"""
Message Configuration Routes

Admin interface for managing configurable onboarding messages.
Allows editing of welcome messages, league responses, and other automated messages.
"""

import logging
from datetime import datetime

from flask import Blueprint, request, jsonify, render_template, flash, redirect, url_for
from sqlalchemy.exc import SQLAlchemyError

from app.models import MessageCategory, MessageTemplate, db
from app.utils.db_utils import transactional
from app.decorators import role_required
from app.utils.user_helpers import safe_current_user
from app import csrf

logger = logging.getLogger(__name__)

# Create blueprint for message configuration routes
message_config = Blueprint('message_config', __name__, url_prefix='/admin/messages')


@message_config.route('/', methods=['GET'])
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def list_categories():
    """List all message categories and recent announcements."""
    try:
        from app.models import Announcement
        categories = MessageCategory.query.order_by(MessageCategory.name).all()
        # Get recent announcements for the dashboard
        announcements = Announcement.query.order_by(Announcement.created_at.desc()).limit(5).all()
        return render_template('admin/message_categories_flowbite.html',
                             categories=categories,
                             announcements=announcements)
    except Exception as e:
        logger.error(f"Error listing message categories: {e}")
        flash(f'Error loading message categories: {str(e)}. You may need to run the initialization script.', 'error')
        return redirect(url_for('admin.admin_dashboard'))


@message_config.route('/category/<int:category_id>', methods=['GET'])
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def view_category(category_id: int):
    """View all templates in a category."""
    try:
        category = MessageCategory.query.get_or_404(category_id)
        templates = MessageTemplate.query.filter_by(category_id=category_id).order_by(MessageTemplate.key).all()
        
        return render_template('admin/message_templates_flowbite.html',
                             category=category,
                             templates=templates)
    except Exception as e:
        logger.error(f"Error viewing category {category_id}: {e}")
        flash('Error loading message templates', 'error')
        return redirect(url_for('admin.message_config.list_categories'))


@message_config.route('/template/<int:template_id>/edit', methods=['GET', 'POST'])
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def edit_template(template_id: int):
    """Edit a message template."""
    try:
        template = MessageTemplate.query.get_or_404(template_id)
        
        if request.method == 'POST':
            # Update template
            template.name = request.form.get('name', template.name)
            template.description = request.form.get('description', template.description)
            template.message_content = request.form.get('message_content', template.message_content)
            template.is_active = 'is_active' in request.form
            template.updated_by = safe_current_user.id
            template.updated_at = datetime.utcnow()
            
            db.session.add(template)
            db.session.commit()
            
            flash(f'Template "{template.name}" updated successfully', 'success')
            return redirect(url_for('admin.message_config.view_category', category_id=template.category_id))
        
        return render_template('admin/edit_message_template_flowbite.html', template=template)
        
    except Exception as e:
        logger.error(f"Error editing template {template_id}: {e}")
        flash('Error updating message template', 'error')
        return redirect(url_for('admin.message_config.list_categories'))


@message_config.route('/api/template/<int:template_id>', methods=['GET'])
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def get_template_api(template_id: int):
    """API endpoint to get template data."""
    try:
        template = MessageTemplate.query.get_or_404(template_id)
        
        return jsonify({
            'success': True,
            'id': template.id,
            'key': template.key,
            'name': template.name,
            'description': template.description,
            'message_content': template.message_content,
            'variables': template.variables,
            'is_active': template.is_active,
            'category_name': template.category.name
        })
        
    except Exception as e:
        logger.error(f"Error getting template {template_id}: {e}")
        return jsonify({'success': False, 'error': 'Template not found'}), 404


@message_config.route('/api/template/<int:template_id>', methods=['POST', 'PUT'])
@csrf.exempt
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def update_template_api(template_id: int):
    """API endpoint to update template content."""
    try:
        template = MessageTemplate.query.get_or_404(template_id)
        
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
            # Convert checkbox value to boolean
            if 'is_active' in data:
                data['is_active'] = data['is_active'] == 'on'
        
        if 'message_content' in data:
            template.message_content = data['message_content']
        if 'name' in data:
            template.name = data['name']
        if 'description' in data:
            template.description = data['description']
        if 'is_active' in data:
            template.is_active = bool(data['is_active'])
            
        template.updated_by = safe_current_user.id
        template.updated_at = datetime.utcnow()
        
        db.session.add(template)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Template "{template.name}" updated successfully'
        })
        
    except Exception as e:
        logger.error(f"Error updating template {template_id}: {e}")
        return jsonify({'success': False, 'error': 'Failed to update template'}), 500


@message_config.route('/api/preview/<int:template_id>', methods=['POST'])
@csrf.exempt
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def preview_template(template_id: int):
    """Preview a template with sample variables."""
    try:
        template = MessageTemplate.query.get_or_404(template_id)
        data = request.get_json()
        
        # Get sample variables or use provided ones
        variables = data.get('variables', {})
        
        # Add default sample variables if not provided
        sample_vars = {
            'username': variables.get('username', 'SampleUser'),
            'league_display_name': variables.get('league_display_name', 'Pub League Premier'),
            'league_welcome_message': variables.get('league_welcome_message', 'Get ready for competitive matches!'),
            'league_contact_info': variables.get('league_contact_info', 'Contact our Premier coordinators for more info.')
        }
        
        # Format the message with variables
        formatted_message = template.format_message(**sample_vars)
        
        return jsonify({
            'preview': formatted_message,
            'variables_used': sample_vars
        })
        
    except Exception as e:
        logger.error(f"Error previewing template {template_id}: {e}")
        return jsonify({'error': 'Failed to preview template'}), 500


@message_config.route('/api/template/create', methods=['POST'])
@csrf.exempt
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def create_template_api():
    """API endpoint to create a new template."""
    try:
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
            # Convert checkbox value to boolean
            if 'is_active' in data:
                data['is_active'] = data['is_active'] == 'on'
        
        # Validate required fields
        required_fields = ['category_id', 'name', 'key', 'message_content']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        # Check if template key already exists
        existing_template = MessageTemplate.query.filter_by(key=data['key']).first()
        if existing_template:
            return jsonify({'success': False, 'error': 'Template key already exists'}), 400
        
        # Create new template
        template = MessageTemplate(
            category_id=int(data['category_id']),
            key=data['key'],
            name=data['name'],
            description=data.get('description', ''),
            message_content=data['message_content'],
            variables=data.get('variables', []),
            is_active=bool(data.get('is_active', True)),
            created_by=safe_current_user.id,
            updated_by=safe_current_user.id
        )
        
        db.session.add(template)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Template "{template.name}" created successfully',
            'template_id': template.id
        })
        
    except Exception as e:
        logger.error(f"Error creating template: {e}")
        return jsonify({'success': False, 'error': 'Failed to create template'}), 500


@message_config.route('/api/template/<int:template_id>/toggle', methods=['POST'])
@csrf.exempt
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def toggle_template_status(template_id: int):
    """API endpoint to toggle template active status."""
    try:
        template = MessageTemplate.query.get_or_404(template_id)
        
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
            is_active = data.get('is_active', False)
        else:
            data = request.form.to_dict()
            is_active = data.get('is_active', 'false').lower() in ['true', '1', 'on']
        
        template.is_active = bool(is_active)
        template.updated_by = safe_current_user.id
        template.updated_at = datetime.utcnow()
        
        db.session.add(template)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Template "{template.name}" {"activated" if is_active else "deactivated"}',
            'is_active': template.is_active
        })
        
    except Exception as e:
        logger.error(f"Error toggling template {template_id} status: {e}")
        return jsonify({'success': False, 'error': 'Failed to toggle template status'}), 500


@message_config.route('/api/category/<int:category_id>', methods=['POST'])
@csrf.exempt
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def update_category_api(category_id: int):
    """API endpoint to update category details."""
    try:
        category = MessageCategory.query.get_or_404(category_id)
        
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        if 'name' in data:
            category.name = data['name']
        if 'description' in data:
            category.description = data['description']
            
        category.updated_at = datetime.utcnow()
        
        db.session.add(category)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Category "{category.name}" updated successfully'
        })
        
    except Exception as e:
        logger.error(f"Error updating category {category_id}: {e}")
        return jsonify({'success': False, 'error': 'Failed to update category'}), 500