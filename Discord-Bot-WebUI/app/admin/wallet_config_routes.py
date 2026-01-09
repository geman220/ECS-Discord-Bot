# app/admin/wallet_config_routes.py

"""
Wallet Configuration Admin Routes

DEPRECATED: This monolithic file has been refactored into modular components.
Please use the new package at app/admin/wallet/ instead.

The new structure is:
- app/admin/wallet/__init__.py - Blueprint definitions
- app/admin/wallet/config_routes.py - Core config routes
- app/admin/wallet/design_routes.py - Visual editor routes
- app/admin/wallet/location_routes.py - Location/subgroup routes
- app/admin/wallet/sponsor_routes.py - Sponsor routes
- app/admin/wallet/helpers.py - Shared utility functions

This file is kept for reference only and should not be imported directly.
The app/__init__.py has been updated to import from app.admin.wallet.

This module provides administrative routes for configuring the wallet pass system:
- Certificate management (upload, activation, deletion)
- Asset management (icons, logos, images)
- Template management and customization
- Configuration testing and diagnostics
- Interactive setup guides
"""

import os
import json
import logging
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, send_file, current_app, session
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.core import db
from app.models import Player, User, Team, Season
from app.models.wallet import (
    WalletPass, WalletPassType, WalletPassCheckin, PassStatus,
    create_ecs_membership_pass, create_pub_league_pass
)
from app.models.wallet_asset import WalletAsset, WalletTemplate, WalletCertificate
from app.decorators import role_required
from app.wallet_pass import validate_pass_configuration, create_pass_for_player
from app.wallet_pass.services.pass_service import pass_service
from app.services.asset_service import asset_service, ASSET_TYPES, CERT_TYPES
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

wallet_config_bp = Blueprint('wallet_config', __name__, url_prefix='/admin/wallet/config')

# Helper Functions
def get_config_status(include_detailed=False):
    """
    Get current configuration status and progress

    Each pass type (ECS Membership, Pub League) is tracked independently.
    A pass type is ready for pass generation when:
    - Certificates are configured (shared between both)
    - That specific pass type has all required assets
    - That specific pass type has a default template

    Returns:
        dict: Configuration status information with per-pass-type details
    """
    status = validate_pass_configuration()

    # Check certificates (Apple and/or Google) - shared between both pass types
    apple_cert_complete = WalletCertificate.has_complete_apple_config()
    google_cert_complete = WalletCertificate.has_complete_google_config()
    cert_complete = apple_cert_complete or google_cert_complete  # At least one platform

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
        ecs_assets_complete = all(any(a.asset_type == req for a in ecs_assets) for req in required_assets)
        ecs_template = WalletTemplate.get_default(ecs_type.id, 'apple')
        ecs_template_complete = ecs_template is not None
        # ECS is ready if certs + assets + template are all configured
        ecs_ready = cert_complete and ecs_assets_complete and ecs_template_complete

    # ===== Pub League Status =====
    pub_assets_complete = False
    pub_template_complete = False
    pub_ready = False
    pub_assets = []

    if pub_type:
        pub_assets = WalletAsset.get_assets_by_pass_type(pub_type.id)
        pub_assets_complete = all(any(a.asset_type == req for a in pub_assets) for req in required_assets)
        pub_template = WalletTemplate.get_default(pub_type.id, 'apple')
        pub_template_complete = pub_template is not None
        # Pub League is ready if certs + assets + template are all configured
        pub_ready = cert_complete and pub_assets_complete and pub_template_complete

    # ===== Overall Progress Calculation =====
    # Calculate overall progress - at least one pass type being ready means progress is made
    # Certificates count as 1 step, then each pass type (assets + templates) counts toward completion
    total_steps = 3  # Certificates + Assets + Templates
    completed_steps = 0

    if cert_complete:
        completed_steps += 1

    # Assets: complete if at least one pass type has all required assets
    assets_complete = ecs_assets_complete or pub_assets_complete
    if assets_complete:
        completed_steps += 1

    # Templates: complete if at least one pass type has a default template
    templates_complete = ecs_template_complete or pub_template_complete
    if templates_complete:
        completed_steps += 1

    # Testing is complete if at least one pass type is fully ready
    testing_complete = ecs_ready or pub_ready

    # WooCommerce is optional
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
        # Per-pass-type status
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
        # Pass types
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

        # Certificates
        apple_certs = {c.type: c.to_dict() for c in WalletCertificate.query.filter_by(platform='apple', is_active=True).all()}
        google_certs = {c.type: c.to_dict() for c in WalletCertificate.query.filter_by(platform='google', is_active=True).all()}
        details['certificates'] = {
            'apple': apple_certs,
            'google': google_certs,
            'apple_complete': apple_cert_complete,
            'google_complete': google_cert_complete
        }

        # Assets - always include even if pass types don't exist (just empty dicts)
        ecs_assets_dict = {a.asset_type: a.to_dict() for a in ecs_assets} if ecs_type else {}
        pub_assets_dict = {a.asset_type: a.to_dict() for a in pub_assets} if pub_type else {}
        details['assets'] = {
            'ecs': ecs_assets_dict,
            'pub': pub_assets_dict
        }

    return {
        'status': status,
        'progress': progress,
        'details': details
    }


@wallet_config_bp.route('/')
@login_required
@role_required(['Global Admin'])
def dashboard():
    """
    Main wallet configuration dashboard
    
    Shows configuration status, setup progress, and quick actions
    """
    try:
        config_info = get_config_status(include_detailed=True)
        status = config_info['status']
        progress = config_info['progress']
        details = config_info['details']
        
        # Get pass types
        ecs_type = WalletPassType.get_ecs_membership()
        pub_type = WalletPassType.get_pub_league()
        
        # Get recent passes for preview
        recent_passes = WalletPass.query.order_by(WalletPass.created_at.desc()).limit(5).all()
        
        # Get pass statistics
        stats = pass_service.get_statistics()
        
        return render_template(
            'admin/wallet_config/dashboard_flowbite.html',
            status=status,
            progress=progress,
            details=details,
            ecs_type=ecs_type,
            pub_type=pub_type,
            recent_passes=recent_passes,
            stats=stats,
            asset_types=ASSET_TYPES,
            cert_types=CERT_TYPES
        )
    except Exception as e:
        logger.error(f"Error loading wallet config dashboard: {str(e)}", exc_info=True)
        flash('Error loading wallet configuration dashboard.', 'error')
        return redirect(url_for('wallet_admin.wallet_config'))


@wallet_config_bp.route('/setup')
@login_required
@role_required(['Global Admin'])
def setup_wizard():
    """
    Interactive setup wizard for wallet configuration
    
    Guides admin through the entire configuration process step by step
    """
    try:
        # Get current configuration status
        config_info = get_config_status()
        
        # Determine which step to show
        current_step = request.args.get('step', 'certificates')
        
        # Get pass types
        ecs_type = WalletPassType.get_ecs_membership()
        pub_type = WalletPassType.get_pub_league()
        
        # Get step-specific data
        step_data = {}
        
        if current_step == 'certificates':
            # Get existing certificates
            apple_certs = {c.type: c for c in WalletCertificate.query.filter_by(platform='apple').all()}
            google_certs = {c.type: c for c in WalletCertificate.query.filter_by(platform='google').all()}
            
            step_data = {
                'apple_certs': apple_certs,
                'google_certs': google_certs,
                'cert_types': CERT_TYPES
            }
        
        elif current_step == 'assets':
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
        
        elif current_step == 'templates':
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
        
        elif current_step == 'testing':
            # Get test results if available
            test_results = session.get('wallet_test_results', None)

            step_data = {
                'test_results': test_results
            }

        elif current_step == 'woocommerce':
            # WooCommerce integration step
            webhook_secret = os.getenv('WALLET_WEBHOOK_SECRET', '')

            step_data = {
                'webhook_configured': bool(webhook_secret),
                'webhook_secret': webhook_secret if webhook_secret else None,
                'last_webhook_time': None  # Could track this in DB if needed
            }

        return render_template(
            'admin/wallet_config/wizard_flowbite.html',
            wallet_config=config_info,
            current_step=current_step,
            ecs_type=ecs_type,
            pub_type=pub_type,
            step_data=step_data
        )
    
    except Exception as e:
        logger.error(f"Error loading wallet setup wizard: {str(e)}", exc_info=True)
        flash('Error loading setup wizard.', 'error')
        return redirect(url_for('wallet_admin.wallet_config'))


@wallet_config_bp.route('/certificates')
@login_required
@role_required(['Global Admin'])
def certificates():
    """
    Certificate management page
    
    Shows uploaded certificates and allows managing them
    """
    try:
        # Get existing certificates
        apple_certs = WalletCertificate.query.filter_by(platform='apple').all()
        google_certs = WalletCertificate.query.filter_by(platform='google').all()
        
        # Get certificate types for upload form
        return render_template(
            'admin/wallet_config/certificates_flowbite.html',
            apple_certs=apple_certs,
            google_certs=google_certs,
            cert_types=CERT_TYPES,
            has_complete_apple=WalletCertificate.has_complete_apple_config(),
            has_complete_google=WalletCertificate.has_complete_google_config()
        )
    
    except Exception as e:
        logger.error(f"Error loading certificate management page: {str(e)}", exc_info=True)
        flash('Error loading certificate management page.', 'error')
        return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/certificates/upload', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def upload_certificate():
    """
    Handle certificate upload

    Uploads a certificate file and creates/updates database record
    """
    is_wizard = request.form.get('is_wizard', 'false') == 'true'

    def redirect_back(step='certificates'):
        """Helper to redirect back to appropriate page"""
        if is_wizard:
            return redirect(url_for('wallet_config.setup_wizard', step=step))
        return redirect(url_for('wallet_config.certificates'))

    try:
        # Get form data
        platform = request.form.get('platform', 'apple')
        cert_type = request.form.get('cert_type')
        name = request.form.get('name')
        team_identifier = request.form.get('team_identifier')
        pass_type_identifier = request.form.get('pass_type_identifier')
        issuer_id = request.form.get('issuer_id')

        logger.info(f"Certificate upload request: platform={platform}, type={cert_type}, name={name}")

        # Validate required fields
        if not cert_type or not name:
            flash('Certificate type and name are required.', 'error')
            return redirect_back()

        # Check if file was provided
        if 'certificate_file' not in request.files:
            flash('No certificate file provided.', 'error')
            return redirect_back()

        file = request.files['certificate_file']
        if file.filename == '':
            flash('No certificate file selected.', 'error')
            return redirect_back()

        logger.info(f"Uploading certificate file: {file.filename}")

        # Upload certificate using asset service
        certificate = asset_service.upload_certificate(
            file=file,
            cert_type=cert_type,
            platform=platform,
            name=name,
            team_identifier=team_identifier,
            pass_type_identifier=pass_type_identifier,
            issuer_id=issuer_id
        )

        logger.info(f"Certificate uploaded successfully: id={certificate.id}")
        flash(f'Certificate "{name}" uploaded successfully.', 'success')

        # Redirect back to certificate management or setup wizard
        if is_wizard:
            # If all certs are uploaded, proceed to next step
            if WalletCertificate.has_complete_apple_config():
                return redirect(url_for('wallet_config.setup_wizard', step='assets'))
            return redirect(url_for('wallet_config.setup_wizard', step='certificates'))

        return redirect(url_for('wallet_config.certificates'))

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
    """
    Toggle certificate active status
    
    Activates or deactivates a certificate (and deactivates other certs of same type)
    """
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
    """
    Delete a certificate
    
    Removes the certificate file and database record
    """
    try:
        asset_service.delete_certificate(cert_id)
        flash('Certificate deleted successfully.', 'success')
        return redirect(url_for('wallet_config.certificates'))
    
    except Exception as e:
        logger.error(f"Error deleting certificate {cert_id}: {str(e)}", exc_info=True)
        flash(f'Error deleting certificate: {str(e)}', 'error')
        return redirect(url_for('wallet_config.certificates'))


@wallet_config_bp.route('/certificates/help')
@login_required
@role_required(['Global Admin'])
def certificate_help():
    """
    Certificate setup help page
    
    Provides detailed instructions for obtaining and setting up certificates
    """
    return render_template('admin/wallet_config/certificate_help_flowbite.html')


@wallet_config_bp.route('/assets')
@login_required
@role_required(['Global Admin'])
def assets():
    """
    Asset management page

    Shows uploaded assets and allows managing them
    """
    try:
        # Get pass types
        ecs_type = WalletPassType.get_ecs_membership()
        pub_type = WalletPassType.get_pub_league()

        # Check if pass types exist
        pass_types_missing = not ecs_type or not pub_type

        # Get existing assets only if pass types exist
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
    """
    Handle asset upload
    
    Uploads an asset file and creates/updates database record
    """
    # Check if request came from wizard
    is_wizard = request.form.get('is_wizard', 'false') == 'true'
    redirect_url = url_for('wallet_config.setup_wizard', step='assets') if is_wizard else url_for('wallet_config.assets')

    try:
        # Get form data
        pass_type_id = request.form.get('pass_type_id')
        asset_type = request.form.get('asset_type')

        # Validate required fields
        if not pass_type_id or not asset_type:
            flash('Pass type and asset type are required.', 'error')
            return redirect(redirect_url)

        # Check if file was provided
        if 'asset_file' not in request.files:
            flash('No asset file provided.', 'error')
            return redirect(redirect_url)

        file = request.files['asset_file']
        if file.filename == '':
            flash('No asset file selected.', 'error')
            return redirect(redirect_url)

        # Upload asset using asset service
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
    """
    Delete an asset

    Removes the asset file and database record
    """
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


@wallet_config_bp.route('/assets/serve/<int:asset_id>')
@login_required
def get_asset(asset_id):
    """
    Serve an asset file

    Returns the asset file for display in templates
    """
    try:
        asset = WalletAsset.query.get_or_404(asset_id)
        file_path = asset.file_path

        # Log the current working directory and stored path for debugging
        cwd = os.getcwd()
        logger.info(f"Serving asset {asset_id}: stored_path='{file_path}', cwd='{cwd}'")

        # Build list of paths to try
        paths_to_try = [file_path]

        # Normalize the path - remove duplicate 'app/' prefixes
        normalized = file_path
        while 'app/app/' in normalized:
            normalized = normalized.replace('app/app/', 'app/', 1)
        if normalized != file_path:
            paths_to_try.append(normalized)

        # If path starts with 'app/', try without it (since CWD is /app)
        if file_path.startswith('app/'):
            paths_to_try.append(file_path[4:])  # Strip 'app/' prefix

        # Also try stripping multiple app/ prefixes for legacy records
        stripped = file_path
        while stripped.startswith('app/'):
            stripped = stripped[4:]
            paths_to_try.append(stripped)

        # If absolute path, try making it relative
        if file_path.startswith('/'):
            # Try stripping /app/ prefix
            if file_path.startswith('/app/'):
                paths_to_try.append(file_path[5:])
            # Try stripping /app/app/ prefix
            if file_path.startswith('/app/app/'):
                paths_to_try.append(file_path[9:])

        # Try each path
        for try_path in paths_to_try:
            # Check if file exists (relative to CWD)
            logger.info(f"Trying path: {try_path}, exists: {os.path.exists(try_path)}")
            if os.path.exists(try_path):
                # Convert to absolute path for send_file
                # (send_file resolves relative paths from app.root_path, not CWD)
                absolute_path = os.path.abspath(try_path)
                logger.info(f"Serving file from absolute path: {absolute_path}")
                return send_file(
                    absolute_path,
                    mimetype=asset.content_type or 'application/octet-stream',
                    as_attachment=False
                )

        # None worked - return detailed error
        logger.error(f"Asset file not found. Tried paths: {paths_to_try}")
        return f"Asset not found. Stored path: {file_path}", 404

    except Exception as e:
        logger.error(f"Error serving asset {asset_id}: {str(e)}", exc_info=True)
        return f"Error serving asset: {str(e)}", 500


@wallet_config_bp.route('/templates')
@login_required
@role_required(['Global Admin'])
def templates():
    """
    Template management page

    Shows existing templates and allows customization
    """
    try:
        # Get pass types
        ecs_type = WalletPassType.get_ecs_membership()
        pub_type = WalletPassType.get_pub_league()

        # Check if pass types exist
        pass_types_missing = not ecs_type or not pub_type

        # Get existing templates only if pass types exist
        if pass_types_missing:
            ecs_templates = []
            pub_templates = []
            ecs_default_apple = None
            pub_default_apple = None
        else:
            ecs_templates = WalletTemplate.query.filter_by(pass_type_id=ecs_type.id).all()
            pub_templates = WalletTemplate.query.filter_by(pass_type_id=pub_type.id).all()
            ecs_default_apple = WalletTemplate.get_default(ecs_type.id, 'apple')
            pub_default_apple = WalletTemplate.get_default(pub_type.id, 'apple')

        return render_template(
            'admin/wallet_config/templates_flowbite.html',
            ecs_type=ecs_type,
            pub_type=pub_type,
            ecs_templates=ecs_templates,
            pub_templates=pub_templates,
            ecs_default_apple=ecs_default_apple,
            pub_default_apple=pub_default_apple,
            pass_types_missing=pass_types_missing
        )

    except Exception as e:
        logger.error(f"Error loading template management page: {str(e)}", exc_info=True)
        flash('Error loading template management page.', 'error')
        return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/templates/create', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def create_template():
    """
    Create or update a template
    
    Creates a new template or updates an existing one
    """
    try:
        # Get form data
        pass_type_id = request.form.get('pass_type_id')
        name = request.form.get('name')
        platform = request.form.get('platform', 'apple')
        content = request.form.get('content')
        is_default = request.form.get('is_default', 'false') == 'true'
        
        # Validate required fields
        if not pass_type_id or not name or not content:
            flash('Pass type, name and content are required.', 'error')
            return redirect(url_for('wallet_config.templates'))
        
        # Create or update template
        template = asset_service.upload_template(
            name=name,
            content=content,
            pass_type_id=int(pass_type_id),
            platform=platform,
            is_default=is_default
        )
        
        flash(f'Template "{name}" saved successfully.', 'success')
        
        # Redirect back to template management or setup wizard
        if request.form.get('is_wizard', 'false') == 'true':
            return redirect(url_for('wallet_config.setup_wizard', step='templates'))
        
        return redirect(url_for('wallet_config.templates'))
    
    except Exception as e:
        logger.error(f"Error creating/updating template: {str(e)}", exc_info=True)
        flash(f'Error saving template: {str(e)}', 'error')
        return redirect(url_for('wallet_config.templates'))


@wallet_config_bp.route('/templates/<int:template_id>/default', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def set_default_template(template_id):
    """
    Set a template as default
    
    Makes a template the default for its pass type and platform
    """
    try:
        template = asset_service.set_default_template(template_id)
        flash(f'Template "{template.name}" set as default.', 'success')
        return redirect(url_for('wallet_config.templates'))
    
    except Exception as e:
        logger.error(f"Error setting default template {template_id}: {str(e)}", exc_info=True)
        flash(f'Error setting default template: {str(e)}', 'error')
        return redirect(url_for('wallet_config.templates'))


@wallet_config_bp.route('/templates/<int:template_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def delete_template(template_id):
    """
    Delete a template
    
    Removes a template from the system
    """
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
    """
    Generate a default template
    
    Creates a default template based on pass type configuration
    """
    try:
        pass_type_id = request.form.get('pass_type_id')
        platform = request.form.get('platform', 'apple')
        
        if not pass_type_id:
            flash('Pass type is required.', 'error')
            return redirect(url_for('wallet_config.templates'))
        
        pass_type = WalletPassType.query.get_or_404(pass_type_id)
        
        # Generate default template content based on pass type
        if platform == 'apple':
            # Basic Apple Wallet template structure
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
                        {
                            "key": "member",
                            "label": "MEMBER",
                            "value": "{{member_name}}"
                        }
                    ],
                    "secondaryFields": [
                        {
                            "key": "validity",
                            "label": "VALID FOR",
                            "value": "{{validity}}"
                        }
                    ],
                    "auxiliaryFields": [
                        {
                            "key": "team",
                            "label": "TEAM",
                            "value": "{{team_name}}"
                        }
                    ],
                    "backFields": [
                        {
                            "key": "terms",
                            "label": "TERMS & CONDITIONS",
                            "value": "This pass identifies the holder as a member of the Emerald City Supporters. Membership is non-transferable."
                        },
                        {
                            "key": "website",
                            "label": "WEBSITE",
                            "value": "https://www.weareecs.com"
                        }
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
            
            # Create template
            template = asset_service.upload_template(
                name=f"Default {pass_type.name} Template",
                content=json.dumps(template_content, indent=2),
                pass_type_id=int(pass_type_id),
                platform=platform,
                is_default=True
            )
            
            flash(f'Default {platform} template generated for {pass_type.name}.', 'success')
            
            # Redirect back to template management or setup wizard
            if request.form.get('is_wizard', 'false') == 'true':
                return redirect(url_for('wallet_config.setup_wizard', step='templates'))
            
            return redirect(url_for('wallet_config.templates'))
        
        else:
            # Google Wallet not yet implemented
            flash('Google Wallet templates not yet supported.', 'warning')
            return redirect(url_for('wallet_config.templates'))
    
    except Exception as e:
        logger.error(f"Error generating default template: {str(e)}", exc_info=True)
        flash(f'Error generating template: {str(e)}', 'error')
        return redirect(url_for('wallet_config.templates'))


@wallet_config_bp.route('/test')
@login_required
@role_required(['Global Admin'])
def test_config():
    """
    Test wallet configuration
    
    Runs comprehensive tests on the wallet configuration
    """
    try:
        # Get configuration status
        config_status = validate_pass_configuration()
        
        # Run additional tests
        test_results = {
            'configuration': config_status,
            'tests': []
        }
        
        # Test Apple certificate configuration
        try:
            apple_cert_complete = WalletCertificate.has_complete_apple_config()
            apple_cert_message = "All required Apple certificates are present" if apple_cert_complete else "Missing required Apple certificates"
            test_results['tests'].append({
                'name': 'Apple Wallet Certificates',
                'status': 'passed' if apple_cert_complete else 'warning',
                'message': apple_cert_message
            })
        except Exception as e:
            test_results['tests'].append({
                'name': 'Apple Wallet Certificates',
                'status': 'failed',
                'message': f'Error testing Apple certificates: {str(e)}'
            })

        # Test Google certificate configuration
        try:
            google_cert_complete = WalletCertificate.has_complete_google_config()
            google_cert_message = "Google Wallet credentials are present" if google_cert_complete else "Google Wallet credentials not configured (optional)"
            test_results['tests'].append({
                'name': 'Google Wallet Credentials',
                'status': 'passed' if google_cert_complete else 'info',
                'message': google_cert_message
            })
        except Exception as e:
            test_results['tests'].append({
                'name': 'Google Wallet Credentials',
                'status': 'failed',
                'message': f'Error testing Google credentials: {str(e)}'
            })
        
        # Test asset configuration
        try:
            ecs_type = WalletPassType.get_ecs_membership()
            pub_type = WalletPassType.get_pub_league()
            
            assets_complete = False
            assets_message = "Could not check assets - pass types not configured"
            
            if ecs_type and pub_type:
                # Check essential assets
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
        
        # Test template configuration
        try:
            templates_complete = False
            template_message = "Could not check templates - pass types not configured"
            
            if ecs_type and pub_type:
                ecs_template = WalletTemplate.get_default(ecs_type.id, 'apple')
                pub_template = WalletTemplate.get_default(pub_type.id, 'apple')
                
                if ecs_template and pub_template:
                    templates_complete = True
                    template_message = "Default templates are configured"
                else:
                    missing = []
                    if not ecs_template:
                        missing.append("ECS Membership")
                    if not pub_template:
                        missing.append("Pub League")
                    template_message = f"Missing default templates for: {', '.join(missing)}"
            
            test_results['tests'].append({
                'name': 'Template Configuration',
                'status': 'passed' if templates_complete else 'failed',
                'message': template_message
            })
        except Exception as e:
            test_results['tests'].append({
                'name': 'Template Configuration',
                'status': 'failed',
                'message': f'Error testing templates: {str(e)}'
            })
        
        # Test sample pass generation
        try:
            # Only try to generate a sample pass if configuration is complete
            if config_status.get('configured', False):
                test_member = "Test Member"
                test_email = "test@example.com"
                test_year = datetime.now().year
                
                # Create a test pass but don't save to database
                test_pass = create_ecs_membership_pass(
                    member_name=test_member,
                    member_email=test_email,
                    year=test_year
                )
                
                # Check if pass properties are set correctly
                if (test_pass and test_pass.member_name == test_member and 
                    test_pass.member_email == test_email and 
                    test_pass.membership_year == test_year):
                    test_results['tests'].append({
                        'name': 'Pass Generation',
                        'status': 'passed',
                        'message': f"Successfully generated test pass for {test_member}"
                    })
                else:
                    test_results['tests'].append({
                        'name': 'Pass Generation',
                        'status': 'failed',
                        'message': "Test pass generation failed - pass properties incorrect"
                    })
            else:
                test_results['tests'].append({
                    'name': 'Pass Generation',
                    'status': 'skipped',
                    'message': "Cannot test pass generation until configuration is complete"
                })
        except Exception as e:
            test_results['tests'].append({
                'name': 'Pass Generation',
                'status': 'failed',
                'message': f'Error generating test pass: {str(e)}'
            })
        
        # Store test results in session for wizard
        session['wallet_test_results'] = test_results
        
        # Return results
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(test_results)
        else:
            return render_template(
                'admin/wallet_config/test_results_flowbite.html',
                test_results=test_results
            )
    
    except Exception as e:
        logger.error(f"Error testing wallet configuration: {str(e)}", exc_info=True)
        error_message = {'error': str(e)}
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(error_message), 500
        else:
            flash(f'Error testing wallet configuration: {str(e)}', 'error')
            return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/diagnostics')
@login_required
@role_required(['Global Admin'])
def diagnostics():
    """
    Run diagnostics on the wallet configuration
    
    Returns detailed diagnostic information for troubleshooting
    """
    try:
        # Get configuration status
        config_status = validate_pass_configuration()
        
        # Get system information
        system_info = {
            'app_path': current_app.root_path,
            'asset_path': asset_service.asset_path,
            'cert_path': asset_service.cert_path,
            'template_path': asset_service.template_path,
            'pass_type_id': current_app.config.get('WALLET_PASS_TYPE_ID'),
            'team_id': current_app.config.get('WALLET_TEAM_ID'),
        }
        
        # Check directory permissions
        directory_checks = {}
        for name, path in [
            ('Asset Directory', asset_service.asset_path), 
            ('Certificate Directory', asset_service.cert_path),
            ('Template Directory', asset_service.template_path)
        ]:
            try:
                exists = os.path.exists(path)
                writable = os.access(path, os.W_OK) if exists else False
                directory_checks[name] = {
                    'path': path,
                    'exists': exists,
                    'writable': writable,
                    'status': 'OK' if exists and writable else 'ERROR'
                }
            except Exception as e:
                directory_checks[name] = {
                    'path': path,
                    'error': str(e),
                    'status': 'ERROR'
                }
        
        # Check database configuration
        database_checks = {}
        try:
            # Check pass types
            ecs_type = WalletPassType.get_ecs_membership()
            pub_type = WalletPassType.get_pub_league()
            
            database_checks['Pass Types'] = {
                'ecs_type': {
                    'exists': ecs_type is not None,
                    'details': ecs_type.to_dict() if ecs_type else None
                },
                'pub_type': {
                    'exists': pub_type is not None,
                    'details': pub_type.to_dict() if pub_type else None
                }
            }
            
            # Check certificates
            apple_certs = {c.type: c.to_dict() for c in WalletCertificate.query.filter_by(platform='apple').all()}
            database_checks['Certificates'] = {
                'apple': apple_certs,
                'complete': WalletCertificate.has_complete_apple_config()
            }
            
            # Check assets (if pass types exist)
            if ecs_type and pub_type:
                ecs_assets = {a.asset_type: a.to_dict() for a in WalletAsset.get_assets_by_pass_type(ecs_type.id)}
                pub_assets = {a.asset_type: a.to_dict() for a in WalletAsset.get_assets_by_pass_type(pub_type.id)}
                
                database_checks['Assets'] = {
                    'ecs_assets': ecs_assets,
                    'pub_assets': pub_assets
                }
            
            # Check templates (if pass types exist)
            if ecs_type and pub_type:
                ecs_templates = [t.to_dict() for t in WalletTemplate.query.filter_by(pass_type_id=ecs_type.id).all()]
                pub_templates = [t.to_dict() for t in WalletTemplate.query.filter_by(pass_type_id=pub_type.id).all()]
                
                database_checks['Templates'] = {
                    'ecs_templates': ecs_templates,
                    'pub_templates': pub_templates
                }
        
        except Exception as e:
            database_checks['Error'] = str(e)
        
        # Return diagnostic results
        diagnostics = {
            'config_status': config_status,
            'system_info': system_info,
            'directory_checks': directory_checks,
            'database_checks': database_checks
        }
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(diagnostics)
        else:
            return render_template(
                'admin/wallet_config/diagnostics_flowbite.html',
                diagnostics=diagnostics
            )
    
    except Exception as e:
        logger.error(f"Error running wallet diagnostics: {str(e)}", exc_info=True)
        error_message = {'error': str(e)}
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(error_message), 500
        else:
            flash(f'Error running wallet diagnostics: {str(e)}', 'error')
            return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/init-pass-types', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def init_pass_types():
    """
    Initialize wallet pass types via the UI

    Creates the ECS Membership and Pub League pass types if they don't exist.
    This replaces the need for the CLI command `flask wallet init_types`.
    """
    import json

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
            logger.info('Created ECS Membership pass type')

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
                validity_duration_days=182,  # ~6 months (half year)
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
            logger.info('Created Pub League pass type')

        db.session.commit()

        if created:
            flash(f'Successfully created pass types: {", ".join(created)}', 'success')
        else:
            flash('Pass types already exist.', 'info')

        # Redirect back to wherever they came from
        next_step = request.form.get('next_step', 'certificates')
        is_wizard = request.form.get('is_wizard', 'false') == 'true'

        if is_wizard:
            return redirect(url_for('wallet_config.setup_wizard', step=next_step))
        return redirect(url_for('wallet_config.dashboard'))

    except Exception as e:
        logger.error(f"Error initializing pass types: {str(e)}", exc_info=True)
        flash(f'Error initializing pass types: {str(e)}', 'error')
        return redirect(url_for('wallet_config.setup_wizard', step='certificates'))


@wallet_config_bp.route('/help')
@login_required
@role_required(['Global Admin'])
def help_page():
    """
    Help documentation page

    Provides comprehensive help on wallet pass configuration
    """
    return render_template('admin/wallet_config/help_flowbite.html')


@wallet_config_bp.route('/download-woo-plugin')
@login_required
@role_required(['Global Admin'])
def download_woo_plugin():
    """
    Download the WooCommerce integration plugin file

    Returns the PHP plugin file for WordPress installation
    """
    import os
    from flask import send_file, current_app

    # Path to the plugin file
    plugin_path = os.path.join(
        current_app.root_path,
        '..',
        'docs',
        'woocommerce',
        'ecs-wallet-pass-plugin.php'
    )

    if os.path.exists(plugin_path):
        return send_file(
            plugin_path,
            as_attachment=True,
            download_name='ecs-wallet-pass-plugin.php',
            mimetype='application/x-php'
        )
    else:
        flash('Plugin file not found.', 'error')
        return redirect(url_for('wallet_config.setup_wizard', step='woocommerce'))


@wallet_config_bp.route('/editor/<pass_type>')
@login_required
@role_required(['Global Admin'])
def visual_editor(pass_type):
    """
    Visual pass editor
    
    Provides a visual editor for customizing pass appearance
    """
    try:
        # Get pass type
        if pass_type == 'ecs':
            pass_obj = WalletPassType.get_ecs_membership()
            if not pass_obj:
                flash('ECS Membership pass type not found.', 'error')
                return redirect(url_for('wallet_config.templates'))
        elif pass_type == 'pub':
            pass_obj = WalletPassType.get_pub_league()
            if not pass_obj:
                flash('Pub League pass type not found.', 'error')
                return redirect(url_for('wallet_config.templates'))
        else:
            flash('Invalid pass type.', 'error')
            return redirect(url_for('wallet_config.templates'))
        
        # Get existing template
        template = WalletTemplate.get_default(pass_obj.id, 'apple')
        template_content = json.loads(template.content) if template else None
        
        # Get assets
        assets = WalletAsset.get_assets_by_pass_type(pass_obj.id)
        assets_dict = {a.asset_type: a for a in assets}
        
        return render_template(
            'admin/wallet_config/visual_editor_flowbite.html',
            pass_type=pass_obj,
            template=template,
            template_content=template_content,
            assets=assets_dict
        )
    
    except Exception as e:
        logger.error(f"Error loading visual editor: {str(e)}", exc_info=True)
        flash(f'Error loading visual editor: {str(e)}', 'error')
        return redirect(url_for('wallet_config.templates'))


@wallet_config_bp.route('/editor/save', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def save_visual_editor():
    """
    Save changes from visual editor
    
    Updates pass type and template with customized settings
    """
    try:
        # Get form data
        pass_type_id = request.form.get('pass_type_id')
        background_color = request.form.get('background_color')
        foreground_color = request.form.get('foreground_color')
        label_color = request.form.get('label_color')
        logo_text = request.form.get('logo_text')
        template_content = request.form.get('template_content')
        
        # Update pass type
        pass_type = WalletPassType.query.get_or_404(pass_type_id)
        
        if background_color:
            pass_type.background_color = background_color
        if foreground_color:
            pass_type.foreground_color = foreground_color
        if label_color:
            pass_type.label_color = label_color
        if logo_text:
            pass_type.logo_text = logo_text
        
        db.session.commit()
        
        # Update or create template if content provided
        if template_content:
            # Get existing default template
            template = WalletTemplate.get_default(pass_type_id, 'apple')
            
            if template:
                # Update existing template
                template.content = template_content
                db.session.commit()
            else:
                # Create new template
                template = WalletTemplate(
                    pass_type_id=int(pass_type_id),
                    platform='apple',
                    name=f"Default {pass_type.name} Template",
                    content=template_content,
                    is_default=True
                )
                db.session.add(template)
                db.session.commit()
        
        flash(f'{pass_type.name} appearance updated successfully.', 'success')

        # Send push updates to all devices with this pass type
        try:
            push_result = pass_service.update_pass_type_design(pass_type.id)
            if push_result.get('push_results'):
                total = push_result['push_results'].get('total_passes', 0)
                if total > 0:
                    flash(f'Push updates sent to {total} existing passes.', 'info')
        except Exception as push_error:
            logger.warning(f"Failed to send push updates: {push_error}")

        return redirect(url_for('wallet_config.templates'))

    except Exception as e:
        logger.error(f"Error saving visual editor changes: {str(e)}", exc_info=True)
        flash(f'Error saving changes: {str(e)}', 'error')
        return redirect(url_for('wallet_config.templates'))


# =============================================================================
# LOCATIONS MANAGEMENT
# =============================================================================

@wallet_config_bp.route('/locations')
@login_required
@role_required(['Global Admin'])
def locations():
    """
    Location management page

    Manage partner venues that trigger location-based notifications.
    Apple Wallet allows up to 10 locations per pass.
    """
    from app.models.wallet_config import WalletLocation

    try:
        all_locations = WalletLocation.query.order_by(
            WalletLocation.display_order, WalletLocation.name
        ).all()

        return render_template(
            'admin/wallet_config/locations_flowbite.html',
            locations=all_locations
        )

    except Exception as e:
        logger.error(f"Error loading locations page: {str(e)}", exc_info=True)
        flash('Error loading locations page.', 'error')
        return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/locations/add', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def add_location():
    """Add a new partner location"""
    from app.models.wallet_config import WalletLocation

    try:
        location = WalletLocation(
            name=request.form.get('name'),
            latitude=float(request.form.get('latitude')),
            longitude=float(request.form.get('longitude')),
            relevant_text=request.form.get('relevant_text') or request.form.get('name'),
            address=request.form.get('address'),
            city=request.form.get('city'),
            state=request.form.get('state'),
            applies_to=request.form.get('applies_to', 'all'),
            location_type=request.form.get('location_type', 'partner_bar'),
            is_active=request.form.get('is_active') == 'on'
        )
        db.session.add(location)
        db.session.commit()

        flash(f'Location "{location.name}" added successfully.', 'success')
        return redirect(url_for('wallet_config.locations'))

    except Exception as e:
        logger.error(f"Error adding location: {str(e)}", exc_info=True)
        flash(f'Error adding location: {str(e)}', 'error')
        return redirect(url_for('wallet_config.locations'))


@wallet_config_bp.route('/locations/<int:location_id>/edit', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def edit_location(location_id):
    """Edit an existing location"""
    from app.models.wallet_config import WalletLocation

    try:
        location = WalletLocation.query.get_or_404(location_id)

        location.name = request.form.get('name', location.name)
        location.latitude = float(request.form.get('latitude', location.latitude))
        location.longitude = float(request.form.get('longitude', location.longitude))
        location.relevant_text = request.form.get('relevant_text', location.relevant_text)
        location.address = request.form.get('address')
        location.city = request.form.get('city')
        location.state = request.form.get('state')
        location.applies_to = request.form.get('applies_to', 'all')
        location.location_type = request.form.get('location_type', 'partner_bar')
        location.is_active = request.form.get('is_active') == 'on'

        db.session.commit()

        flash(f'Location "{location.name}" updated successfully.', 'success')
        return redirect(url_for('wallet_config.locations'))

    except Exception as e:
        logger.error(f"Error updating location: {str(e)}", exc_info=True)
        flash(f'Error updating location: {str(e)}', 'error')
        return redirect(url_for('wallet_config.locations'))


@wallet_config_bp.route('/locations/<int:location_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def delete_location(location_id):
    """Delete a location"""
    from app.models.wallet_config import WalletLocation

    try:
        location = WalletLocation.query.get_or_404(location_id)
        name = location.name
        db.session.delete(location)
        db.session.commit()

        flash(f'Location "{name}" deleted successfully.', 'success')
        return redirect(url_for('wallet_config.locations'))

    except Exception as e:
        logger.error(f"Error deleting location: {str(e)}", exc_info=True)
        flash(f'Error deleting location: {str(e)}', 'error')
        return redirect(url_for('wallet_config.locations'))


@wallet_config_bp.route('/locations/<int:location_id>/toggle', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def toggle_location(location_id):
    """Toggle location active status"""
    from app.models.wallet_config import WalletLocation

    try:
        location = WalletLocation.query.get_or_404(location_id)
        location.is_active = not location.is_active
        db.session.commit()

        status = 'activated' if location.is_active else 'deactivated'
        flash(f'Location "{location.name}" {status}.', 'success')
        return redirect(url_for('wallet_config.locations'))

    except Exception as e:
        logger.error(f"Error toggling location: {str(e)}", exc_info=True)
        flash(f'Error toggling location: {str(e)}', 'error')
        return redirect(url_for('wallet_config.locations'))


# =============================================================================
# SPONSORS MANAGEMENT
# =============================================================================

@wallet_config_bp.route('/sponsors')
@login_required
@role_required(['Global Admin'])
def sponsors():
    """Sponsor management page"""
    from app.models.wallet_config import WalletSponsor

    try:
        all_sponsors = WalletSponsor.query.order_by(
            WalletSponsor.display_order, WalletSponsor.name
        ).all()

        return render_template(
            'admin/wallet_config/sponsors_flowbite.html',
            sponsors=all_sponsors
        )

    except Exception as e:
        logger.error(f"Error loading sponsors page: {str(e)}", exc_info=True)
        flash('Error loading sponsors page.', 'error')
        return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/sponsors/add', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def add_sponsor():
    """Add a new sponsor"""
    from app.models.wallet_config import WalletSponsor

    try:
        sponsor = WalletSponsor(
            name=request.form.get('name'),
            display_name=request.form.get('display_name') or request.form.get('name'),
            description=request.form.get('description'),
            website_url=request.form.get('website_url'),
            applies_to=request.form.get('applies_to', 'all'),
            display_location=request.form.get('display_location', 'back'),
            sponsor_type=request.form.get('sponsor_type', 'partner'),
            is_active=request.form.get('is_active') == 'on'
        )
        db.session.add(sponsor)
        db.session.commit()

        flash(f'Sponsor "{sponsor.name}" added successfully.', 'success')
        return redirect(url_for('wallet_config.sponsors'))

    except Exception as e:
        logger.error(f"Error adding sponsor: {str(e)}", exc_info=True)
        flash(f'Error adding sponsor: {str(e)}', 'error')
        return redirect(url_for('wallet_config.sponsors'))


@wallet_config_bp.route('/sponsors/<int:sponsor_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def delete_sponsor(sponsor_id):
    """Delete a sponsor"""
    from app.models.wallet_config import WalletSponsor

    try:
        sponsor = WalletSponsor.query.get_or_404(sponsor_id)
        name = sponsor.name
        db.session.delete(sponsor)
        db.session.commit()

        flash(f'Sponsor "{name}" deleted successfully.', 'success')
        return redirect(url_for('wallet_config.sponsors'))

    except Exception as e:
        logger.error(f"Error deleting sponsor: {str(e)}", exc_info=True)
        flash(f'Error deleting sponsor: {str(e)}', 'error')
        return redirect(url_for('wallet_config.sponsors'))


# =============================================================================
# SUBGROUPS MANAGEMENT
# =============================================================================

@wallet_config_bp.route('/subgroups')
@login_required
@role_required(['Global Admin'])
def subgroups():
    """Subgroup management page for ECS supporter subgroups"""
    from app.models.wallet_config import WalletSubgroup

    try:
        all_subgroups = WalletSubgroup.query.order_by(
            WalletSubgroup.display_order, WalletSubgroup.name
        ).all()

        return render_template(
            'admin/wallet_config/subgroups_flowbite.html',
            subgroups=all_subgroups
        )

    except Exception as e:
        logger.error(f"Error loading subgroups page: {str(e)}", exc_info=True)
        flash('Error loading subgroups page.', 'error')
        return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/subgroups/add', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def add_subgroup():
    """Add a new subgroup"""
    from app.models.wallet_config import WalletSubgroup

    try:
        code = request.form.get('code', '').lower().replace(' ', '_').replace('-', '_')
        subgroup = WalletSubgroup(
            code=code,
            name=request.form.get('name'),
            description=request.form.get('description'),
            is_active=request.form.get('is_active') == 'on'
        )
        db.session.add(subgroup)
        db.session.commit()

        flash(f'Subgroup "{subgroup.name}" added successfully.', 'success')
        return redirect(url_for('wallet_config.subgroups'))

    except Exception as e:
        logger.error(f"Error adding subgroup: {str(e)}", exc_info=True)
        flash(f'Error adding subgroup: {str(e)}', 'error')
        return redirect(url_for('wallet_config.subgroups'))


@wallet_config_bp.route('/subgroups/<int:subgroup_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def delete_subgroup(subgroup_id):
    """Delete a subgroup"""
    from app.models.wallet_config import WalletSubgroup

    try:
        subgroup = WalletSubgroup.query.get_or_404(subgroup_id)
        name = subgroup.name
        db.session.delete(subgroup)
        db.session.commit()

        flash(f'Subgroup "{name}" deleted successfully.', 'success')
        return redirect(url_for('wallet_config.subgroups'))

    except Exception as e:
        logger.error(f"Error deleting subgroup: {str(e)}", exc_info=True)
        flash(f'Error deleting subgroup: {str(e)}', 'error')
        return redirect(url_for('wallet_config.subgroups'))


# =============================================================================
# PASS FIELDS CONFIGURATION
# =============================================================================

@wallet_config_bp.route('/fields/<pass_type>')
@login_required
@role_required(['Global Admin'])
def pass_fields(pass_type):
    """
    Configure pass fields for a specific pass type

    User-friendly interface for configuring what information appears on passes.
    """
    from app.models.wallet_config import WalletPassFieldConfig, WalletBackField

    try:
        # Get pass type
        if pass_type == 'ecs':
            pass_obj = WalletPassType.get_ecs_membership()
        elif pass_type == 'pub':
            pass_obj = WalletPassType.get_pub_league()
        else:
            flash('Invalid pass type.', 'error')
            return redirect(url_for('wallet_config.templates'))

        if not pass_obj:
            flash('Pass type not found.', 'error')
            return redirect(url_for('wallet_config.templates'))

        # Get configured fields
        front_fields = WalletPassFieldConfig.query.filter_by(
            pass_type_id=pass_obj.id
        ).order_by(WalletPassFieldConfig.display_order).all()

        back_fields = WalletBackField.query.filter_by(
            pass_type_id=pass_obj.id
        ).order_by(WalletBackField.display_order).all()

        return render_template(
            'admin/wallet_config/pass_fields_flowbite.html',
            pass_type=pass_obj,
            pass_type_code=pass_type,
            front_fields=front_fields,
            back_fields=back_fields
        )

    except Exception as e:
        logger.error(f"Error loading pass fields page: {str(e)}", exc_info=True)
        flash(f'Error loading pass fields: {str(e)}', 'error')
        return redirect(url_for('wallet_config.templates'))


@wallet_config_bp.route('/fields/<pass_type>/save', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def save_pass_fields(pass_type):
    """Save pass field configurations"""
    from app.models.wallet_config import WalletPassFieldConfig, WalletBackField

    try:
        # Get pass type
        if pass_type == 'ecs':
            pass_obj = WalletPassType.get_ecs_membership()
        elif pass_type == 'pub':
            pass_obj = WalletPassType.get_pub_league()
        else:
            flash('Invalid pass type.', 'error')
            return redirect(url_for('wallet_config.templates'))

        if not pass_obj:
            flash('Pass type not found.', 'error')
            return redirect(url_for('wallet_config.templates'))

        # Process front fields from form
        field_data = request.form.to_dict(flat=False)

        # Get existing fields
        existing_front = {f.field_key: f for f in WalletPassFieldConfig.query.filter_by(
            pass_type_id=pass_obj.id
        ).all()}

        existing_back = {f.field_key: f for f in WalletBackField.query.filter_by(
            pass_type_id=pass_obj.id
        ).all()}

        # Process front field updates
        front_field_keys = field_data.get('front_field_key', [])
        front_field_labels = field_data.get('front_field_label', [])
        front_field_locations = field_data.get('front_field_location', [])
        front_field_templates = field_data.get('front_field_template', [])
        front_field_visible = field_data.get('front_field_visible', [])

        processed_front_keys = set()
        for i, key in enumerate(front_field_keys):
            if not key:
                continue

            processed_front_keys.add(key)

            if key in existing_front:
                # Update existing
                field = existing_front[key]
                field.label = front_field_labels[i] if i < len(front_field_labels) else field.label
                field.field_location = front_field_locations[i] if i < len(front_field_locations) else field.field_location
                field.value_template = front_field_templates[i] if i < len(front_field_templates) else field.value_template
                field.is_visible = key in front_field_visible
                field.display_order = i
            else:
                # Create new
                new_field = WalletPassFieldConfig(
                    pass_type_id=pass_obj.id,
                    field_key=key,
                    label=front_field_labels[i] if i < len(front_field_labels) else key.upper(),
                    field_location=front_field_locations[i] if i < len(front_field_locations) else 'auxiliary',
                    value_template=front_field_templates[i] if i < len(front_field_templates) else '',
                    is_visible=key in front_field_visible,
                    display_order=i
                )
                db.session.add(new_field)

        # Process back field updates
        back_field_keys = field_data.get('back_field_key', [])
        back_field_labels = field_data.get('back_field_label', [])
        back_field_values = field_data.get('back_field_value', [])
        back_field_visible = field_data.get('back_field_visible', [])

        processed_back_keys = set()
        for i, key in enumerate(back_field_keys):
            if not key:
                continue

            processed_back_keys.add(key)

            if key in existing_back:
                # Update existing
                field = existing_back[key]
                field.label = back_field_labels[i] if i < len(back_field_labels) else field.label
                field.value = back_field_values[i] if i < len(back_field_values) else field.value
                field.is_visible = key in back_field_visible
                field.display_order = i
            else:
                # Create new
                new_field = WalletBackField(
                    pass_type_id=pass_obj.id,
                    field_key=key,
                    label=back_field_labels[i] if i < len(back_field_labels) else key.upper(),
                    value=back_field_values[i] if i < len(back_field_values) else '',
                    is_visible=key in back_field_visible,
                    display_order=i
                )
                db.session.add(new_field)

        db.session.commit()

        flash(f'{pass_obj.name} fields updated successfully.', 'success')
        return redirect(url_for('wallet_config.pass_fields', pass_type=pass_type))

    except Exception as e:
        logger.error(f"Error saving pass fields: {str(e)}", exc_info=True)
        flash(f'Error saving pass fields: {str(e)}', 'error')
        return redirect(url_for('wallet_config.pass_fields', pass_type=pass_type))


# =============================================================================
# PASS DESIGN (User-friendly visual editor replacement)
# =============================================================================

@wallet_config_bp.route('/design/<pass_type>')
@login_required
@role_required(['Global Admin'])
def pass_design(pass_type):
    """
    User-friendly pass design page

    Provides a simple interface for customizing passes without technical knowledge.
    Replaces the JSON-heavy visual_editor with form-based configuration.
    """
    from app.models.wallet_config import (
        WalletLocation, WalletSponsor, WalletSubgroup,
        WalletPassFieldConfig, WalletBackField
    )

    try:
        # Get pass type
        if pass_type == 'ecs':
            pass_obj = WalletPassType.get_ecs_membership()
        elif pass_type == 'pub':
            pass_obj = WalletPassType.get_pub_league()
        else:
            flash('Invalid pass type.', 'error')
            return redirect(url_for('wallet_config.templates'))

        if not pass_obj:
            flash('Pass type not found. Please initialize pass types first.', 'error')
            return redirect(url_for('wallet_config.dashboard'))

        # Get configured fields
        front_fields = WalletPassFieldConfig.query.filter_by(
            pass_type_id=pass_obj.id, is_visible=True
        ).order_by(WalletPassFieldConfig.display_order).all()

        back_fields = WalletBackField.query.filter_by(
            pass_type_id=pass_obj.id, is_visible=True
        ).order_by(WalletBackField.display_order).all()

        # Get locations for this pass type
        locations = WalletLocation.get_for_pass_type(pass_obj.code, limit=10)

        # Get sponsors for this pass type
        sponsors = WalletSponsor.get_active_for_pass_type(pass_obj.code)

        # Get subgroups (for ECS only)
        subgroups = []
        if pass_type == 'ecs':
            subgroups = WalletSubgroup.get_active()

        # Get assets
        assets = WalletAsset.get_assets_by_pass_type(pass_obj.id)
        assets_dict = {a.asset_type: a for a in assets}

        # Get template
        template = WalletTemplate.get_default(pass_obj.id, 'apple')
        template_content = json.loads(template.content) if template else None

        return render_template(
            'admin/wallet_config/pass_design_flowbite.html',
            pass_type=pass_obj,
            pass_type_code=pass_type,
            front_fields=front_fields,
            back_fields=back_fields,
            locations=locations,
            sponsors=sponsors,
            subgroups=subgroups,
            assets=assets_dict,
            template=template,
            template_content=template_content,
            # Available template variables
            available_variables=[
                {'var': '{{member_name}}', 'desc': "Member's full name"},
                {'var': '{{validity}}', 'desc': 'Membership year or season name'},
                {'var': '{{team_name}}', 'desc': "Player's team (Pub League)"},
                {'var': '{{member_since}}', 'desc': 'Year member joined (if known)'},
                {'var': '{{subgroup}}', 'desc': 'Supporter subgroup (ECS)'},
                {'var': '{{barcode_data}}', 'desc': 'Unique pass barcode'},
                {'var': '{{serial_number}}', 'desc': 'Unique pass ID'},
            ]
        )

    except Exception as e:
        logger.error(f"Error loading pass design page: {str(e)}", exc_info=True)
        flash(f'Error loading pass design: {str(e)}', 'error')
        return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/design/<pass_type>/save', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def save_pass_design(pass_type):
    """
    Save pass design from user-friendly form

    Updates all aspects of the pass configuration including:
    - Colors and appearance
    - Field configurations
    - Locations
    """
    from app.models.wallet_config import WalletPassFieldConfig, WalletBackField, WalletLocation

    try:
        # Get pass type
        if pass_type == 'ecs':
            pass_obj = WalletPassType.get_ecs_membership()
        elif pass_type == 'pub':
            pass_obj = WalletPassType.get_pub_league()
        else:
            return jsonify({'success': False, 'error': 'Invalid pass type'}), 400

        if not pass_obj:
            return jsonify({'success': False, 'error': 'Pass type not found'}), 404

        # Update appearance settings
        if request.form.get('background_color'):
            pass_obj.background_color = request.form.get('background_color')
        if request.form.get('foreground_color'):
            pass_obj.foreground_color = request.form.get('foreground_color')
        if request.form.get('label_color'):
            pass_obj.label_color = request.form.get('label_color')
        if request.form.get('logo_text'):
            pass_obj.logo_text = request.form.get('logo_text')

        db.session.commit()

        # Regenerate template with updated settings
        template = WalletTemplate.get_default(pass_obj.id, 'apple')

        if template:
            try:
                content = json.loads(template.content)
                content['backgroundColor'] = pass_obj.background_color
                content['foregroundColor'] = pass_obj.foreground_color
                content['labelColor'] = pass_obj.label_color
                content['logoText'] = pass_obj.logo_text

                # Update locations in template
                active_locations = WalletLocation.get_for_pass_type(pass_obj.code, limit=10)
                if active_locations:
                    content['locations'] = [loc.to_pass_dict() for loc in active_locations]
                elif 'locations' in content:
                    del content['locations']

                template.content = json.dumps(content, indent=2)
                db.session.commit()
            except json.JSONDecodeError:
                logger.warning("Could not update template JSON")

        flash(f'{pass_obj.name} design updated successfully.', 'success')

        # Send push updates
        try:
            push_result = pass_service.update_pass_type_design(pass_obj.id)
            if push_result.get('push_results'):
                total = push_result['push_results'].get('total_passes', 0)
                if total > 0:
                    flash(f'Push updates sent to {total} existing passes.', 'info')
        except Exception as push_error:
            logger.warning(f"Failed to send push updates: {push_error}")

        return redirect(url_for('wallet_config.pass_design', pass_type=pass_type))

    except Exception as e:
        logger.error(f"Error saving pass design: {str(e)}", exc_info=True)
        flash(f'Error saving design: {str(e)}', 'error')
        return redirect(url_for('wallet_config.pass_design', pass_type=pass_type))


# =============================================================================
# API ENDPOINTS FOR AJAX
# =============================================================================

@wallet_config_bp.route('/api/locations')
@login_required
@role_required(['Global Admin'])
def api_get_locations():
    """Get all locations as JSON"""
    from app.models.wallet_config import WalletLocation

    locations = WalletLocation.query.order_by(WalletLocation.display_order).all()
    return jsonify([loc.to_dict() for loc in locations])


@wallet_config_bp.route('/api/sponsors')
@login_required
@role_required(['Global Admin'])
def api_get_sponsors():
    """Get all sponsors as JSON"""
    from app.models.wallet_config import WalletSponsor

    sponsors = WalletSponsor.query.order_by(WalletSponsor.display_order).all()
    return jsonify([s.to_dict() for s in sponsors])


@wallet_config_bp.route('/api/subgroups')
@login_required
@role_required(['Global Admin'])
def api_get_subgroups():
    """Get all subgroups as JSON"""
    from app.models.wallet_config import WalletSubgroup

    subgroups = WalletSubgroup.query.order_by(WalletSubgroup.display_order).all()
    return jsonify([s.to_dict() for s in subgroups])


@wallet_config_bp.route('/api/init-defaults', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def api_init_defaults():
    """Initialize default wallet configuration data"""
    from app.models.wallet_config import initialize_wallet_config_defaults

    try:
        initialize_wallet_config_defaults()
        return jsonify({'success': True, 'message': 'Defaults initialized'})
    except Exception as e:
        logger.error(f"Error initializing defaults: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500