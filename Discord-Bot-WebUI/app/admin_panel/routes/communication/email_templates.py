# app/admin_panel/routes/communication/email_templates.py

"""
Email Template Routes

CRUD operations for reusable email wrapper templates.
"""

import logging
from flask import render_template, request, jsonify
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models import EmailTemplate, EmailCampaign
from app.decorators import role_required
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/communication/email-templates')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def email_templates_list():
    """Template management list page."""
    templates = EmailTemplate.query.filter_by(is_deleted=False).order_by(
        EmailTemplate.is_default.desc(), EmailTemplate.name
    ).all()

    return render_template(
        'admin_panel/communication/email_templates_flowbite.html',
        templates=templates,
        page_title='Email Templates',
    )


@admin_panel_bp.route('/communication/email-templates/new')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def email_template_new():
    """Create new template page."""
    return render_template(
        'admin_panel/communication/email_template_edit_flowbite.html',
        template=None,
        page_title='New Email Template',
    )


@admin_panel_bp.route('/communication/email-templates/<int:template_id>/edit')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def email_template_edit(template_id):
    """Edit template page."""
    template = EmailTemplate.query.get_or_404(template_id)
    if template.is_deleted:
        return jsonify({'success': False, 'error': 'Template has been deleted'}), 404

    return render_template(
        'admin_panel/communication/email_template_edit_flowbite.html',
        template=template,
        page_title=f'Edit Template: {template.name}',
    )


# ---------------------------------------------------------------------------
# JSON API endpoints
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/api/email-templates', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def email_template_create():
    """Create a new email template (JSON API)."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        name = (data.get('name') or '').strip()
        html_content = (data.get('html_content') or '').strip()

        if not name or not html_content:
            return jsonify({'success': False, 'error': 'Name and HTML content are required'}), 400

        template = EmailTemplate(
            name=name,
            description=(data.get('description') or '').strip() or None,
            html_content=html_content,
            is_default=False,
            created_by_id=current_user.id,
        )
        db.session.add(template)
        db.session.flush()

        return jsonify({
            'success': True,
            'template': template.to_dict(),
            'message': 'Template created',
        })

    except Exception as e:
        logger.error(f"Error creating email template: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/email-templates/<int:template_id>', methods=['PUT'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def email_template_update(template_id):
    """Update an email template (JSON API)."""
    try:
        template = EmailTemplate.query.get(template_id)
        if not template or template.is_deleted:
            return jsonify({'success': False, 'error': 'Template not found'}), 404

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        name = (data.get('name') or '').strip()
        html_content = (data.get('html_content') or '').strip()

        if not name or not html_content:
            return jsonify({'success': False, 'error': 'Name and HTML content are required'}), 400

        template.name = name
        template.description = (data.get('description') or '').strip() or None
        template.html_content = html_content

        return jsonify({
            'success': True,
            'template': template.to_dict(),
            'message': 'Template updated',
        })

    except Exception as e:
        logger.error(f"Error updating email template: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/email-templates/<int:template_id>', methods=['DELETE'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def email_template_delete(template_id):
    """Delete an email template (JSON API). Soft-deletes if campaigns reference it."""
    try:
        template = EmailTemplate.query.get(template_id)
        if not template or template.is_deleted:
            return jsonify({'success': False, 'error': 'Template not found'}), 404

        # Check if any campaigns reference this template
        campaign_count = EmailCampaign.query.filter_by(template_id=template_id).count()

        if campaign_count > 0:
            # Soft delete - campaigns still reference it
            template.is_deleted = True
            return jsonify({
                'success': True,
                'message': f'Template hidden (still used by {campaign_count} campaign(s))',
                'soft_deleted': True,
            })
        else:
            # Hard delete - no references
            db.session.delete(template)
            return jsonify({
                'success': True,
                'message': 'Template deleted',
                'soft_deleted': False,
            })

    except Exception as e:
        logger.error(f"Error deleting email template: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/email-templates/<int:template_id>/set-default', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def email_template_set_default(template_id):
    """Set a template as the default (JSON API)."""
    try:
        template = EmailTemplate.query.get(template_id)
        if not template or template.is_deleted:
            return jsonify({'success': False, 'error': 'Template not found'}), 404

        # Unset all defaults
        EmailTemplate.query.filter_by(is_default=True).update({'is_default': False})

        # Set this one
        template.is_default = True

        return jsonify({
            'success': True,
            'message': f'"{template.name}" is now the default template',
        })

    except Exception as e:
        logger.error(f"Error setting default template: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/email-templates/<int:template_id>/duplicate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def email_template_duplicate(template_id):
    """Duplicate a template (JSON API)."""
    try:
        original = EmailTemplate.query.get(template_id)
        if not original:
            return jsonify({'success': False, 'error': 'Template not found'}), 404

        copy = EmailTemplate(
            name=f'{original.name} (Copy)',
            description=original.description,
            html_content=original.html_content,
            is_default=False,
            created_by_id=current_user.id,
        )
        db.session.add(copy)
        db.session.flush()

        return jsonify({
            'success': True,
            'template': copy.to_dict(),
            'message': 'Template duplicated',
        })

    except Exception as e:
        logger.error(f"Error duplicating email template: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/email-templates/preview', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def email_template_preview():
    """Render a template preview with sample content (JSON API)."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        html_content = (data.get('html_content') or '').strip()
        if not html_content:
            return jsonify({'success': False, 'error': 'HTML content is required'}), 400

        sample_content = (
            '<div style="border: 2px dashed #1a472a; border-radius: 8px; padding: 24px; '
            'text-align: center; color: #1a472a; background-color: #f0faf4;">'
            '<p style="font-size: 16px; font-weight: bold; margin: 0 0 8px 0;">'
            'Your email content will appear here</p>'
            '<p style="font-size: 13px; margin: 0; opacity: 0.7;">'
            'This is a preview placeholder for the {content} token</p>'
            '</div>'
        )

        rendered = html_content.replace('{content}', sample_content)
        rendered = rendered.replace('{subject}', 'Sample Subject')

        return jsonify({
            'success': True,
            'html': rendered,
        })

    except Exception as e:
        logger.error(f"Error previewing template: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/email-templates/list')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def email_templates_api_list():
    """JSON list of active templates for compose dropdown."""
    try:
        templates = EmailTemplate.query.filter_by(is_deleted=False).order_by(
            EmailTemplate.is_default.desc(), EmailTemplate.name
        ).all()

        return jsonify({
            'success': True,
            'templates': [
                {
                    'id': t.id,
                    'name': t.name,
                    'description': t.description,
                    'is_default': t.is_default,
                }
                for t in templates
            ],
        })

    except Exception as e:
        logger.error(f"Error listing templates: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
