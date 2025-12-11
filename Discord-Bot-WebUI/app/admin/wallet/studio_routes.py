# app/admin/wallet/studio_routes.py

"""
Pass Studio Routes

Unified Pass Studio for creating and editing wallet passes.
Provides a cohesive, non-technical interface for managing:
- Pass appearance (colors, logos)
- Field configuration (primary, secondary, auxiliary, header, back)
- Location management (sponsor-linked and manual)
- Sponsor management (with address/geocoding)
- Draft/Publish workflow
"""

import logging
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required

from app.core import db
from app.models.wallet import WalletPassType
from app.models.wallet_config import (
    WalletLocation, WalletSponsor, WalletSubgroup,
    WalletPassFieldConfig, WalletBackField
)
from app.models.wallet_asset import WalletAsset, WalletCertificate, WalletTemplate
from app.decorators import role_required
from app.services.asset_service import asset_service, ASSET_TYPES

logger = logging.getLogger(__name__)


def get_config_status():
    """
    Get simplified wallet configuration status for Pass Studio.

    This is a lighter version that doesn't import wallet_pass module
    to avoid circular import issues.
    """
    try:
        # Check certificates
        cert_complete = WalletCertificate.has_complete_apple_config()

        # Get pass types
        ecs_type = WalletPassType.get_ecs_membership()
        pub_type = WalletPassType.get_pub_league()

        required_assets = ['icon', 'logo']

        # Check ECS assets
        ecs_assets_complete = False
        if ecs_type:
            ecs_assets = WalletAsset.get_assets_by_pass_type(ecs_type.id)
            ecs_asset_types = [a.asset_type for a in ecs_assets]
            ecs_assets_complete = all(req in ecs_asset_types for req in required_assets)

        # Check Pub League assets
        pub_assets_complete = False
        if pub_type:
            pub_assets = WalletAsset.get_assets_by_pass_type(pub_type.id)
            pub_asset_types = [a.asset_type for a in pub_assets]
            pub_assets_complete = all(req in pub_asset_types for req in required_assets)

        # Check templates
        ecs_template = WalletTemplate.get_default(ecs_type.id, 'apple') if ecs_type else None
        pub_template = WalletTemplate.get_default(pub_type.id, 'apple') if pub_type else None

        # Calculate overall progress
        total_steps = 4  # certificates, assets, templates, testing
        completed = 0
        if cert_complete:
            completed += 1
        if ecs_assets_complete and pub_assets_complete:
            completed += 1
        if ecs_template and pub_template:
            completed += 1

        # Ready when both pass types have everything
        ecs_ready = cert_complete and ecs_assets_complete and ecs_template is not None
        pub_ready = cert_complete and pub_assets_complete and pub_template is not None

        return {
            'ready': ecs_ready or pub_ready,
            'progress': {
                'certificates': cert_complete,
                'assets': ecs_assets_complete or pub_assets_complete,
                'templates': ecs_template is not None or pub_template is not None,
                'testing': False,
                'percent': int((completed / total_steps) * 100)
            },
            'ecs_ready': ecs_ready,
            'pub_ready': pub_ready
        }
    except Exception as e:
        logger.error(f"Error getting config status: {e}")
        return {
            'ready': False,
            'progress': {
                'certificates': False,
                'assets': False,
                'templates': False,
                'testing': False,
                'percent': 0
            },
            'ecs_ready': False,
            'pub_ready': False
        }

# Create blueprint
pass_studio_bp = Blueprint('pass_studio', __name__, url_prefix='/admin/wallet/studio')


# =============================================================================
# PASS STUDIO INDEX
# =============================================================================

@pass_studio_bp.route('/')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def index():
    """Pass Studio index - select which pass type to edit"""
    try:
        ecs_type = WalletPassType.get_ecs_membership()
        pub_type = WalletPassType.get_pub_league()
        config = get_config_status()

        return render_template(
            'admin/pass_studio/index.html',
            ecs_type=ecs_type,
            pub_type=pub_type,
            wallet_config=config
        )
    except Exception as e:
        logger.error(f"Error loading Pass Studio index: {str(e)}", exc_info=True)
        flash('Error loading Pass Studio.', 'error')
        return redirect(url_for('wallet_admin.wallet_management'))


# =============================================================================
# MAIN STUDIO EDITOR
# =============================================================================

@pass_studio_bp.route('/<pass_type_code>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def studio(pass_type_code):
    """Main Pass Studio editor for a specific pass type"""
    try:
        # Validate pass type
        if pass_type_code not in ['ecs_membership', 'pub_league']:
            flash('Invalid pass type.', 'error')
            return redirect(url_for('pass_studio.index'))

        # Get pass type
        pass_type = WalletPassType.get_by_code(pass_type_code)
        if not pass_type:
            flash(f'Pass type "{pass_type_code}" not configured. Please run setup first.', 'warning')
            return redirect(url_for('wallet_config.setup_wizard'))

        # Get the other pass type for switching
        other_code = 'pub_league' if pass_type_code == 'ecs_membership' else 'ecs_membership'
        other_type = WalletPassType.get_by_code(other_code)

        # Get configuration status
        config = get_config_status()

        # Track if tables are missing for warning message
        tables_missing = False

        # Get field configurations with graceful fallback
        front_fields = []
        back_fields = []
        try:
            front_fields = WalletPassFieldConfig.query.filter(
                WalletPassFieldConfig.pass_type_id == pass_type.id,
                WalletPassFieldConfig.field_location.in_(['primary', 'secondary', 'auxiliary', 'header'])
            ).order_by(WalletPassFieldConfig.display_order).all()

            back_fields = WalletBackField.query.filter_by(
                pass_type_id=pass_type.id
            ).order_by(WalletBackField.display_order).all()
        except Exception as e:
            logger.warning(f"Could not load field configurations: {e}. Tables may not exist yet.")
            tables_missing = True

        # Get locations (max 10 for Apple Wallet) with graceful fallback
        locations = []
        try:
            locations = WalletLocation.query.filter(
                db.or_(
                    WalletLocation.applies_to == 'all',
                    WalletLocation.applies_to == pass_type_code
                )
            ).order_by(WalletLocation.display_order).all()
        except Exception as e:
            logger.warning(f"Could not load locations: {e}. Table may not exist yet.")
            tables_missing = True

        # Get sponsors with graceful fallback
        sponsors = []
        try:
            sponsors = WalletSponsor.query.filter(
                db.or_(
                    WalletSponsor.applies_to == 'all',
                    WalletSponsor.applies_to == pass_type_code
                )
            ).order_by(WalletSponsor.display_order).all()
        except Exception as e:
            logger.warning(f"Could not load sponsors: {e}. Table may not exist yet.")
            tables_missing = True

        # Get subgroups (ECS only) with graceful fallback
        subgroups = []
        if pass_type_code == 'ecs_membership':
            try:
                subgroups = WalletSubgroup.get_active()
            except Exception as e:
                logger.warning(f"Could not load subgroups: {e}. Table may not exist yet.")
                tables_missing = True

        # Show warning if tables are missing
        if tables_missing:
            flash('Some configuration tables are missing. Run "flask wallet create_tables" from the command line to create them.', 'warning')

        # Get assets
        assets = {a.asset_type: a for a in WalletAsset.get_assets_by_pass_type(pass_type.id)}

        # Active tab from query param
        active_tab = request.args.get('tab', 'appearance')

        # Template variables and sample data based on pass type
        if pass_type_code == 'ecs_membership':
            template_variables = [
                {'name': 'member_name', 'label': 'Member Name', 'description': "Member's full name"},
                {'name': 'validity', 'label': 'Validity', 'description': 'Membership year (e.g., 2025)'},
                {'name': 'member_since', 'label': 'Member Since', 'description': 'Year member joined'},
                {'name': 'subgroup', 'label': 'Subgroup', 'description': 'Supporter subgroup (if any)'},
                {'name': 'barcode_data', 'label': 'Barcode', 'description': 'Unique barcode value'},
                {'name': 'serial_number', 'label': 'Serial Number', 'description': 'Unique pass ID'},
            ]
            sample_data = {
                'member_name': 'Jane Smith',
                'validity': '2025',
                'member_since': '2019',
                'subgroup': 'Gorilla FC',
                'barcode_data': 'ECSFC-ECS-ABC123DEF456',
                'serial_number': 'abc123-def456-789'
            }
        else:
            template_variables = [
                {'name': 'member_name', 'label': 'Player Name', 'description': "Player's full name"},
                {'name': 'team_name', 'label': 'Team Name', 'description': "Player's team"},
                {'name': 'validity', 'label': 'Season', 'description': 'Current season (e.g., Spring 2025)'},
                {'name': 'barcode_data', 'label': 'Barcode', 'description': 'Unique barcode value'},
                {'name': 'serial_number', 'label': 'Serial Number', 'description': 'Unique pass ID'},
            ]
            sample_data = {
                'member_name': 'John Doe',
                'team_name': 'FC Placeholder',
                'validity': 'Spring 2025',
                'barcode_data': 'ECSFC-PUB-XYZ789ABC123',
                'serial_number': 'xyz789-abc123-456'
            }

        return render_template(
            'admin/pass_studio/studio.html',
            pass_type=pass_type,
            pass_type_code=pass_type_code,
            other_type=other_type,
            wallet_config=config,
            front_fields=front_fields,
            back_fields=back_fields,
            locations=locations,
            sponsors=sponsors,
            subgroups=subgroups,
            assets=assets,
            active_tab=active_tab,
            template_variables=template_variables,
            sample_data=sample_data,
            location_count=len([l for l in locations if l.is_active]),
            max_locations=10
        )

    except Exception as e:
        logger.error(f"Error loading Pass Studio for {pass_type_code}: {str(e)}", exc_info=True)
        flash('Error loading Pass Studio.', 'error')
        return redirect(url_for('pass_studio.index'))


# =============================================================================
# APPEARANCE UPDATES
# =============================================================================

@pass_studio_bp.route('/<pass_type_code>/appearance', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def save_appearance(pass_type_code):
    """Save appearance settings (colors, logo text)"""
    try:
        pass_type = WalletPassType.get_by_code(pass_type_code)
        if not pass_type:
            return jsonify({'success': False, 'error': 'Pass type not found'}), 404

        data = request.get_json() if request.is_json else request.form

        # Update colors if provided
        if 'background_color' in data:
            pass_type.background_color = data['background_color']
        if 'foreground_color' in data:
            pass_type.foreground_color = data['foreground_color']
        if 'label_color' in data:
            pass_type.label_color = data['label_color']
        if 'logo_text' in data:
            pass_type.logo_text = data['logo_text']

        # Update Google Wallet URLs
        if 'google_hero_image_url' in data:
            pass_type.google_hero_image_url = data['google_hero_image_url'] or None
        if 'google_logo_url' in data:
            pass_type.google_logo_url = data['google_logo_url'] or None

        # Update barcode settings
        if 'suppress_barcode' in data:
            # Handle both boolean and string values
            suppress_value = data['suppress_barcode']
            if isinstance(suppress_value, bool):
                pass_type.suppress_barcode = suppress_value
            else:
                pass_type.suppress_barcode = str(suppress_value).lower() in ('true', '1', 'on', 'yes')

        # Update pass style (generic, storeCard, eventTicket)
        if 'apple_pass_style' in data:
            style = data['apple_pass_style']
            logger.info(f"Received apple_pass_style: '{style}' (current: '{pass_type.apple_pass_style}')")
            if style in ('generic', 'storeCard', 'eventTicket'):
                pass_type.apple_pass_style = style
                logger.info(f"Updated apple_pass_style to: '{pass_type.apple_pass_style}'")

        # Update logo visibility
        if 'show_logo' in data:
            show_value = data['show_logo']
            if isinstance(show_value, bool):
                pass_type.show_logo = show_value
            else:
                pass_type.show_logo = str(show_value).lower() in ('true', '1', 'on', 'yes')

        db.session.commit()

        # Send push updates to all existing passes of this type
        push_sent = False
        push_result = None
        try:
            from app.wallet_pass.services.pass_service import pass_service
            push_result = pass_service.update_pass_type_design(pass_type.id)
            push_sent = True
            logger.info(f"Pushed appearance update to passes: {push_result}")
        except Exception as push_err:
            logger.warning(f"Failed to push appearance update: {push_err}")

        if request.is_json:
            return jsonify({
                'success': True,
                'message': 'Appearance updated',
                'push_sent': push_sent,
                'push_result': push_result,
                'data': {
                    'background_color': pass_type.background_color,
                    'foreground_color': pass_type.foreground_color,
                    'label_color': pass_type.label_color,
                    'logo_text': pass_type.logo_text,
                    'apple_pass_style': pass_type.apple_pass_style or 'generic',
                    'google_hero_image_url': pass_type.google_hero_image_url,
                    'google_logo_url': pass_type.google_logo_url,
                    'suppress_barcode': pass_type.suppress_barcode or False,
                    'show_logo': pass_type.show_logo if pass_type.show_logo is not None else True
                }
            })

        flash('Appearance settings saved. Push updates sent to existing passes.', 'success')
        return redirect(url_for('pass_studio.studio', pass_type_code=pass_type_code, tab='appearance'))

    except Exception as e:
        logger.error(f"Error saving appearance: {str(e)}", exc_info=True)
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f'Error saving appearance: {str(e)}', 'error')
        return redirect(url_for('pass_studio.studio', pass_type_code=pass_type_code, tab='appearance'))


# =============================================================================
# FIELD CONFIGURATION
# =============================================================================

@pass_studio_bp.route('/<pass_type_code>/fields', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def save_fields(pass_type_code):
    """Save field configuration"""
    try:
        pass_type = WalletPassType.get_by_code(pass_type_code)
        if not pass_type:
            return jsonify({'success': False, 'error': 'Pass type not found'}), 404

        data = request.get_json() if request.is_json else None
        if not data:
            flash('Invalid request data.', 'error')
            return redirect(url_for('pass_studio.studio', pass_type_code=pass_type_code, tab='fields'))

        # Process front fields
        if 'front_fields' in data:
            for field_data in data['front_fields']:
                field = WalletPassFieldConfig.query.filter_by(
                    pass_type_id=pass_type.id,
                    field_key=field_data['field_key']
                ).first()

                if field:
                    field.label = field_data.get('label', field.label)
                    field.field_location = field_data.get('field_location', field.field_location)
                    field.value_template = field_data.get('value_template', field.value_template)
                    field.is_visible = field_data.get('is_visible', field.is_visible)
                    field.display_order = field_data.get('display_order', field.display_order)
                    field.field_type = field_data.get('field_type', field.field_type)
                    field.text_alignment = field_data.get('text_alignment', field.text_alignment)
                    field.date_style = field_data.get('date_style') or None
                    field.time_style = field_data.get('time_style') or None
                    field.number_style = field_data.get('number_style') or None
                    field.currency_code = field_data.get('currency_code') or None
                else:
                    # Create new field
                    field = WalletPassFieldConfig(
                        pass_type_id=pass_type.id,
                        field_key=field_data['field_key'],
                        label=field_data.get('label', field_data['field_key'].upper()),
                        field_location=field_data.get('field_location', 'secondary'),
                        value_template=field_data.get('value_template', ''),
                        is_visible=field_data.get('is_visible', True),
                        display_order=field_data.get('display_order', 0),
                        field_type=field_data.get('field_type', 'text'),
                        text_alignment=field_data.get('text_alignment', 'natural'),
                        date_style=field_data.get('date_style') or None,
                        time_style=field_data.get('time_style') or None,
                        number_style=field_data.get('number_style') or None,
                        currency_code=field_data.get('currency_code') or None
                    )
                    db.session.add(field)

        # Process back fields
        if 'back_fields' in data:
            for field_data in data['back_fields']:
                field = WalletBackField.query.filter_by(
                    pass_type_id=pass_type.id,
                    field_key=field_data['field_key']
                ).first()

                if field:
                    field.label = field_data.get('label', field.label)
                    field.value = field_data.get('value', field.value)
                    field.is_visible = field_data.get('is_visible', field.is_visible)
                    field.display_order = field_data.get('display_order', field.display_order)
                else:
                    field = WalletBackField(
                        pass_type_id=pass_type.id,
                        field_key=field_data['field_key'],
                        label=field_data.get('label', field_data['field_key'].upper()),
                        value=field_data.get('value', ''),
                        is_visible=field_data.get('is_visible', True),
                        display_order=field_data.get('display_order', 0)
                    )
                    db.session.add(field)

        db.session.commit()

        # Send push updates to all existing passes of this type
        push_sent = False
        push_result = None
        try:
            from app.wallet_pass.services.pass_service import pass_service
            push_result = pass_service.update_pass_type_design(pass_type.id)
            push_sent = True
            logger.info(f"Pushed field update to passes: {push_result}")
        except Exception as push_err:
            logger.warning(f"Failed to push field update: {push_err}")

        return jsonify({
            'success': True,
            'message': 'Fields updated',
            'push_sent': push_sent,
            'push_result': push_result
        })

    except Exception as e:
        logger.error(f"Error saving fields: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@pass_studio_bp.route('/<pass_type_code>/fields/<field_key>', methods=['DELETE'])
@login_required
@role_required(['Global Admin'])
def delete_field(pass_type_code, field_key):
    """Delete a field"""
    try:
        pass_type = WalletPassType.get_by_code(pass_type_code)
        if not pass_type:
            return jsonify({'success': False, 'error': 'Pass type not found'}), 404

        # Try front field first
        field = WalletPassFieldConfig.query.filter_by(
            pass_type_id=pass_type.id,
            field_key=field_key
        ).first()

        if not field:
            # Try back field
            field = WalletBackField.query.filter_by(
                pass_type_id=pass_type.id,
                field_key=field_key
            ).first()

        if not field:
            return jsonify({'success': False, 'error': 'Field not found'}), 404

        db.session.delete(field)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Field deleted'})

    except Exception as e:
        logger.error(f"Error deleting field: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# LOCATION MANAGEMENT
# =============================================================================

@pass_studio_bp.route('/<pass_type_code>/locations', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_locations(pass_type_code):
    """Get locations for a pass type"""
    try:
        locations = WalletLocation.query.filter(
            db.or_(
                WalletLocation.applies_to == 'all',
                WalletLocation.applies_to == pass_type_code
            )
        ).order_by(WalletLocation.display_order).all()

        return jsonify({
            'success': True,
            'locations': [loc.to_dict() for loc in locations],
            'count': len([l for l in locations if l.is_active]),
            'max': 10
        })

    except Exception as e:
        logger.error(f"Error getting locations: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@pass_studio_bp.route('/<pass_type_code>/locations', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def add_location(pass_type_code):
    """Add a new location"""
    try:
        data = request.get_json()

        # Check location limit
        active_count = WalletLocation.query.filter(
            WalletLocation.is_active == True,
            db.or_(
                WalletLocation.applies_to == 'all',
                WalletLocation.applies_to == pass_type_code
            )
        ).count()

        if active_count >= 10:
            return jsonify({
                'success': False,
                'error': 'Maximum of 10 locations allowed for Apple Wallet'
            }), 400

        location = WalletLocation(
            name=data['name'],
            latitude=data['latitude'],
            longitude=data['longitude'],
            relevant_text=data.get('relevant_text', data['name']),
            address=data.get('address'),
            city=data.get('city'),
            state=data.get('state'),
            applies_to=data.get('applies_to', pass_type_code),
            location_type=data.get('location_type', 'partner_bar'),
            is_active=True,
            display_order=data.get('display_order', 0)
        )

        db.session.add(location)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Location added',
            'location': location.to_dict()
        })

    except Exception as e:
        logger.error(f"Error adding location: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@pass_studio_bp.route('/<pass_type_code>/locations/<int:location_id>', methods=['PUT'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def update_location(pass_type_code, location_id):
    """Update a location"""
    try:
        location = WalletLocation.query.get_or_404(location_id)
        data = request.get_json()

        location.name = data.get('name', location.name)
        location.latitude = data.get('latitude', location.latitude)
        location.longitude = data.get('longitude', location.longitude)
        location.relevant_text = data.get('relevant_text', location.relevant_text)
        location.address = data.get('address', location.address)
        location.city = data.get('city', location.city)
        location.state = data.get('state', location.state)
        location.applies_to = data.get('applies_to', location.applies_to)
        location.location_type = data.get('location_type', location.location_type)
        location.is_active = data.get('is_active', location.is_active)
        location.display_order = data.get('display_order', location.display_order)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Location updated',
            'location': location.to_dict()
        })

    except Exception as e:
        logger.error(f"Error updating location: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@pass_studio_bp.route('/<pass_type_code>/locations/<int:location_id>', methods=['DELETE'])
@login_required
@role_required(['Global Admin'])
def delete_location(pass_type_code, location_id):
    """Delete a location"""
    try:
        location = WalletLocation.query.get_or_404(location_id)
        db.session.delete(location)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Location deleted'})

    except Exception as e:
        logger.error(f"Error deleting location: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# SPONSOR MANAGEMENT
# =============================================================================

@pass_studio_bp.route('/<pass_type_code>/sponsors', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_sponsors(pass_type_code):
    """Get sponsors for a pass type"""
    try:
        sponsors = WalletSponsor.query.filter(
            db.or_(
                WalletSponsor.applies_to == 'all',
                WalletSponsor.applies_to == pass_type_code
            )
        ).order_by(WalletSponsor.display_order).all()

        return jsonify({
            'success': True,
            'sponsors': [s.to_dict() for s in sponsors]
        })

    except Exception as e:
        logger.error(f"Error getting sponsors: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@pass_studio_bp.route('/<pass_type_code>/sponsors', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def add_sponsor(pass_type_code):
    """Add a new sponsor"""
    try:
        data = request.get_json()

        sponsor = WalletSponsor(
            name=data['name'],
            display_name=data.get('display_name', data['name']),
            description=data.get('description'),
            website_url=data.get('website_url'),
            applies_to=data.get('applies_to', pass_type_code),
            display_location=data.get('display_location', 'back'),
            sponsor_type=data.get('sponsor_type', 'partner'),
            is_active=True,
            display_order=data.get('display_order', 0)
        )

        db.session.add(sponsor)
        db.session.commit()

        # If address with coordinates provided, optionally create location
        if data.get('create_location') and data.get('latitude') and data.get('longitude'):
            location = WalletLocation(
                name=sponsor.name,
                latitude=data['latitude'],
                longitude=data['longitude'],
                relevant_text=sponsor.display_name,
                address=data.get('address'),
                city=data.get('city'),
                state=data.get('state'),
                applies_to=sponsor.applies_to,
                location_type='venue' if sponsor.sponsor_type == 'venue' else 'partner_bar',
                is_active=True
            )
            db.session.add(location)
            db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Sponsor added',
            'sponsor': sponsor.to_dict()
        })

    except Exception as e:
        logger.error(f"Error adding sponsor: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@pass_studio_bp.route('/<pass_type_code>/sponsors/<int:sponsor_id>', methods=['PUT'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def update_sponsor(pass_type_code, sponsor_id):
    """Update a sponsor"""
    try:
        sponsor = WalletSponsor.query.get_or_404(sponsor_id)
        data = request.get_json()

        sponsor.name = data.get('name', sponsor.name)
        sponsor.display_name = data.get('display_name', sponsor.display_name)
        sponsor.description = data.get('description', sponsor.description)
        sponsor.website_url = data.get('website_url', sponsor.website_url)
        sponsor.applies_to = data.get('applies_to', sponsor.applies_to)
        sponsor.display_location = data.get('display_location', sponsor.display_location)
        sponsor.sponsor_type = data.get('sponsor_type', sponsor.sponsor_type)
        sponsor.is_active = data.get('is_active', sponsor.is_active)
        sponsor.display_order = data.get('display_order', sponsor.display_order)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Sponsor updated',
            'sponsor': sponsor.to_dict()
        })

    except Exception as e:
        logger.error(f"Error updating sponsor: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@pass_studio_bp.route('/<pass_type_code>/sponsors/<int:sponsor_id>', methods=['DELETE'])
@login_required
@role_required(['Global Admin'])
def delete_sponsor(pass_type_code, sponsor_id):
    """Delete a sponsor"""
    try:
        sponsor = WalletSponsor.query.get_or_404(sponsor_id)
        db.session.delete(sponsor)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Sponsor deleted'})

    except Exception as e:
        logger.error(f"Error deleting sponsor: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# PREVIEW API
# =============================================================================

@pass_studio_bp.route('/<pass_type_code>/preview', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_preview_data(pass_type_code):
    """Get preview data for live pass preview"""
    try:
        pass_type = WalletPassType.get_by_code(pass_type_code)
        if not pass_type:
            return jsonify({'success': False, 'error': 'Pass type not found'}), 404

        # Get field configurations
        front_fields = WalletPassFieldConfig.query.filter(
            WalletPassFieldConfig.pass_type_id == pass_type.id,
            WalletPassFieldConfig.is_visible == True,
            WalletPassFieldConfig.field_location.in_(['primary', 'secondary', 'auxiliary', 'header'])
        ).order_by(WalletPassFieldConfig.display_order).all()

        back_fields = WalletBackField.query.filter_by(
            pass_type_id=pass_type.id,
            is_visible=True
        ).order_by(WalletBackField.display_order).all()

        # Group front fields by location
        fields_by_location = {
            'primary': [],
            'secondary': [],
            'auxiliary': [],
            'header': []
        }

        for field in front_fields:
            if field.field_location in fields_by_location:
                fields_by_location[field.field_location].append({
                    'key': field.field_key,
                    'label': field.label,
                    'value_template': field.value_template
                })

        # Sample data for preview
        if pass_type_code == 'ecs_membership':
            sample_data = {
                'member_name': 'Jane Smith',
                'validity': '2025',
                'member_since': '2019',
                'subgroup': 'Gorilla FC',
                'barcode_data': 'ECSFC-ECS-ABC123DEF456',
                'serial_number': 'abc123-def456-789'
            }
        else:
            sample_data = {
                'member_name': 'John Doe',
                'team_name': 'FC Placeholder',
                'validity': 'Spring 2025',
                'barcode_data': 'ECSFC-PUB-XYZ789ABC123',
                'serial_number': 'xyz789-abc123-456'
            }

        # Get assets with URLs
        assets = WalletAsset.get_assets_by_pass_type(pass_type.id)
        assets_data = {}
        for asset in assets:
            assets_data[asset.asset_type] = {
                'id': asset.id,
                'url': url_for('wallet_config.get_asset', asset_id=asset.id),
                'dimensions': ASSET_TYPES.get(asset.asset_type, {}).get('dimensions', 'unknown')
            }

        return jsonify({
            'success': True,
            'pass_type': {
                'code': pass_type.code,
                'name': pass_type.name,
                'background_color': pass_type.background_color,
                'foreground_color': pass_type.foreground_color,
                'label_color': pass_type.label_color,
                'logo_text': pass_type.logo_text,
                'google_hero_image_url': pass_type.google_hero_image_url,
                'google_logo_url': pass_type.google_logo_url
            },
            'fields': fields_by_location,
            'back_fields': [{'key': f.field_key, 'label': f.label, 'value': f.value} for f in back_fields],
            'sample_data': sample_data,
            'assets': assets_data
        })

    except Exception as e:
        logger.error(f"Error getting preview data: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# SUBGROUP MANAGEMENT (ECS ONLY)
# =============================================================================

@pass_studio_bp.route('/ecs_membership/subgroups', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_subgroups():
    """Get all subgroups"""
    try:
        subgroups = WalletSubgroup.query.order_by(WalletSubgroup.display_order).all()
        return jsonify({
            'success': True,
            'subgroups': [s.to_dict() for s in subgroups]
        })
    except Exception as e:
        logger.error(f"Error getting subgroups: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@pass_studio_bp.route('/ecs_membership/subgroups', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def add_subgroup():
    """Add a new subgroup"""
    try:
        data = request.get_json()

        # Generate code from name if not provided
        code = data.get('code') or data['name'].lower().replace(' ', '_')

        # Check for duplicate code
        existing = WalletSubgroup.query.filter_by(code=code).first()
        if existing:
            return jsonify({
                'success': False,
                'error': f'Subgroup with code "{code}" already exists'
            }), 400

        subgroup = WalletSubgroup(
            code=code,
            name=data['name'],
            description=data.get('description'),
            is_active=data.get('is_active', True),
            display_order=data.get('display_order', 0)
        )

        db.session.add(subgroup)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Subgroup added',
            'subgroup': subgroup.to_dict()
        })

    except Exception as e:
        logger.error(f"Error adding subgroup: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@pass_studio_bp.route('/ecs_membership/subgroups/<int:subgroup_id>', methods=['DELETE'])
@login_required
@role_required(['Global Admin'])
def delete_subgroup(subgroup_id):
    """Delete a subgroup"""
    try:
        subgroup = WalletSubgroup.query.get_or_404(subgroup_id)
        db.session.delete(subgroup)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Subgroup deleted'})

    except Exception as e:
        logger.error(f"Error deleting subgroup: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# ASSET UPLOAD API (with cropping)
# =============================================================================

@pass_studio_bp.route('/<pass_type_code>/assets/upload', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def upload_asset_cropped(pass_type_code):
    """
    Upload a cropped asset image (base64 encoded).

    Expects JSON body with:
    - asset_type: Type of asset (icon, logo, strip, thumbnail, background)
    - cropped_image: Base64 encoded PNG image data

    Returns the saved asset info including URL for preview.
    """
    try:
        pass_type = WalletPassType.get_by_code(pass_type_code)
        if not pass_type:
            return jsonify({'success': False, 'error': 'Pass type not found'}), 404

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        asset_type = data.get('asset_type')
        cropped_image = data.get('cropped_image')

        if not asset_type:
            return jsonify({'success': False, 'error': 'Missing asset_type'}), 400

        if not cropped_image:
            return jsonify({'success': False, 'error': 'Missing cropped_image data'}), 400

        if asset_type not in ASSET_TYPES:
            return jsonify({'success': False, 'error': f'Invalid asset type: {asset_type}'}), 400

        # Process and save the cropped image
        asset = asset_service.process_cropped_asset(
            base64_data=cropped_image,
            asset_type=asset_type,
            pass_type_id=pass_type.id
        )

        # Push update to all existing passes of this type
        push_sent = False
        try:
            from app.wallet_pass.services.pass_service import pass_service
            push_result = pass_service.update_pass_type_design(pass_type.id)
            push_sent = True
            logger.info(f"Pushed asset update to passes: {push_result}")
        except Exception as push_err:
            logger.warning(f"Failed to push asset update: {push_err}")

        return jsonify({
            'success': True,
            'message': f'{ASSET_TYPES[asset_type]["description"]} uploaded successfully',
            'push_sent': push_sent,
            'asset': {
                'id': asset.id,
                'asset_type': asset.asset_type,
                'dimensions': ASSET_TYPES[asset_type]['dimensions'],
                'url': url_for('wallet_config.get_asset', asset_id=asset.id)
            }
        })

    except ValueError as e:
        logger.warning(f"Asset upload validation error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error uploading cropped asset: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to upload asset'}), 500


@pass_studio_bp.route('/<pass_type_code>/assets', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_assets(pass_type_code):
    """Get all assets for a pass type"""
    try:
        pass_type = WalletPassType.get_by_code(pass_type_code)
        if not pass_type:
            return jsonify({'success': False, 'error': 'Pass type not found'}), 404

        assets = WalletAsset.get_assets_by_pass_type(pass_type.id)
        assets_data = {}

        for asset in assets:
            assets_data[asset.asset_type] = {
                'id': asset.id,
                'asset_type': asset.asset_type,
                'url': url_for('wallet_config.get_asset', asset_id=asset.id),
                'dimensions': ASSET_TYPES.get(asset.asset_type, {}).get('dimensions', 'unknown'),
                'description': ASSET_TYPES.get(asset.asset_type, {}).get('description', asset.asset_type),
                'required': ASSET_TYPES.get(asset.asset_type, {}).get('required', False)
            }

        # Also include asset types that haven't been uploaded yet
        all_asset_types = {}
        for asset_type, config in ASSET_TYPES.items():
            all_asset_types[asset_type] = {
                'asset_type': asset_type,
                'dimensions': config['dimensions'],
                'description': config['description'],
                'required': config.get('required', False),
                'uploaded': asset_type in assets_data,
                **assets_data.get(asset_type, {})
            }

        return jsonify({
            'success': True,
            'assets': assets_data,
            'all_asset_types': all_asset_types
        })

    except Exception as e:
        logger.error(f"Error getting assets: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@pass_studio_bp.route('/<pass_type_code>/assets/<asset_type>', methods=['DELETE'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def delete_asset(pass_type_code, asset_type):
    """Delete an asset"""
    try:
        pass_type = WalletPassType.get_by_code(pass_type_code)
        if not pass_type:
            return jsonify({'success': False, 'error': 'Pass type not found'}), 404

        asset = WalletAsset.get_by_type_and_pass_type(asset_type, pass_type.id)
        if not asset:
            return jsonify({'success': False, 'error': 'Asset not found'}), 404

        asset_service.delete_asset(asset.id)

        return jsonify({
            'success': True,
            'message': f'{asset_type} deleted successfully'
        })

    except Exception as e:
        logger.error(f"Error deleting asset: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# GOOGLE WALLET SETTINGS API
# =============================================================================

@pass_studio_bp.route('/<pass_type_code>/google-settings', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def save_google_settings(pass_type_code):
    """
    Save Google Wallet specific settings (hero image URL, logo URL).

    Expects JSON body with optional fields:
    - google_hero_image_url: URL to hero/banner image
    - google_logo_url: URL to logo image
    """
    try:
        pass_type = WalletPassType.get_by_code(pass_type_code)
        if not pass_type:
            return jsonify({'success': False, 'error': 'Pass type not found'}), 404

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        # Update Google settings if provided
        if 'google_hero_image_url' in data:
            pass_type.google_hero_image_url = data['google_hero_image_url'] or None

        if 'google_logo_url' in data:
            pass_type.google_logo_url = data['google_logo_url'] or None

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Google Wallet settings updated',
            'google_hero_image_url': pass_type.google_hero_image_url,
            'google_logo_url': pass_type.google_logo_url
        })

    except Exception as e:
        logger.error(f"Error saving Google settings: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@pass_studio_bp.route('/<pass_type_code>/google-settings', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_google_settings(pass_type_code):
    """Get Google Wallet settings for a pass type"""
    try:
        pass_type = WalletPassType.get_by_code(pass_type_code)
        if not pass_type:
            return jsonify({'success': False, 'error': 'Pass type not found'}), 404

        return jsonify({
            'success': True,
            'google_hero_image_url': pass_type.google_hero_image_url,
            'google_logo_url': pass_type.google_logo_url
        })

    except Exception as e:
        logger.error(f"Error getting Google settings: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# INITIALIZATION ENDPOINTS
# =============================================================================

@pass_studio_bp.route('/init-defaults', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def initialize_defaults():
    """
    Initialize default field configurations from the UI.

    This replaces the need to run CLI commands manually.
    Creates default fields, locations, and subgroups if they don't exist.
    """
    try:
        from app.models.wallet_config import initialize_wallet_config_defaults

        initialize_wallet_config_defaults()

        # Count what was created
        field_count = WalletPassFieldConfig.query.count()
        back_field_count = WalletBackField.query.count()
        location_count = WalletLocation.query.count()

        return jsonify({
            'success': True,
            'message': 'Default configurations initialized',
            'counts': {
                'fields': field_count,
                'back_fields': back_field_count,
                'locations': location_count
            }
        })

    except Exception as e:
        logger.error(f"Error initializing defaults: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@pass_studio_bp.route('/config-status', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_configuration_status():
    """
    Get the current configuration status for all pass types.

    Returns counts of configured fields, assets, etc. to help
    the UI determine if initialization is needed.
    """
    try:
        ecs_type = WalletPassType.get_ecs_membership()
        pub_type = WalletPassType.get_pub_league()

        status = {
            'ecs_membership': {
                'exists': ecs_type is not None,
                'id': ecs_type.id if ecs_type else None,
                'fields': 0,
                'back_fields': 0,
                'assets': 0
            },
            'pub_league': {
                'exists': pub_type is not None,
                'id': pub_type.id if pub_type else None,
                'fields': 0,
                'back_fields': 0,
                'assets': 0
            },
            'locations': WalletLocation.query.count(),
            'needs_initialization': False
        }

        if ecs_type:
            status['ecs_membership']['fields'] = WalletPassFieldConfig.query.filter_by(
                pass_type_id=ecs_type.id
            ).count()
            status['ecs_membership']['back_fields'] = WalletBackField.query.filter_by(
                pass_type_id=ecs_type.id
            ).count()
            status['ecs_membership']['assets'] = WalletAsset.query.filter_by(
                pass_type_id=ecs_type.id
            ).count()

        if pub_type:
            status['pub_league']['fields'] = WalletPassFieldConfig.query.filter_by(
                pass_type_id=pub_type.id
            ).count()
            status['pub_league']['back_fields'] = WalletBackField.query.filter_by(
                pass_type_id=pub_type.id
            ).count()
            status['pub_league']['assets'] = WalletAsset.query.filter_by(
                pass_type_id=pub_type.id
            ).count()

        # Check if initialization is needed
        if ecs_type and status['ecs_membership']['fields'] == 0:
            status['needs_initialization'] = True
        if pub_type and status['pub_league']['fields'] == 0:
            status['needs_initialization'] = True

        return jsonify({
            'success': True,
            'status': status
        })

    except Exception as e:
        logger.error(f"Error getting config status: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
