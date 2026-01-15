# app/admin/wallet/design_routes.py

"""
Wallet Pass Design Routes

Handles pass design and visual editor functionality.
Provides user-friendly interface for customizing passes without JSON editing.
"""

import json
import logging
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required

from app.core import db
from app.utils.db_utils import transactional
from app.models.wallet import WalletPassType
from app.models.wallet_asset import WalletAsset, WalletTemplate
from app.models.wallet_config import (
    WalletLocation, WalletSponsor, WalletSubgroup,
    WalletPassFieldConfig, WalletBackField,
    initialize_wallet_config_defaults
)
from app.decorators import role_required
from app.wallet_pass.services.pass_service import pass_service

from . import wallet_config_bp
from .helpers import get_pass_type_or_redirect

logger = logging.getLogger(__name__)


# =============================================================================
# VISUAL EDITOR (Legacy - kept for backwards compatibility)
# =============================================================================

@wallet_config_bp.route('/editor/<pass_type>')
@login_required
@role_required(['Global Admin'])
def visual_editor(pass_type):
    """
    Visual pass editor (legacy)

    Provides a visual editor for customizing pass appearance.
    Consider using /design/<pass_type> for the newer user-friendly version.
    """
    try:
        pass_obj, error_redirect = get_pass_type_or_redirect(pass_type)
        if error_redirect:
            return error_redirect

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
@transactional
def save_visual_editor():
    """Save changes from visual editor"""
    try:
        pass_type_id = request.form.get('pass_type_id')
        background_color = request.form.get('background_color')
        foreground_color = request.form.get('foreground_color')
        label_color = request.form.get('label_color')
        logo_text = request.form.get('logo_text')
        template_content = request.form.get('template_content')

        pass_type = WalletPassType.query.get_or_404(pass_type_id)

        if background_color:
            pass_type.background_color = background_color
        if foreground_color:
            pass_type.foreground_color = foreground_color
        if label_color:
            pass_type.label_color = label_color
        if logo_text:
            pass_type.logo_text = logo_text

        # Update or create template if content provided
        if template_content:
            template = WalletTemplate.get_default(pass_type_id, 'apple')

            if template:
                template.content = template_content
            else:
                template = WalletTemplate(
                    pass_type_id=int(pass_type_id),
                    platform='apple',
                    name=f"Default {pass_type.name} Template",
                    content=template_content,
                    is_default=True
                )
                db.session.add(template)

        flash(f'{pass_type.name} appearance updated successfully.', 'success')

        # Send push updates
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
# PASS DESIGN (User-friendly editor)
# =============================================================================

@wallet_config_bp.route('/design/<pass_type>')
@login_required
@role_required(['Global Admin'])
def pass_design(pass_type):
    """
    User-friendly pass design page

    Provides a simple interface for customizing passes without technical knowledge.
    Supports both Apple and Google Wallet platforms via ?platform= query param.
    """
    try:
        pass_obj, error_redirect = get_pass_type_or_redirect(pass_type, 'wallet_config.dashboard')
        if error_redirect:
            return error_redirect

        # Get platform from query param, default to apple
        platform = request.args.get('platform', 'apple')
        if platform not in ('apple', 'google'):
            platform = 'apple'

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

        # Get template for selected platform
        template = WalletTemplate.get_default(pass_obj.id, platform)
        template_content = json.loads(template.content) if template else None

        # Get template for other platform to show availability
        other_platform = 'google' if platform == 'apple' else 'apple'
        other_template = WalletTemplate.get_default(pass_obj.id, other_platform)

        return render_template(
            'admin/wallet_config/pass_design_flowbite.html',
            pass_type=pass_obj,
            pass_type_code=pass_type,
            platform=platform,
            other_platform=other_platform,
            has_other_template=other_template is not None,
            front_fields=front_fields,
            back_fields=back_fields,
            locations=locations,
            sponsors=sponsors,
            subgroups=subgroups,
            assets=assets_dict,
            template=template,
            template_content=template_content,
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
@transactional
def save_pass_design(pass_type):
    """Save pass design from user-friendly form"""
    try:
        pass_obj, error_redirect = get_pass_type_or_redirect(pass_type, 'wallet_config.dashboard')
        if error_redirect:
            return error_redirect

        # Get platform from form, default to apple
        platform = request.form.get('platform', 'apple')
        if platform not in ('apple', 'google'):
            platform = 'apple'

        # Update appearance settings (shared across platforms)
        if request.form.get('background_color'):
            pass_obj.background_color = request.form.get('background_color')
        if request.form.get('foreground_color'):
            pass_obj.foreground_color = request.form.get('foreground_color')
        if request.form.get('label_color'):
            pass_obj.label_color = request.form.get('label_color')
        if request.form.get('logo_text'):
            pass_obj.logo_text = request.form.get('logo_text')

        # Update template for the specified platform
        template = WalletTemplate.get_default(pass_obj.id, platform)

        if template:
            try:
                content = json.loads(template.content)

                if platform == 'apple':
                    # Apple-specific template fields
                    content['backgroundColor'] = pass_obj.background_color
                    content['foregroundColor'] = pass_obj.foreground_color
                    content['labelColor'] = pass_obj.label_color
                    content['logoText'] = pass_obj.logo_text

                    # Update locations in Apple template
                    active_locations = WalletLocation.get_for_pass_type(pass_obj.code, limit=10)
                    if active_locations:
                        content['locations'] = [loc.to_pass_dict() for loc in active_locations]
                    elif 'locations' in content:
                        del content['locations']

                elif platform == 'google':
                    # Google-specific template fields
                    content['hexBackgroundColor'] = pass_obj.background_color
                    # Google doesn't have direct equivalents for foreground/label colors

                template.content = json.dumps(content, indent=2)
            except json.JSONDecodeError:
                logger.warning("Could not update template JSON")

        # Also update the other platform's template if it exists
        other_platform = 'google' if platform == 'apple' else 'apple'
        other_template = WalletTemplate.get_default(pass_obj.id, other_platform)
        if other_template:
            try:
                other_content = json.loads(other_template.content)
                if other_platform == 'apple':
                    other_content['backgroundColor'] = pass_obj.background_color
                    other_content['foregroundColor'] = pass_obj.foreground_color
                    other_content['labelColor'] = pass_obj.label_color
                    other_content['logoText'] = pass_obj.logo_text
                elif other_platform == 'google':
                    other_content['hexBackgroundColor'] = pass_obj.background_color
                other_template.content = json.dumps(other_content, indent=2)
            except json.JSONDecodeError:
                logger.warning(f"Could not update {other_platform} template JSON")

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

        return redirect(url_for('wallet_config.pass_design', pass_type=pass_type, platform=platform))

    except Exception as e:
        logger.error(f"Error saving pass design: {str(e)}", exc_info=True)
        flash(f'Error saving design: {str(e)}', 'error')
        return redirect(url_for('wallet_config.pass_design', pass_type=pass_type))


# =============================================================================
# PASS FIELDS CONFIGURATION
# =============================================================================

@wallet_config_bp.route('/fields/<pass_type>')
@login_required
@role_required(['Global Admin'])
def pass_fields(pass_type):
    """Configure pass fields for a specific pass type"""
    try:
        pass_obj, error_redirect = get_pass_type_or_redirect(pass_type)
        if error_redirect:
            return error_redirect

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
@transactional
def save_pass_fields(pass_type):
    """Save pass field configurations"""
    try:
        pass_obj, error_redirect = get_pass_type_or_redirect(pass_type)
        if error_redirect:
            return error_redirect

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

        for i, key in enumerate(front_field_keys):
            if not key:
                continue

            if key in existing_front:
                field = existing_front[key]
                field.label = front_field_labels[i] if i < len(front_field_labels) else field.label
                field.field_location = front_field_locations[i] if i < len(front_field_locations) else field.field_location
                field.value_template = front_field_templates[i] if i < len(front_field_templates) else field.value_template
                field.is_visible = key in front_field_visible
                field.display_order = i
            else:
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

        for i, key in enumerate(back_field_keys):
            if not key:
                continue

            if key in existing_back:
                field = existing_back[key]
                field.label = back_field_labels[i] if i < len(back_field_labels) else field.label
                field.value = back_field_values[i] if i < len(back_field_values) else field.value
                field.is_visible = key in back_field_visible
                field.display_order = i
            else:
                new_field = WalletBackField(
                    pass_type_id=pass_obj.id,
                    field_key=key,
                    label=back_field_labels[i] if i < len(back_field_labels) else key.upper(),
                    value=back_field_values[i] if i < len(back_field_values) else '',
                    is_visible=key in back_field_visible,
                    display_order=i
                )
                db.session.add(new_field)

        flash(f'{pass_obj.name} fields updated successfully.', 'success')
        return redirect(url_for('wallet_config.pass_fields', pass_type=pass_type))

    except Exception as e:
        logger.error(f"Error saving pass fields: {str(e)}", exc_info=True)
        flash(f'Error saving pass fields: {str(e)}', 'error')
        return redirect(url_for('wallet_config.pass_fields', pass_type=pass_type))


# =============================================================================
# API ENDPOINTS
# =============================================================================

@wallet_config_bp.route('/api/init-defaults', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def api_init_defaults():
    """Initialize default wallet configuration data"""
    try:
        initialize_wallet_config_defaults()
        return jsonify({'success': True, 'message': 'Defaults initialized'})
    except Exception as e:
        logger.error(f"Error initializing defaults: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
