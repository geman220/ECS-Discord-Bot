# app/admin/wallet/helpers.py

"""
Wallet Admin Helper Functions

Shared utility functions used across wallet admin routes.
These are extracted to avoid code duplication and improve testability.
"""

import os
import logging
from flask import flash, redirect, url_for

from app.models.wallet import WalletPassType
from app.models.wallet_asset import WalletAsset, WalletTemplate, WalletCertificate
from app.wallet_pass import validate_pass_configuration

logger = logging.getLogger(__name__)


def get_config_status(include_detailed=False):
    """
    Get current wallet configuration status and progress.

    Each pass type (ECS Membership, Pub League) is tracked independently.
    A pass type is ready for pass generation when:
    - Certificates are configured (shared between both)
    - That specific pass type has all required assets
    - That specific pass type has a default template

    Args:
        include_detailed: Include additional details for admin UI

    Returns:
        dict: Configuration status information with per-pass-type details
    """
    status = validate_pass_configuration()

    # Check certificates (Apple and/or Google) - shared between both pass types
    apple_cert_complete = WalletCertificate.has_complete_apple_config()
    google_cert_complete = WalletCertificate.has_complete_google_config()
    cert_complete = apple_cert_complete or google_cert_complete

    # Get pass types
    ecs_type = WalletPassType.get_ecs_membership()
    pub_type = WalletPassType.get_pub_league()

    required_assets = ['icon', 'logo']

    # ===== ECS Membership Status =====
    ecs_assets_complete = False
    ecs_template_complete = False
    ecs_ready = False
    ecs_assets = []

    if ecs_type:
        ecs_assets = WalletAsset.get_assets_by_pass_type(ecs_type.id)
        ecs_assets_complete = all(
            any(a.asset_type == req for a in ecs_assets)
            for req in required_assets
        )
        ecs_template = WalletTemplate.get_default(ecs_type.id, 'apple')
        ecs_template_complete = ecs_template is not None
        ecs_ready = cert_complete and ecs_assets_complete and ecs_template_complete

    # ===== Pub League Status =====
    pub_assets_complete = False
    pub_template_complete = False
    pub_ready = False
    pub_assets = []

    if pub_type:
        pub_assets = WalletAsset.get_assets_by_pass_type(pub_type.id)
        pub_assets_complete = all(
            any(a.asset_type == req for a in pub_assets)
            for req in required_assets
        )
        pub_template = WalletTemplate.get_default(pub_type.id, 'apple')
        pub_template_complete = pub_template is not None
        pub_ready = cert_complete and pub_assets_complete and pub_template_complete

    # ===== Overall Progress Calculation =====
    total_steps = 3  # Certificates + Assets + Templates
    completed_steps = 0

    if cert_complete:
        completed_steps += 1

    assets_complete = ecs_assets_complete or pub_assets_complete
    if assets_complete:
        completed_steps += 1

    templates_complete = ecs_template_complete or pub_template_complete
    if templates_complete:
        completed_steps += 1

    testing_complete = ecs_ready or pub_ready
    woocommerce_configured = bool(os.getenv('WALLET_WEBHOOK_SECRET', ''))

    progress = {
        'certificates': cert_complete,
        'apple_certificates': apple_cert_complete,
        'google_certificates': google_cert_complete,
        'assets': assets_complete,
        'templates': templates_complete,
        'testing': testing_complete,
        'woocommerce': woocommerce_configured,
        'percent': int((completed_steps / total_steps) * 100),
        'ecs': {
            'exists': ecs_type is not None,
            'assets_complete': ecs_assets_complete,
            'template_complete': ecs_template_complete,
            'ready': ecs_ready
        },
        'pub': {
            'exists': pub_type is not None,
            'assets_complete': pub_assets_complete,
            'template_complete': pub_template_complete,
            'ready': pub_ready
        }
    }

    # Additional details for admin UI
    details = {}
    if include_detailed:
        details['pass_types'] = {
            'ecs': {
                'exists': ecs_type is not None,
                'info': ecs_type.to_dict() if ecs_type else None
            },
            'pub': {
                'exists': pub_type is not None,
                'info': pub_type.to_dict() if pub_type else None
            }
        }

        # Certificate details
        details['certificates'] = {
            'apple': {
                'complete': apple_cert_complete,
                'certificate': WalletCertificate.get_active_by_type('certificate', 'apple') is not None,
                'key': WalletCertificate.get_active_by_type('key', 'apple') is not None,
                'wwdr': WalletCertificate.get_active_by_type('wwdr', 'apple') is not None
            },
            'google': {
                'complete': google_cert_complete,
                'credentials': WalletCertificate.get_active_by_type('credentials', 'google') is not None
            }
        }

        # Asset details
        details['assets'] = {
            'ecs': {a.asset_type: a.to_dict() for a in ecs_assets} if ecs_assets else {},
            'pub': {a.asset_type: a.to_dict() for a in pub_assets} if pub_assets else {},
            'required': required_assets
        }

    return {
        'status': status,
        'progress': progress,
        'details': details if include_detailed else None
    }


def get_pass_type_or_redirect(pass_type_code, redirect_url='wallet_config.templates'):
    """
    Get a pass type object by code, or return redirect response if not found.

    Args:
        pass_type_code: 'ecs' or 'pub'
        redirect_url: URL to redirect to on error

    Returns:
        tuple: (pass_type_object, None) on success, or (None, redirect_response) on error
    """
    if pass_type_code == 'ecs':
        pass_obj = WalletPassType.get_ecs_membership()
        if not pass_obj:
            flash('ECS Membership pass type not found.', 'error')
            return None, redirect(url_for(redirect_url))
    elif pass_type_code == 'pub':
        pass_obj = WalletPassType.get_pub_league()
        if not pass_obj:
            flash('Pub League pass type not found.', 'error')
            return None, redirect(url_for(redirect_url))
    else:
        flash('Invalid pass type.', 'error')
        return None, redirect(url_for(redirect_url))

    return pass_obj, None


def get_wallet_config_context():
    """
    Get common context data for wallet config templates.

    Returns:
        dict: Common template context variables
    """
    config = get_config_status(include_detailed=True)

    return {
        'wallet_config': config,
        'ecs_type': WalletPassType.get_ecs_membership(),
        'pub_type': WalletPassType.get_pub_league(),
    }


def log_wallet_action(action, details=None, level='info'):
    """
    Log a wallet-related admin action.

    Args:
        action: Description of the action
        details: Additional details dict
        level: Log level ('info', 'warning', 'error')
    """
    message = f"Wallet Admin: {action}"
    if details:
        message += f" - {details}"

    if level == 'warning':
        logger.warning(message)
    elif level == 'error':
        logger.error(message)
    else:
        logger.info(message)
