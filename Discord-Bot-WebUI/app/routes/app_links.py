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
from flask import Blueprint, jsonify, current_app, request, make_response
from markupsafe import escape

logger = logging.getLogger(__name__)

app_links_bp = Blueprint('app_links', __name__)


def _season_pass_deeplinks_enabled() -> bool:
    """
    Whether iOS should route the season-pass URLs (/pub-league/buy|link-order|claim)
    to the native app.

    This is a ROLLOUT SAFETY SWITCH, off by default. On iOS the app declares only
    the DOMAIN in its entitlement; the SERVER'S AASA decides which paths open the
    app. So the moment these paths are listed, iOS hands them to *whatever* version
    of the app is installed — including an OLD build with no season-pass screens,
    which dead-ends the buyer.

    Sequence to flip it on safely:
      1. Ship the app version that HANDLES these paths, and get it approved and
         live in BOTH the App Store and Play Store.
      2. THEN set AdminConfig `season_pass_deeplinks_enabled = true`.
    Until then, these URLs open in the browser for everyone (the web flow works
    end-to-end), and no installed app can grab them.

    (Android needs no such switch: its assetlinks.json only authorizes the domain,
    and the app's own intent filters — which live in the binary — decide which
    paths it claims. An old Android app simply doesn't declare these paths.)

    Fails to False (browser) on any error — the safe direction.
    """
    try:
        from app.models.admin_config import AdminConfig
        val = AdminConfig.get_setting('season_pass_deeplinks_enabled', False)
        # Parse defensively: get_setting only returns a real bool when the row's
        # data_type is 'boolean'. Stored as a plain string it comes back as
        # "false", and bool("false") is True — so an OFF flag would read as ON.
        if isinstance(val, str):
            return val.strip().lower() in ('true', '1', 'yes', 'on')
        return bool(val)
    except Exception:
        return False


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
    - /m/* - Member identity (player QR scan)
    - /check-in/* - Venue check-in (printed QR sign / NFC sticker at the pitch)
    - /pub-league/buy|link-order|claim* - Season pass (gated by
      season_pass_deeplinks_enabled; see _season_pass_deeplinks_enabled)
    """
    # Get app identifiers from environment
    ios_team_id = os.getenv('IOS_TEAM_ID', 'XXXXXXXXXX')
    ios_bundle_id = os.getenv('IOS_BUNDLE_ID', 'com.example.ecsfc')

    paths = [
        # Substitute response pages (both systems)
        "/ecs-fc/sub-response/*",
        "/sub-rsvp/*",
        # Match detail pages
        "/ecs-fc/matches/*",
        "/match/*",
        # RSVP pages
        "/ecs-fc/rsvp/*",
        "/rsvp/*",
        # OAuth callback bridge — Universal Link target so Discord's
        # HTTPS redirect lands in the app instead of Safari.
        "/oauth/callback*",
        # Member identity card (player QR camera-app scans)
        "/m/*",
        # Venue check-in (printed QR / NFC at the pitch)
        "/check-in/*",
    ]

    # Season-pass paths are gated so we never route them to an app version that
    # can't handle them (iOS routes by SERVER config, not app version). Flip the
    # flag on only once the season-pass app build is live in both stores.
    if _season_pass_deeplinks_enabled():
        paths += [
            # /buy is the QR target; link-order/claim are the tapped return + email
            # links. iOS only fires a Universal Link on a *tap*, so the post-payment
            # redirect is handled by an ecs-fc-scheme:// bounce (see pub_league/routes.py).
            "/pub-league/buy*",
            "/pub-league/link-order*",
            "/pub-league/claim*",
        ]

    # iOS Universal Links configuration
    association = {
        "applinks": {
            "apps": [],  # Required to be empty for universal links
            "details": [
                {
                    "appID": f"{ios_team_id}.{ios_bundle_id}",
                    "paths": paths,
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


def validate_app_link_config():
    """
    Validate App Link env vars at startup.

    Refuses to boot in production if Android/iOS App Link identity is missing
    — without these set, /.well-known/assetlinks.json silently serves a
    placeholder fingerprint and Android App Link verification fails.
    """
    is_production = os.getenv('FLASK_ENV', 'development').lower() == 'production'

    issues = []

    if os.getenv('ANDROID_PACKAGE_NAME', 'com.example.ecsfc') == 'com.example.ecsfc':
        issues.append('ANDROID_PACKAGE_NAME is unset or using placeholder default')

    fingerprints = [fp.strip() for fp in os.getenv('ANDROID_SHA256_FINGERPRINTS', '').split(',') if fp.strip()]
    if not fingerprints:
        issues.append('ANDROID_SHA256_FINGERPRINTS is empty — assetlinks.json will serve placeholder fingerprint')

    if os.getenv('IOS_TEAM_ID', 'XXXXXXXXXX') == 'XXXXXXXXXX':
        issues.append('IOS_TEAM_ID is unset or using placeholder default')

    if os.getenv('IOS_BUNDLE_ID', 'com.example.ecsfc') == 'com.example.ecsfc':
        issues.append('IOS_BUNDLE_ID is unset or using placeholder default')

    if not issues:
        return

    detail = '; '.join(issues)
    if is_production:
        raise RuntimeError(
            f"Refusing to start in production: App Link config incomplete ({detail})"
        )
    logger.warning(f"App Link config issues (dev mode, not blocking boot): {detail}")


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
            },
            "season_pass_buy": {
                "description": "Buy a season pass (redirects into WooCommerce's own checkout)",
                "custom_scheme": "ecs-fc-scheme://buy?division=<classic|premier>",
                "web_url": f"{base_url}/pub-league/buy?division=<classic|premier>&src=app"
            },
            "season_pass_link_order": {
                "description": "Link the season pass(es) from a WooCommerce order to a player",
                "custom_scheme": "ecs-fc-scheme://link-order?order_id=<woo_order_id>&token=<hmac>",
                "web_url": f"{base_url}/pub-league/link-order?order_id=<woo_order_id>&token=<hmac>"
            },
            "season_pass_claim": {
                "description": "Claim a season pass that someone else bought for you",
                "custom_scheme": "ecs-fc-scheme://claim?token=<claim_token>",
                "web_url": f"{base_url}/pub-league/claim?token=<claim_token>"
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


@app_links_bp.route('/oauth/callback', methods=['GET'])
def oauth_callback_bridge():
    """
    HTTPS bridge endpoint for OAuth callbacks.

    Discord (and any future OAuth provider) redirects here after the user
    authorizes. On Android with autoVerify'd App Links and on iOS with the
    /oauth/callback* path registered in apple-app-site-association above,
    this URL is intercepted by the native app and never opens a browser tab.

    For browsers and unverified installs, the page renders a meta-refresh
    deep-link to ecs-fc-scheme://auth?<query> so the OAuth code/state still
    reach the app via the custom scheme. Query params are passed through
    unchanged so the mobile app receives `code`, `state`, `error`, etc.
    exactly as the OAuth provider sent them.
    """
    query = request.query_string.decode('utf-8')
    deep_link = f"ecs-fc-scheme://auth?{query}" if query else "ecs-fc-scheme://auth"
    safe_deep_link = escape(deep_link)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="0; url={safe_deep_link}">
    <title>Returning to app...</title>
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; padding: 2rem; text-align: center; color: #333; }}
        a {{ color: #213e96; }}
    </style>
</head>
<body>
    <p>Returning to the ECS FC app...</p>
    <p><a href="{safe_deep_link}">Tap here if you aren't redirected automatically.</a></p>
</body>
</html>"""

    response = make_response(html, 200)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app_links_bp.route('/robots.txt')
def robots_txt():
    """Serve robots.txt from root URL to guide web crawlers."""
    return current_app.send_static_file('robots.txt')
