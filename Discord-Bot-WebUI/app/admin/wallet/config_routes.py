# app/admin/wallet/config_routes.py

"""
Wallet Configuration Routes - Core

Handles core wallet configuration:
- Dashboard
- Certificates (upload, toggle, delete)
- Assets (upload, delete, serve)
- Templates (upload, delete, generate default)
- Setup wizard
- Diagnostics
"""

import os
import json
import logging
from flask import render_template, request, jsonify, flash, redirect, url_for, send_file, current_app, session
from flask_login import login_required

from datetime import datetime

from app.core import db
from app.models.wallet import WalletPassType, WalletPass, WalletPassCheckin, PassStatus
from app.models.wallet_asset import WalletAsset, WalletTemplate, WalletCertificate
from app.decorators import role_required
from app.wallet_pass import validate_pass_configuration
from app.services.asset_service import asset_service, ASSET_TYPES, CERT_TYPES

from . import wallet_config_bp
from .helpers import get_config_status, get_wallet_config_context

logger = logging.getLogger(__name__)


# =============================================================================
# AUTO-INITIALIZATION HELPERS
# =============================================================================

def _auto_init_pass_types():
    """Auto-initialize pass types if they don't exist.

    This allows non-technical users to use the wizard without running CLI commands.
    """
    created = []

    # ECS Membership pass type
    ecs_type = WalletPassType.query.filter_by(code='ecs_membership').first()
    if not ecs_type:
        ecs_type = WalletPassType(
            code='ecs_membership',
            name='ECS Membership',
            description='Annual ECS FC membership card valid for one calendar year',
            template_name='ecs_membership',
            background_color='#1a472a',
            foreground_color='#ffffff',
            label_color='#c8c8c8',
            logo_text='ECS',
            validity_type='annual',
            validity_duration_days=365,
            grace_period_days=30,
            woo_product_patterns=json.dumps([
                r'ECS\s+\d{4}\s+Membership',
                r'ECS\s+Membership\s+\d{4}',
                r'ECS\s+Membership\s+Card',
                r'ECS\s+Membership\s+Package\s+\d{4}'
            ]),
            apple_pass_type_id='pass.com.weareecs.membership',
            google_issuer_id='3388000000022958274',
            google_class_id='ecs_membership',
            is_active=True,
            display_order=1
        )
        db.session.add(ecs_type)
        created.append('ECS Membership')

    # Pub League pass type
    pub_type = WalletPassType.query.filter_by(code='pub_league').first()
    if not pub_type:
        pub_type = WalletPassType(
            code='pub_league',
            name='Pub League',
            description='Seasonal Pub League membership card valid for one season',
            template_name='pub_league',
            background_color='#213e96',
            foreground_color='#ffffff',
            label_color='#c8c8c8',
            logo_text='ECS Pub League',
            validity_type='seasonal',
            validity_duration_days=182,
            grace_period_days=30,
            woo_product_patterns=json.dumps([
                r'ECS\s+Pub\s+League',
                r'Pub\s+League\s+(Spring|Fall|Summer|Winter)\s+\d{4}'
            ]),
            apple_pass_type_id='pass.com.weareecs.membership',
            google_issuer_id='3388000000022958274',
            google_class_id='pub_league',
            is_active=True,
            display_order=2
        )
        db.session.add(pub_type)
        created.append('Pub League')

    if created:
        db.session.commit()
        logger.info(f"Auto-initialized pass types: {', '.join(created)}")

    return created


# =============================================================================
# DASHBOARD - DEPRECATED, REDIRECTS TO MAIN WALLET MANAGEMENT
# =============================================================================

@wallet_config_bp.route('/')
@wallet_config_bp.route('/dashboard')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def dashboard():
    """
    DEPRECATED: Redirects to main wallet management dashboard.

    The old config dashboard at /admin/wallet/config/dashboard has been
    deprecated in favor of the unified wallet management at /admin/wallet/
    """
    return redirect(url_for('wallet_admin.wallet_management'))


@wallet_config_bp.route('/getting-started')
@login_required
@role_required(['Global Admin'])
def getting_started():
    """Redirect to setup wizard - the primary configuration entry point"""
    return redirect(url_for('wallet_config.setup_wizard'))


# =============================================================================
# SETUP WIZARD
# =============================================================================

@wallet_config_bp.route('/wizard')
@wallet_config_bp.route('/wizard/<step>')
@login_required
@role_required(['Global Admin'])
def setup_wizard(step='certificates'):
    """Interactive setup wizard with step-by-step configuration"""
    try:
        valid_steps = ['certificates', 'assets', 'templates', 'testing', 'woocommerce']
        if step not in valid_steps:
            step = 'certificates'

        config = get_config_status(include_detailed=True)

        # Get pass types - auto-initialize if they don't exist
        ecs_type = WalletPassType.get_ecs_membership()
        pub_type = WalletPassType.get_pub_league()

        # Auto-create pass types if they don't exist (for non-technical users)
        if not ecs_type or not pub_type:
            try:
                _auto_init_pass_types()
                ecs_type = WalletPassType.get_ecs_membership()
                pub_type = WalletPassType.get_pub_league()
                if ecs_type or pub_type:
                    flash('Pass types have been automatically initialized.', 'success')
            except Exception as e:
                logger.warning(f"Could not auto-initialize pass types: {e}")

        # Build step_data based on current step
        step_data = {}

        if step == 'certificates':
            # Get existing certificates organized by type
            apple_certs = {c.type: c for c in WalletCertificate.query.filter_by(platform='apple').all()}
            google_certs = {c.type: c for c in WalletCertificate.query.filter_by(platform='google').all()}

            # Get APNs key info for easier template access
            apns_key = apple_certs.get('apns_key')
            apns_key_info = None
            if apns_key:
                apns_key_info = {
                    'key_id': apns_key.apns_key_id,
                    'team_id': apns_key.team_identifier,
                    'name': apns_key.name
                }

            step_data = {
                'apple_certs': apple_certs,
                'google_certs': google_certs,
                'cert_types': CERT_TYPES,
                'apns_key': apns_key_info
            }

        elif step == 'assets':
            # Check if pass types exist - if not, show init button in template
            if not ecs_type or not pub_type:
                step_data = {
                    'pass_types_missing': True,
                    'asset_types': ASSET_TYPES,
                    'ecs_assets': {},
                    'pub_assets': {}
                }
            else:
                # Get existing assets
                ecs_assets = {a.asset_type: a for a in WalletAsset.get_assets_by_pass_type(ecs_type.id)}
                pub_assets = {a.asset_type: a for a in WalletAsset.get_assets_by_pass_type(pub_type.id)}

                step_data = {
                    'pass_types_missing': False,
                    'asset_types': ASSET_TYPES,
                    'ecs_assets': ecs_assets,
                    'pub_assets': pub_assets
                }

        elif step == 'templates':
            # Check if pass types exist - if not, show init button in template
            if not ecs_type or not pub_type:
                step_data = {
                    'pass_types_missing': True,
                    'ecs_templates': [],
                    'pub_templates': []
                }
            else:
                # Get existing templates
                ecs_templates = WalletTemplate.query.filter_by(pass_type_id=ecs_type.id).all()
                pub_templates = WalletTemplate.query.filter_by(pass_type_id=pub_type.id).all()

                step_data = {
                    'pass_types_missing': False,
                    'ecs_templates': ecs_templates,
                    'pub_templates': pub_templates
                }

        elif step == 'testing':
            # Get test results if available
            test_results = session.get('wallet_test_results', None)

            step_data = {
                'test_results': test_results
            }

        elif step == 'woocommerce':
            # WooCommerce integration step
            webhook_secret = os.getenv('WALLET_WEBHOOK_SECRET', '')

            # Get WooCommerce site URL from database first, then fall back to env var
            from app.models.admin_config import AdminConfig
            woocommerce_site_url = AdminConfig.get_setting('woocommerce_site_url', '')
            if not woocommerce_site_url:
                woocommerce_site_url = os.getenv('WOOCOMMERCE_SITE_URL', '')

            step_data = {
                'webhook_configured': bool(webhook_secret),
                'webhook_secret': webhook_secret if webhook_secret else None,
                'woocommerce_site_url': woocommerce_site_url if woocommerce_site_url else None,
                'last_webhook_time': None  # Could track this in DB if needed
            }

        return render_template(
            'admin/wallet_config/wizard_flowbite.html',
            current_step=step,
            wallet_config=config,
            ecs_type=ecs_type,
            pub_type=pub_type,
            step_data=step_data
        )

    except Exception as e:
        logger.error(f"Error loading wallet setup wizard: {str(e)}", exc_info=True)
        flash('Error loading setup wizard.', 'error')
        return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/wizard/save-woocommerce-url', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def save_woocommerce_url():
    """Save WooCommerce site URL to database"""
    try:
        from flask_login import current_user
        from app.models.admin_config import AdminConfig

        data = request.get_json()
        woocommerce_url = data.get('woocommerce_site_url', '').strip()

        # Validate URL format
        if woocommerce_url:
            if not woocommerce_url.startswith(('http://', 'https://')):
                return jsonify({'success': False, 'error': 'URL must start with http:// or https://'}), 400
            # Remove trailing slash for consistency
            woocommerce_url = woocommerce_url.rstrip('/')

        # Save to database using AdminConfig
        AdminConfig.set_setting(
            key='woocommerce_site_url',
            value=woocommerce_url,
            description='WooCommerce site URL for wallet pass callback',
            category='wallet',
            data_type='string',
            user_id=current_user.id if current_user else None
        )

        logger.info(f"WooCommerce site URL saved: {woocommerce_url}")
        return jsonify({
            'success': True,
            'message': 'WooCommerce site URL saved successfully',
            'url': woocommerce_url
        })

    except Exception as e:
        logger.error(f"Error saving WooCommerce URL: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# CERTIFICATES
# =============================================================================

@wallet_config_bp.route('/certificates')
@login_required
@role_required(['Global Admin'])
def certificates():
    """Certificate management page"""
    try:
        certificates = {
            'apple': asset_service.get_certificates_by_platform('apple'),
            'google': asset_service.get_certificates_by_platform('google')
        }

        apple_complete = WalletCertificate.has_complete_apple_config()
        google_complete = WalletCertificate.has_complete_google_config()

        return render_template(
            'admin/wallet_config/certificates_flowbite.html',
            certificates=certificates,
            cert_types=CERT_TYPES,
            apple_complete=apple_complete,
            google_complete=google_complete
        )

    except Exception as e:
        logger.error(f"Error loading certificates page: {str(e)}", exc_info=True)
        flash('Error loading certificates page.', 'error')
        return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/certificates/upload', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def upload_certificate():
    """Handle certificate upload"""
    def redirect_back():
        is_wizard = request.form.get('is_wizard', 'false') == 'true'
        if is_wizard:
            return redirect(url_for('wallet_config.setup_wizard', step='certificates'))
        return redirect(url_for('wallet_config.certificates'))

    try:
        # Get form data
        platform = request.form.get('platform')
        cert_type = request.form.get('cert_type')
        name = request.form.get('name')
        team_identifier = request.form.get('team_identifier')
        pass_type_identifier = request.form.get('pass_type_identifier')
        issuer_id = request.form.get('issuer_id')
        apns_key_id = request.form.get('apns_key_id')
        is_wizard = request.form.get('is_wizard', 'false') == 'true'

        # For APNs key uploads, auto-generate name if not provided
        if cert_type == 'apns_key' and not name:
            name = f'APNs Key {apns_key_id}' if apns_key_id else 'APNs Push Key'

        # Validate required fields
        if not all([platform, cert_type, name]):
            flash('Platform, certificate type, and name are required.', 'error')
            return redirect_back()

        # Validate APNs key specific fields
        if cert_type == 'apns_key':
            if not apns_key_id:
                flash('APNs Key ID is required for push key uploads.', 'error')
                return redirect_back()
            if not team_identifier:
                flash('Team ID is required for push key uploads.', 'error')
                return redirect_back()

        # Check if file was provided
        if 'certificate_file' not in request.files:
            flash('No certificate file provided.', 'error')
            return redirect_back()

        file = request.files['certificate_file']
        if file.filename == '':
            flash('No certificate file selected.', 'error')
            return redirect_back()

        # Upload certificate
        certificate = asset_service.upload_certificate(
            file=file,
            cert_type=cert_type,
            platform=platform,
            name=name,
            team_identifier=team_identifier,
            pass_type_identifier=pass_type_identifier,
            issuer_id=issuer_id,
            apns_key_id=apns_key_id
        )

        flash(f'Certificate "{name}" uploaded successfully.', 'success')

        if is_wizard and WalletCertificate.has_complete_apple_config():
            return redirect(url_for('wallet_config.setup_wizard', step='assets'))

        return redirect_back()

    except ValueError as ve:
        logger.warning(f"Certificate validation error: {str(ve)}")
        flash(f'Invalid certificate: {str(ve)}', 'error')
        return redirect_back()

    except Exception as e:
        logger.error(f"Error uploading certificate: {str(e)}", exc_info=True)
        flash(f'Error uploading certificate: {str(e)}', 'error')
        return redirect_back()


@wallet_config_bp.route('/certificates/<int:cert_id>/toggle', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def toggle_certificate(cert_id):
    """Toggle certificate active status"""
    try:
        certificate = asset_service.toggle_certificate(cert_id)
        status = 'activated' if certificate.is_active else 'deactivated'
        flash(f'Certificate "{certificate.name}" {status} successfully.', 'success')
        return redirect(url_for('wallet_config.certificates'))

    except Exception as e:
        logger.error(f"Error toggling certificate {cert_id}: {str(e)}", exc_info=True)
        flash(f'Error updating certificate: {str(e)}', 'error')
        return redirect(url_for('wallet_config.certificates'))


@wallet_config_bp.route('/certificates/<int:cert_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def delete_certificate(cert_id):
    """Delete a certificate"""
    try:
        asset_service.delete_certificate(cert_id)
        flash('Certificate deleted successfully.', 'success')
        return redirect(url_for('wallet_config.certificates'))

    except Exception as e:
        logger.error(f"Error deleting certificate {cert_id}: {str(e)}", exc_info=True)
        flash(f'Error deleting certificate: {str(e)}', 'error')
        return redirect(url_for('wallet_config.certificates'))


# =============================================================================
# ASSETS
# =============================================================================

@wallet_config_bp.route('/assets')
@login_required
@role_required(['Global Admin'])
def assets():
    """Asset management page"""
    try:
        ecs_type = WalletPassType.get_ecs_membership()
        pub_type = WalletPassType.get_pub_league()

        pass_types_missing = not ecs_type or not pub_type

        if pass_types_missing:
            ecs_assets = {}
            pub_assets = {}
        else:
            ecs_assets = {a.asset_type: a for a in WalletAsset.get_assets_by_pass_type(ecs_type.id)}
            pub_assets = {a.asset_type: a for a in WalletAsset.get_assets_by_pass_type(pub_type.id)}

        return render_template(
            'admin/wallet_config/assets_flowbite.html',
            asset_types=ASSET_TYPES,
            ecs_type=ecs_type,
            pub_type=pub_type,
            ecs_assets=ecs_assets,
            pub_assets=pub_assets,
            pass_types_missing=pass_types_missing
        )

    except Exception as e:
        logger.error(f"Error loading asset management page: {str(e)}", exc_info=True)
        flash('Error loading asset management page.', 'error')
        return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/assets/upload', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def upload_asset():
    """Handle asset upload"""
    # Check if request came from wizard
    is_wizard = request.form.get('is_wizard', 'false') == 'true'
    redirect_url = url_for('wallet_config.setup_wizard', step='assets') if is_wizard else url_for('wallet_config.assets')

    try:
        pass_type_id = request.form.get('pass_type_id')
        asset_type = request.form.get('asset_type')

        if not pass_type_id or not asset_type:
            flash('Pass type and asset type are required.', 'error')
            return redirect(redirect_url)

        if 'asset_file' not in request.files:
            flash('No asset file provided.', 'error')
            return redirect(redirect_url)

        file = request.files['asset_file']
        if file.filename == '':
            flash('No asset file selected.', 'error')
            return redirect(redirect_url)

        asset = asset_service.upload_asset(
            file=file,
            asset_type=asset_type,
            pass_type_id=int(pass_type_id)
        )

        # Push update to all existing passes of this type
        try:
            from app.wallet_pass.services.pass_service import pass_service
            push_result = pass_service.update_pass_type_design(int(pass_type_id))
            logger.info(f"Pushed asset update to passes: {push_result}")
        except Exception as push_err:
            logger.warning(f"Failed to push asset update: {push_err}")

        flash(f'Asset "{asset_type}" uploaded successfully.', 'success')
        return redirect(redirect_url)

    except ValueError as ve:
        flash(f'Invalid asset: {str(ve)}', 'error')
        return redirect(redirect_url)

    except Exception as e:
        logger.error(f"Error uploading asset: {str(e)}", exc_info=True)
        flash(f'Error uploading asset: {str(e)}', 'error')
        return redirect(redirect_url)


@wallet_config_bp.route('/assets/<int:asset_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def delete_asset(asset_id):
    """Delete an asset"""
    # Check if request came from wizard
    is_wizard = request.form.get('is_wizard', 'false') == 'true'
    redirect_url = url_for('wallet_config.setup_wizard', step='assets') if is_wizard else url_for('wallet_config.assets')

    try:
        asset_service.delete_asset(asset_id)
        flash('Asset deleted successfully.', 'success')
        return redirect(redirect_url)

    except Exception as e:
        logger.error(f"Error deleting asset {asset_id}: {str(e)}", exc_info=True)
        flash(f'Error deleting asset: {str(e)}', 'error')
        return redirect(redirect_url)


@wallet_config_bp.route('/assets/<int:asset_id>')
@login_required
def get_asset(asset_id):
    """Serve an asset file"""
    try:
        asset = WalletAsset.query.get_or_404(asset_id)

        paths_to_try = [
            asset.file_path,
            os.path.join('app', asset.file_path) if not asset.file_path.startswith('app/') else asset.file_path,
        ]

        for try_path in paths_to_try:
            if os.path.exists(try_path):
                absolute_path = os.path.abspath(try_path)
                return send_file(
                    absolute_path,
                    mimetype=asset.content_type or 'application/octet-stream',
                    as_attachment=False
                )

        logger.error(f"Asset file not found for asset {asset_id}")
        return jsonify({'error': 'Asset file not found'}), 404

    except Exception as e:
        logger.error(f"Error serving asset {asset_id}: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# =============================================================================
# TEMPLATES
# =============================================================================

@wallet_config_bp.route('/templates')
@login_required
@role_required(['Global Admin'])
def templates():
    """Template management page"""
    try:
        ecs_type = WalletPassType.get_ecs_membership()
        pub_type = WalletPassType.get_pub_league()

        ecs_templates = WalletTemplate.query.filter_by(pass_type_id=ecs_type.id).all() if ecs_type else []
        pub_templates = WalletTemplate.query.filter_by(pass_type_id=pub_type.id).all() if pub_type else []

        return render_template(
            'admin/wallet_config/templates_flowbite.html',
            ecs_type=ecs_type,
            pub_type=pub_type,
            ecs_templates=ecs_templates,
            pub_templates=pub_templates
        )

    except Exception as e:
        logger.error(f"Error loading templates page: {str(e)}", exc_info=True)
        flash('Error loading templates page.', 'error')
        return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/templates/<int:template_id>/set-default', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def set_default_template(template_id):
    """Set a template as default"""
    try:
        asset_service.set_default_template(template_id)
        flash('Default template updated.', 'success')
        return redirect(url_for('wallet_config.templates'))

    except Exception as e:
        logger.error(f"Error setting default template: {str(e)}", exc_info=True)
        flash(f'Error setting default template: {str(e)}', 'error')
        return redirect(url_for('wallet_config.templates'))


@wallet_config_bp.route('/templates/<int:template_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def delete_template(template_id):
    """Delete a template"""
    try:
        asset_service.delete_template(template_id)
        flash('Template deleted successfully.', 'success')
        return redirect(url_for('wallet_config.templates'))

    except Exception as e:
        logger.error(f"Error deleting template {template_id}: {str(e)}", exc_info=True)
        flash(f'Error deleting template: {str(e)}', 'error')
        return redirect(url_for('wallet_config.templates'))


@wallet_config_bp.route('/templates/generate-default', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def generate_default_template():
    """Generate a default template"""
    try:
        pass_type_id = request.form.get('pass_type_id')
        platform = request.form.get('platform', 'apple')

        if not pass_type_id:
            flash('Pass type is required.', 'error')
            return redirect(url_for('wallet_config.templates'))

        pass_type = WalletPassType.query.get_or_404(pass_type_id)

        if platform == 'apple':
            template_content = {
                "formatVersion": 1,
                "passTypeIdentifier": pass_type.apple_pass_type_id,
                "serialNumber": "{{serial_number}}",
                "teamIdentifier": "{{team_identifier}}",
                "organizationName": "Emerald City Supporters",
                "description": pass_type.description,
                "logoText": pass_type.logo_text,
                "foregroundColor": pass_type.foreground_color,
                "backgroundColor": pass_type.background_color,
                "labelColor": pass_type.label_color,
                "generic": {
                    "primaryFields": [
                        {"key": "member", "label": "MEMBER", "value": "{{member_name}}"}
                    ],
                    "secondaryFields": [
                        {"key": "validity", "label": "VALID FOR", "value": "{{validity}}"}
                    ],
                    "auxiliaryFields": [
                        {"key": "team", "label": "TEAM", "value": "{{team_name}}"}
                    ],
                    "backFields": [
                        {
                            "key": "terms",
                            "label": "TERMS & CONDITIONS",
                            "value": "This pass identifies the holder as a member of the Emerald City Supporters. Membership is non-transferable."
                        },
                        {"key": "website", "label": "WEBSITE", "value": "https://www.weareecs.com"}
                    ]
                },
                "barcodes": [
                    {
                        "format": "PKBarcodeFormatQR",
                        "message": "{{barcode_data}}",
                        "messageEncoding": "utf-8",
                        "altText": "{{barcode_data}}"
                    }
                ]
            }

            template = asset_service.upload_template(
                name=f"Default {pass_type.name} Template",
                content=json.dumps(template_content, indent=2),
                pass_type_id=int(pass_type_id),
                platform=platform,
                is_default=True
            )

            flash(f'Default {platform} template generated for {pass_type.name}.', 'success')

            if request.form.get('is_wizard', 'false') == 'true':
                return redirect(url_for('wallet_config.setup_wizard', step='templates'))

            return redirect(url_for('wallet_config.templates'))

        elif platform == 'google':
            # Google Wallet template structure (Generic Pass format)
            template_content = {
                "issuerName": "Emerald City Supporters",
                "header": {
                    "defaultValue": {
                        "language": "en-US",
                        "value": "{{member_name}}"
                    }
                },
                "subheader": {
                    "defaultValue": {
                        "language": "en-US",
                        "value": pass_type.description or pass_type.name
                    }
                },
                "hexBackgroundColor": pass_type.background_color or "#1a472a",
                "textModulesData": [
                    {
                        "header": "Member",
                        "body": "{{member_name}}"
                    },
                    {
                        "header": "Valid For",
                        "body": "{{validity}}"
                    },
                    {
                        "header": "Team",
                        "body": "{{team_name}}"
                    }
                ],
                "linksModuleData": {
                    "uris": [
                        {
                            "uri": "https://www.weareecs.com",
                            "description": "ECS Website"
                        },
                        {
                            "uri": "https://portal.ecsfc.com",
                            "description": "Member Portal"
                        }
                    ]
                },
                "barcode": {
                    "type": "QR_CODE",
                    "value": "{{barcode_data}}",
                    "alternateText": "{{barcode_data}}"
                }
            }

            template = asset_service.upload_template(
                name=f"Default {pass_type.name} Google Template",
                content=json.dumps(template_content, indent=2),
                pass_type_id=int(pass_type_id),
                platform=platform,
                is_default=True
            )

            flash(f'Default Google Wallet template generated for {pass_type.name}.', 'success')

            if request.form.get('is_wizard', 'false') == 'true':
                return redirect(url_for('wallet_config.setup_wizard', step='templates'))

            return redirect(url_for('wallet_config.templates'))

        else:
            flash('Invalid platform specified.', 'error')
            return redirect(url_for('wallet_config.templates'))

    except Exception as e:
        logger.error(f"Error generating default template: {str(e)}", exc_info=True)
        flash(f'Error generating template: {str(e)}', 'error')
        return redirect(url_for('wallet_config.templates'))


# =============================================================================
# DIAGNOSTICS & TESTING
# =============================================================================

@wallet_config_bp.route('/test')
@login_required
@role_required(['Global Admin'])
def test_config():
    """Test wallet configuration"""
    try:
        config_status = validate_pass_configuration()

        test_results = {
            'configuration': config_status,
            'tests': []
        }

        # Test Apple certificates
        try:
            apple_cert_complete = WalletCertificate.has_complete_apple_config()
            test_results['tests'].append({
                'name': 'Apple Wallet Certificates',
                'status': 'passed' if apple_cert_complete else 'warning',
                'message': "All required Apple certificates are present" if apple_cert_complete else "Missing required Apple certificates"
            })
        except Exception as e:
            test_results['tests'].append({
                'name': 'Apple Wallet Certificates',
                'status': 'failed',
                'message': f'Error testing Apple certificates: {str(e)}'
            })

        # Test Google certificates
        try:
            google_cert_complete = WalletCertificate.has_complete_google_config()
            test_results['tests'].append({
                'name': 'Google Wallet Credentials',
                'status': 'passed' if google_cert_complete else 'info',
                'message': "Google Wallet credentials are present" if google_cert_complete else "Google Wallet credentials not configured (optional)"
            })
        except Exception as e:
            test_results['tests'].append({
                'name': 'Google Wallet Credentials',
                'status': 'failed',
                'message': f'Error testing Google credentials: {str(e)}'
            })

        # Test assets
        try:
            ecs_type = WalletPassType.get_ecs_membership()
            pub_type = WalletPassType.get_pub_league()

            assets_complete = False
            assets_message = "Could not check assets - pass types not configured"

            if ecs_type and pub_type:
                ecs_assets = WalletAsset.get_assets_by_pass_type(ecs_type.id)
                pub_assets = WalletAsset.get_assets_by_pass_type(pub_type.id)

                required_assets = ['icon', 'logo']
                ecs_missing = [req for req in required_assets if not any(a.asset_type == req for a in ecs_assets)]
                pub_missing = [req for req in required_assets if not any(a.asset_type == req for a in pub_assets)]

                if not ecs_missing and not pub_missing:
                    assets_complete = True
                    assets_message = "All required assets are present"
                else:
                    assets_message = "Missing required assets: "
                    if ecs_missing:
                        assets_message += f"ECS: {', '.join(ecs_missing)} "
                    if pub_missing:
                        assets_message += f"Pub League: {', '.join(pub_missing)}"

            test_results['tests'].append({
                'name': 'Asset Configuration',
                'status': 'passed' if assets_complete else 'failed',
                'message': assets_message
            })
        except Exception as e:
            test_results['tests'].append({
                'name': 'Asset Configuration',
                'status': 'failed',
                'message': f'Error testing assets: {str(e)}'
            })

        return render_template(
            'admin/wallet_config/test_results_flowbite.html',
            test_results=test_results,
            now=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        )

    except Exception as e:
        logger.error(f"Error testing wallet configuration: {str(e)}", exc_info=True)
        flash(f'Error testing configuration: {str(e)}', 'error')
        return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/diagnostics')
@login_required
@role_required(['Global Admin'])
def diagnostics():
    """Run wallet diagnostics"""
    try:
        config_status = validate_pass_configuration()

        # System info - updated to not show legacy filesystem paths
        system_info = {
            'python_version': os.popen('python --version').read().strip(),
            'flask_env': os.getenv('FLASK_ENV', 'production'),
            'debug_mode': current_app.debug,
            'wallet_webhook_secret': bool(os.getenv('WALLET_WEBHOOK_SECRET')),
            'app_path': current_app.root_path,
            'asset_path': 'Database-backed (no filesystem)',
            'cert_path': 'Database-backed (no filesystem)',
            'template_path': 'Database-backed (no filesystem)',
            'pass_type_id': 'Configured per pass type',
            'team_id': 'Configured in certificates'
        }

        # Directory checks - mark as database-backed since we don't use filesystem
        directory_checks = {
            'assets_dir': {'exists': True, 'writable': True, 'note': 'Database-backed'},
            'certs_dir': {'exists': True, 'writable': True, 'note': 'Database-backed'},
            'templates_dir': {'exists': True, 'writable': True, 'note': 'Database-backed'}
        }

        # Build database_checks with the structure template expects
        ecs_type = WalletPassType.get_ecs_membership()
        pub_type = WalletPassType.get_pub_league()

        # Pass Types section
        pass_types_data = {
            'ecs_type': {
                'exists': ecs_type is not None,
                'details': ecs_type.to_dict() if ecs_type else None
            },
            'pub_type': {
                'exists': pub_type is not None,
                'details': pub_type.to_dict() if pub_type else None
            }
        }

        # Certificates section
        apple_certs = {}
        for cert in WalletCertificate.query.filter_by(platform='apple').all():
            apple_certs[cert.type] = {
                'name': cert.name,
                'file_name': cert.file_name,
                'is_active': cert.is_active
            }

        certificates_data = {
            'complete': WalletCertificate.has_complete_apple_config(),
            'apple': apple_certs if apple_certs else None
        }

        # Assets section
        ecs_assets = {}
        pub_assets = {}
        if ecs_type:
            for asset in WalletAsset.get_assets_by_pass_type(ecs_type.id):
                ecs_assets[asset.asset_type] = {
                    'file_name': asset.file_name,
                    'content_type': asset.content_type
                }
        if pub_type:
            for asset in WalletAsset.get_assets_by_pass_type(pub_type.id):
                pub_assets[asset.asset_type] = {
                    'file_name': asset.file_name,
                    'content_type': asset.content_type
                }

        assets_data = {
            'ecs_assets': ecs_assets if ecs_assets else None,
            'pub_assets': pub_assets if pub_assets else None
        }

        # Templates section
        ecs_templates = []
        pub_templates = []
        if ecs_type:
            for t in WalletTemplate.query.filter_by(pass_type_id=ecs_type.id).all():
                ecs_templates.append({
                    'name': t.name,
                    'platform': t.platform,
                    'is_default': t.is_default
                })
        if pub_type:
            for t in WalletTemplate.query.filter_by(pass_type_id=pub_type.id).all():
                pub_templates.append({
                    'name': t.name,
                    'platform': t.platform,
                    'is_default': t.is_default
                })

        templates_data = {
            'ecs_templates': ecs_templates if ecs_templates else None,
            'pub_templates': pub_templates if pub_templates else None
        }

        database_checks = {
            'Pass Types': pass_types_data,
            'Certificates': certificates_data,
            'Assets': assets_data,
            'Templates': templates_data
        }

        diagnostics_data = {
            'config_status': config_status,
            'system_info': system_info,
            'directory_checks': directory_checks,
            'database_checks': database_checks
        }

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(diagnostics_data)
        else:
            return render_template('admin/wallet_config/diagnostics_flowbite.html', diagnostics=diagnostics_data)

    except Exception as e:
        logger.error(f"Error running wallet diagnostics: {str(e)}", exc_info=True)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': str(e)}), 500
        else:
            flash(f'Error running wallet diagnostics: {str(e)}', 'error')
            return redirect(url_for('wallet_config.dashboard'))


# =============================================================================
# INITIALIZATION
# =============================================================================

@wallet_config_bp.route('/init-pass-types', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def init_pass_types():
    """Initialize wallet pass types"""
    try:
        created = []

        # ECS Membership pass type
        ecs_type = WalletPassType.query.filter_by(code='ecs_membership').first()
        if not ecs_type:
            ecs_type = WalletPassType(
                code='ecs_membership',
                name='ECS Membership',
                description='Annual ECS FC membership card valid for one calendar year',
                template_name='ecs_membership',
                background_color='#1a472a',
                foreground_color='#ffffff',
                label_color='#c8c8c8',
                logo_text='ECS FC',
                validity_type='annual',
                validity_duration_days=365,
                grace_period_days=30,
                woo_product_patterns=json.dumps([
                    r'ECS\s+\d{4}\s+Membership',
                    r'ECS\s+Membership\s+\d{4}',
                    r'ECS\s+Membership\s+Card',
                    r'ECS\s+Membership\s+Package\s+\d{4}'
                ]),
                apple_pass_type_id='pass.com.weareecs.membership',
                google_issuer_id='3388000000022958274',
                google_class_id='ecs_membership',
                is_active=True,
                display_order=1
            )
            db.session.add(ecs_type)
            created.append('ECS Membership')

        # Pub League pass type
        pub_type = WalletPassType.query.filter_by(code='pub_league').first()
        if not pub_type:
            pub_type = WalletPassType(
                code='pub_league',
                name='Pub League',
                description='Seasonal Pub League membership card valid for one season',
                template_name='pub_league',
                background_color='#213e96',
                foreground_color='#ffffff',
                label_color='#c8c8c8',
                logo_text='ECS Pub League',
                validity_type='seasonal',
                validity_duration_days=182,
                grace_period_days=30,
                woo_product_patterns=json.dumps([
                    r'ECS\s+Pub\s+League',
                    r'Pub\s+League\s+(Spring|Fall|Summer|Winter)\s+\d{4}'
                ]),
                apple_pass_type_id='pass.com.weareecs.membership',
                google_issuer_id='3388000000022958274',
                google_class_id='pub_league',
                is_active=True,
                display_order=2
            )
            db.session.add(pub_type)
            created.append('Pub League')

        db.session.commit()

        if created:
            flash(f'Successfully created pass types: {", ".join(created)}', 'success')
        else:
            flash('Pass types already exist.', 'info')

        next_step = request.form.get('next_step', 'certificates')
        is_wizard = request.form.get('is_wizard', 'false') == 'true'

        if is_wizard:
            return redirect(url_for('wallet_config.setup_wizard', step=next_step))
        return redirect(url_for('wallet_config.dashboard'))

    except Exception as e:
        logger.error(f"Error initializing pass types: {str(e)}", exc_info=True)
        flash(f'Error initializing pass types: {str(e)}', 'error')
        return redirect(url_for('wallet_config.setup_wizard', step='certificates'))


@wallet_config_bp.route('/setup')
@login_required
@role_required(['Global Admin'])
def setup_wizard_legacy():
    """
    Legacy setup wizard route - redirects to new wizard

    Kept for backwards compatibility.
    """
    step = request.args.get('step', 'certificates')
    return redirect(url_for('wallet_config.setup_wizard', step=step))


@wallet_config_bp.route('/certificates/help')
@login_required
@role_required(['Global Admin'])
def certificates_help():
    """Help page for certificates"""
    return render_template('admin/wallet_config/certificates_help_flowbite.html')


@wallet_config_bp.route('/assets/serve/<int:asset_id>')
@login_required
def serve_asset(asset_id):
    """Legacy asset serving route - redirects to new route"""
    return redirect(url_for('wallet_config.get_asset', asset_id=asset_id))


@wallet_config_bp.route('/templates/create', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def create_template():
    """Create a new template manually"""
    try:
        pass_type_id = request.form.get('pass_type_id')
        name = request.form.get('name')
        platform = request.form.get('platform', 'apple')
        content = request.form.get('content', '{}')

        if not pass_type_id or not name:
            flash('Pass type and name are required.', 'error')
            return redirect(url_for('wallet_config.templates'))

        template = asset_service.upload_template(
            name=name,
            content=content,
            pass_type_id=int(pass_type_id),
            platform=platform,
            is_default=False
        )

        flash(f'Template "{name}" created successfully.', 'success')
        return redirect(url_for('wallet_config.templates'))

    except Exception as e:
        logger.error(f"Error creating template: {str(e)}", exc_info=True)
        flash(f'Error creating template: {str(e)}', 'error')
        return redirect(url_for('wallet_config.templates'))


@wallet_config_bp.route('/templates/<int:template_id>/default', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def set_default_template_legacy(template_id):
    """Legacy route for setting default template - redirects to new route"""
    return redirect(url_for('wallet_config.set_default_template', template_id=template_id), code=307)


@wallet_config_bp.route('/help')
@login_required
@role_required(['Global Admin'])
def help_page():
    """Help documentation page"""
    return render_template('admin/wallet_config/help_flowbite.html')


@wallet_config_bp.route('/download-woo-plugin')
@login_required
@role_required(['Global Admin'])
def download_woo_plugin():
    """Download the WooCommerce integration plugin as a ZIP file.

    WordPress requires plugins to be uploaded as ZIP files containing
    a folder with the plugin files inside.
    """
    import zipfile
    from io import BytesIO

    plugin_path = os.path.join(
        current_app.root_path,
        '..',
        'docs',
        'woocommerce',
        'ecs-wallet-pass-plugin.php'
    )

    if not os.path.exists(plugin_path):
        flash('Plugin file not found.', 'error')
        return redirect(url_for('wallet_config.setup_wizard', step='woocommerce'))

    # Create ZIP file in memory
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # WordPress expects plugin files inside a folder named after the plugin
        # The folder name should match the plugin slug
        zip_file.write(
            plugin_path,
            'ecs-wallet-pass/ecs-wallet-pass-plugin.php'
        )

    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        as_attachment=True,
        download_name='ecs-wallet-pass.zip',
        mimetype='application/zip'
    )
