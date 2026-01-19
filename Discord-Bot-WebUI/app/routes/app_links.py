# app/routes/app_links.py

"""
App Links Routes

Serves well-known files for iOS Universal Links and Android App Links.
These files enable the native mobile app to intercept specific URLs and
handle them in-app instead of the browser.

iOS: /.well-known/apple-app-site-association
Android: /.well-known/assetlinks.json
"""

import os
import logging
from flask import Blueprint, jsonify, current_app

logger = logging.getLogger(__name__)

app_links_bp = Blueprint('app_links', __name__)


@app_links_bp.route('/.well-known/apple-app-site-association')
def apple_app_site_association():
    """
    Apple App Site Association file for iOS Universal Links.

    This file tells iOS which URLs should be opened in the native app.
    The app must also be configured with the Associated Domains entitlement.

    Paths covered:
    - /ecs-fc/sub-response/* - ECS FC substitute response pages
    - /sub-rsvp/* - Pub League substitute response pages
    - /ecs-fc/matches/* - ECS FC match details
    - /match/* - Pub League match pages
    """
    # Get app identifiers from environment
    ios_team_id = os.getenv('IOS_TEAM_ID', 'XXXXXXXXXX')
    ios_bundle_id = os.getenv('IOS_BUNDLE_ID', 'com.example.ecsfc')

    # iOS Universal Links configuration
    association = {
        "applinks": {
            "apps": [],  # Required to be empty for universal links
            "details": [
                {
                    "appID": f"{ios_team_id}.{ios_bundle_id}",
                    "paths": [
                        # Substitute response pages (both systems)
                        "/ecs-fc/sub-response/*",
                        "/sub-rsvp/*",
                        # Match detail pages
                        "/ecs-fc/matches/*",
                        "/match/*",
                        # RSVP pages
                        "/ecs-fc/rsvp/*",
                        "/rsvp/*"
                    ]
                }
            ]
        },
        "webcredentials": {
            "apps": [f"{ios_team_id}.{ios_bundle_id}"]
        }
    }

    response = jsonify(association)
    # Apple requires application/json content type
    response.headers['Content-Type'] = 'application/json'
    return response


@app_links_bp.route('/.well-known/assetlinks.json')
def android_asset_links():
    """
    Android Asset Links file for Android App Links.

    This file tells Android which URLs should be opened in the native app.
    The app must also declare intent filters for these URLs.

    Paths covered:
    - /ecs-fc/sub-response/* - ECS FC substitute response pages
    - /sub-rsvp/* - Pub League substitute response pages
    - /ecs-fc/matches/* - ECS FC match details
    - /match/* - Pub League match pages
    """
    # Get app identifiers from environment
    android_package = os.getenv('ANDROID_PACKAGE_NAME', 'com.example.ecsfc')

    # SHA256 fingerprints of the signing certificates
    # In production, get these from your release keystore
    android_fingerprints = os.getenv('ANDROID_SHA256_FINGERPRINTS', '')
    fingerprints = [fp.strip() for fp in android_fingerprints.split(',') if fp.strip()]

    # Default debug fingerprint if none configured
    if not fingerprints:
        fingerprints = ["00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00"]

    # Android App Links configuration
    asset_links = [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": android_package,
                "sha256_cert_fingerprints": fingerprints
            }
        }
    ]

    response = jsonify(asset_links)
    response.headers['Content-Type'] = 'application/json'
    return response


@app_links_bp.route('/.well-known/deep-links')
def deep_link_info():
    """
    Documentation endpoint for available deep link schemes.

    Returns information about all supported deep link formats
    for both the custom URL scheme and web URLs.
    """
    base_url = current_app.config.get('BASE_URL', os.getenv('BASE_URL', 'https://ecs-portal.com'))

    deep_links = {
        "scheme": "ecs-fc-scheme",
        "web_base": base_url,
        "supported_links": {
            "substitute_response": {
                "description": "Respond to a substitute request",
                "custom_scheme": {
                    "ecs_fc": "ecs-fc-scheme://sub-response/<token>",
                    "pub_league": "ecs-fc-scheme://sub-rsvp/<token>"
                },
                "web_url": {
                    "ecs_fc": f"{base_url}/ecs-fc/sub-response/<token>",
                    "pub_league": f"{base_url}/sub-rsvp/<token>"
                }
            },
            "match_details": {
                "description": "View match details",
                "custom_scheme": {
                    "ecs_fc": "ecs-fc-scheme://match/<match_id>",
                    "pub_league": "ecs-fc-scheme://match/<match_id>"
                },
                "web_url": {
                    "ecs_fc": f"{base_url}/ecs-fc/matches/<match_id>",
                    "pub_league": f"{base_url}/match/<match_id>"
                }
            },
            "rsvp": {
                "description": "RSVP to a match",
                "custom_scheme": "ecs-fc-scheme://rsvp/<match_id>",
                "web_url": {
                    "ecs_fc": f"{base_url}/ecs-fc/rsvp/<match_id>",
                    "pub_league": f"{base_url}/rsvp/<match_id>"
                }
            },
            "messages": {
                "description": "View messages from a user",
                "custom_scheme": "ecs-fc-scheme://messages/<user_id>"
            }
        },
        "ios_integration": {
            "associated_domains": [
                f"applinks:{base_url.replace('https://', '').replace('http://', '')}",
                f"webcredentials:{base_url.replace('https://', '').replace('http://', '')}"
            ],
            "info_plist_url_scheme": "ecs-fc-scheme"
        },
        "android_integration": {
            "intent_filter_hosts": [
                base_url.replace('https://', '').replace('http://', '')
            ],
            "custom_scheme": "ecs-fc-scheme"
        }
    }

    return jsonify(deep_links)
