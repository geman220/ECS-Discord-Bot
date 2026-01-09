# app/help.py

"""
Help Module

This module defines the endpoints for the help system in the application.
It includes routes for viewing help topics, searching for topics, and administrative
actions to create, edit, and delete help topics as well as upload images for help content.
Access to topics is controlled based on user roles, and Markdown content is converted to HTML for display.
"""

import os
import re
import markdown
from flask import Blueprint, render_template, request, redirect, url_for, current_app, jsonify, g, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.core import db
from app.models import Role, HelpTopic
from app.forms import HelpTopicForm
from app.decorators import role_required
from app.alert_helpers import show_success, show_error, show_warning, show_info
from app.utils.user_helpers import safe_current_user
import logging

logger = logging.getLogger(__name__)

# Define blueprint for the help system.
help_bp = Blueprint('help', __name__, template_folder='templates/help', static_folder='static/help')

def get_accessible_roles(user_role_names):
    """
    Get all roles accessible to the user based on hierarchical permissions.
    
    Hierarchy:
    - Global Admin: sees everything
    - Pub League Admin: sees all pub league content (coaches, players, subs)
    - Coaches: see their own content plus player content
    - Players: see their own content
    
    Parameters:
        user_role_names (list): List of role names the user has
        
    Returns:
        list: All role names the user can access content for
    """
    accessible_roles = set(user_role_names)
    
    # Global Admin sees everything
    if 'Global Admin' in user_role_names:
        accessible_roles.update([
            'Global Admin', 'Pub League Admin', 'Discord Admin',
            'ECS FC Coach', 'Pub League Coach',
            'pl-classic', 'pl-premier', 'pl-ecs-fc',
            'Classic Sub', 'Premier Sub', 'ECS FC Sub'
        ])
    
    # Pub League Admin sees all pub league related content
    if 'Pub League Admin' in user_role_names:
        accessible_roles.update([
            'Pub League Admin', 'ECS FC Coach', 'Pub League Coach',
            'pl-classic', 'pl-premier', 'pl-ecs-fc',
            'Classic Sub', 'Premier Sub', 'ECS FC Sub'
        ])
    
    # ECS FC Coach sees ECS FC player content
    if 'ECS FC Coach' in user_role_names:
        accessible_roles.update(['ECS FC Coach', 'pl-ecs-fc', 'ECS FC Sub'])
    
    # Pub League Coach sees pub league player content
    if 'Pub League Coach' in user_role_names:
        accessible_roles.update(['Pub League Coach', 'pl-classic', 'pl-premier', 'Classic Sub', 'Premier Sub'])
    
    return list(accessible_roles)

# Allowed file extensions for image uploads.
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    """
    Check if the file has an allowed extension.

    Parameters:
        filename (str): The name of the file.

    Returns:
        bool: True if the file extension is allowed, False otherwise.
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_discord_links(html_content):
    """
    Convert Discord channel references in markdown to styled non-clickable mentions.
    
    Patterns supported:
    - [[#channel-name]] -> styled Discord channel mention
    - <#channel-name> -> styled Discord channel mention
    
    Parameters:
        html_content (str): The HTML content to process
        
    Returns:
        str: HTML content with Discord channel references styled
    """
    # Pattern for [[#channel-name]] format
    pattern1 = r'\[\[#([\w-]+)\]\]'
    # Pattern for <#channel-name> format
    pattern2 = r'&lt;#([\w-]+)&gt;'
    
    # Discord-style channel mention (uses .discord-channel-mention CSS class)
    channel_style = '<span class="discord-channel-mention">#{}</span>'
    
    # Replace [[#channel-name]] format
    html_content = re.sub(pattern1, lambda m: channel_style.format(m.group(1)), html_content)
    
    # Replace <#channel-name> format
    html_content = re.sub(pattern2, lambda m: channel_style.format(m.group(1)), html_content)
    
    return html_content

@help_bp.route('/')
@login_required
def index():
    """
    Display the list of help topics accessible to the current user.

    Returns:
        Rendered template of the help topics index.
    """
    # Get topics allowed based on the current user's effective roles (considering impersonation)
    from app.role_impersonation import is_impersonation_active, get_effective_roles
    
    if is_impersonation_active():
        user_role_names = get_effective_roles()
    else:
        user_role_names = [role.name for role in safe_current_user.roles]
    
    # Get user's effective roles with hierarchical access
    accessible_role_names = get_accessible_roles(user_role_names)
    
    # Get topics that either have no roles assigned (public) or have roles accessible to user
    topics_with_roles = HelpTopic.query.join(HelpTopic.allowed_roles).filter(Role.name.in_(accessible_role_names)).all()
    topics_without_roles = g.db_session.query(HelpTopic).filter(~HelpTopic.allowed_roles.any()).all()
    topics = list(set(topics_with_roles + topics_without_roles))
    
    # Check if user can access admin dashboard
    if is_impersonation_active():
        can_access_admin = 'Global Admin' in user_role_names
    else:
        can_access_admin = 'Global Admin' in [role.name for role in safe_current_user.roles]
    
    return render_template('help/index_flowbite.html', topics=topics, title="Help Topics", can_access_admin=can_access_admin)

@help_bp.route('/<int:topic_id>')
@login_required
def view_topic(topic_id):
    """
    Display a specific help topic, converting its Markdown content to HTML.

    Parameters:
        topic_id (int): The ID of the help topic.

    Returns:
        Rendered template of the help topic view.
    """
    topic = g.db_session.query(HelpTopic).get(topic_id)
    if not topic:
        abort(404)
    allowed_role_names = [role.name for role in topic.allowed_roles]
    
    # Check effective roles (considering impersonation)
    from app.role_impersonation import is_impersonation_active, get_effective_roles
    
    if is_impersonation_active():
        user_role_names = get_effective_roles()
    else:
        user_role_names = [role.name for role in safe_current_user.roles]
    
    # Check if user has permission to view this topic
    # Allow access if topic has no roles (public) or user has hierarchical access to the roles
    accessible_role_names = get_accessible_roles(user_role_names)
    if allowed_role_names and not set(allowed_role_names) & set(accessible_role_names):
        show_error('You do not have permission to view this help topic.')
        return redirect(url_for('help.index'))
        
    # Convert Markdown to HTML with multiple extensions for better formatting
    html_content = markdown.markdown(
        topic.markdown_content, 
        extensions=[
            'fenced_code',           # Code blocks with syntax highlighting
            'tables',                # Table support
            'toc',                   # Table of contents with anchor links
            'attr_list',             # Add attributes to elements
            'def_list',              # Definition lists
            'footnotes',             # Footnote support
            'md_in_html',            # Markdown inside HTML
            'sane_lists',            # Better list handling
            'smarty',                # Smart quotes, dashes, ellipses
            'extra'                  # Abbreviations, attributes, etc.
        ],
        extension_configs={
            'toc': {
                'permalink': True,   # Add permalink anchors to headers
                'slugify': lambda value, separator: value.lower().replace(' & ', '--').replace(' ', '-').replace('&', '-'),
                'toc_depth': 6       # Include all header levels
            }
        }
    )
    
    # Process Discord channel links
    html_content = process_discord_links(html_content)
    
    return render_template('help/view_topic_flowbite.html', topic=topic, content=html_content, title=topic.title)

@help_bp.route('/search_topics', methods=['GET'])
@login_required
def search_topics():
    """
    Search help topics based on a query string and return results as JSON.

    Returns:
        JSON response containing a list of help topics matching the query.
    """
    query = request.args.get('query', '').strip()
    
    # Get topics allowed based on the current user's effective roles (considering impersonation)
    from app.role_impersonation import is_impersonation_active, get_effective_roles
    
    if is_impersonation_active():
        user_role_names = get_effective_roles()
    else:
        user_role_names = [role.name for role in safe_current_user.roles]
    
    # Get user's effective roles with hierarchical access
    accessible_role_names = get_accessible_roles(user_role_names)
    
    # Get topics that either have no roles assigned (public) or have roles accessible to user
    topics_with_roles_query = HelpTopic.query.join(HelpTopic.allowed_roles).filter(Role.name.in_(accessible_role_names))
    topics_without_roles_query = g.db_session.query(HelpTopic).filter(~HelpTopic.allowed_roles.any())
    
    if query:
        topics_with_roles_query = topics_with_roles_query.filter(HelpTopic.title.ilike(f"%{query}%"))
        topics_without_roles_query = topics_without_roles_query.filter(HelpTopic.title.ilike(f"%{query}%"))
    
    topics_with_roles = topics_with_roles_query.all()
    topics_without_roles = topics_without_roles_query.all()
    topics = list(set(topics_with_roles + topics_without_roles))
    topics_data = [{"id": topic.id, "title": topic.title} for topic in topics]
    return jsonify({"topics": topics_data})

# --- ADMIN ROUTES ---

@help_bp.route('/admin')
@login_required
@role_required(['Global Admin'])
def admin_help_topics():
    """
    Display all help topics for administrative management.

    Returns:
        Rendered template of the admin help topics list.
    """
    topics = g.db_session.query(HelpTopic).all()
    return render_template('help/admin/list_help_topics_flowbite.html', topics=topics, title="Admin - Help Topics")

@help_bp.route('/admin/new', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin'])
def new_help_topic():
    """
    Create a new help topic.

    Returns:
        Redirects to the admin help topics list upon successful creation,
        or renders the new help topic form.
    """
    form = HelpTopicForm()
    form.roles.choices = [(role.id, role.name) for role in g.db_session.query(Role).all()]
    if form.validate_on_submit():
        topic = HelpTopic(
            title=form.title.data,
            markdown_content=form.markdown_content.data
        )
        selected_roles = g.db_session.query(Role).filter(Role.id.in_(form.roles.data)).all()
        topic.allowed_roles = selected_roles
        g.db_session.add(topic)
        g.db_session.commit()
        show_success('Help topic created successfully!')
        return redirect(url_for('help.admin_help_topics'))
    return render_template('help/admin/new_help_topic_flowbite.html', form=form, title="Create New Help Topic")

@help_bp.route('/admin/edit/<int:topic_id>', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin'])
def edit_help_topic(topic_id):
    """
    Edit an existing help topic.

    Parameters:
        topic_id (int): The ID of the help topic to edit.

    Returns:
        Redirects to the admin help topics list upon successful update,
        or renders the edit form.
    """
    topic = g.db_session.query(HelpTopic).get(topic_id)
    if not topic:
        abort(404)
    form = HelpTopicForm(obj=topic)
    form.roles.choices = [(role.id, role.name) for role in g.db_session.query(Role).all()]
    if request.method == 'GET':
        form.roles.data = [role.id for role in topic.allowed_roles]
    if form.validate_on_submit():
        topic.title = form.title.data
        topic.markdown_content = form.markdown_content.data
        selected_roles = g.db_session.query(Role).filter(Role.id.in_(form.roles.data)).all()
        topic.allowed_roles = selected_roles
        g.db_session.commit()
        show_success('Help topic updated successfully!')
        return redirect(url_for('help.admin_help_topics'))
    return render_template('help/admin/edit_help_topic_flowbite.html', form=form, topic=topic, title="Edit Help Topic")

@help_bp.route('/admin/delete/<int:topic_id>', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def delete_help_topic(topic_id):
    """
    Delete a help topic.

    Parameters:
        topic_id (int): The ID of the help topic to delete.

    Returns:
        Redirects to the admin help topics list after deletion.
    """
    topic = g.db_session.query(HelpTopic).get(topic_id)
    if not topic:
        abort(404)
    g.db_session.delete(topic)
    g.db_session.commit()
    show_success('Help topic deleted successfully!')
    return redirect(url_for('help.admin_help_topics'))

@help_bp.route('/admin/upload_image', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def upload_image():
    """
    Handle image uploads for help topics.

    Returns:
        JSON response containing the URL of the uploaded image, or an error message.
    """
    if 'image' not in request.files:
        return jsonify({'error': 'No image part'}), 400
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        upload_folder = os.path.join(current_app.root_path, 'static', 'help_uploads')
        os.makedirs(upload_folder, exist_ok=True)
        file.save(os.path.join(upload_folder, filename))
        image_url = url_for('static', filename='help_uploads/' + filename)
        return jsonify({'url': image_url}), 200
    else:
        return jsonify({'error': 'File type not allowed'}), 400

@help_bp.route('/admin/bulk_upload', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin'])
def bulk_upload_help_topics():
    """
    Handle bulk upload of help topics from markdown files.
    
    Returns:
        GET: Renders the bulk upload form
        POST: Processes uploaded files and creates help topics
    """
    if request.method == 'GET':
        return render_template('help/admin/bulk_upload_flowbite.html', title="Bulk Upload Help Topics")
    
    if 'files' not in request.files:
        show_error('No files selected for upload')
        return redirect(url_for('help.bulk_upload_help_topics'))
    
    files = request.files.getlist('files')
    if not files or all(file.filename == '' for file in files):
        show_error('No files selected for upload')
        return redirect(url_for('help.bulk_upload_help_topics'))
    
    success_count = 0
    error_count = 0
    errors = []
    
    for file in files:
        if file.filename == '':
            continue
            
        if not file.filename.endswith('.md'):
            error_count += 1
            errors.append(f'{file.filename}: Only markdown (.md) files are supported')
            continue
        
        try:
            content = file.read().decode('utf-8')
            
            # Parse the markdown content to extract title and role information
            lines = content.split('\n')
            title = None
            role_access = None
            markdown_content = content
            
            # Extract title from first heading
            for line in lines:
                if line.startswith('# '):
                    title = line[2:].strip()
                    break
            
            # Extract role access information
            for line in lines:
                if line.startswith('**Role Access**:'):
                    role_access = line.split(':', 1)[1].strip()
                    break
            
            if not title:
                error_count += 1
                errors.append(f'{file.filename}: No title found (missing # heading)')
                continue
            
            # Check if topic already exists
            existing_topic = g.db_session.query(HelpTopic).filter_by(title=title).first()
            if existing_topic:
                # Update existing topic
                existing_topic.markdown_content = markdown_content
                
                # Update roles based on role_access string
                if role_access:
                    role_access_clean = role_access.strip()
                    if role_access_clean.lower() == 'public':
                        # Public topic - no roles assigned (visible to all)
                        existing_topic.allowed_roles = []
                    else:
                        role_names = [name.strip() for name in role_access_clean.split(',')]
                        roles = g.db_session.query(Role).filter(Role.name.in_(role_names)).all()
                        existing_topic.allowed_roles = roles
                else:
                    # Default to Global Admin if no role specified
                    admin_role = g.db_session.query(Role).filter_by(name='Global Admin').first()
                    if admin_role:
                        existing_topic.allowed_roles = [admin_role]
                
                success_count += 1
                continue
            
            # Create new help topic
            topic = HelpTopic(
                title=title,
                markdown_content=markdown_content
            )
            
            # Assign roles based on role_access string
            if role_access:
                role_access_clean = role_access.strip()
                if role_access_clean.lower() == 'public':
                    # Public topic - no roles assigned (visible to all)
                    topic.allowed_roles = []
                else:
                    role_names = [name.strip() for name in role_access_clean.split(',')]
                    roles = Role.query.filter(Role.name.in_(role_names)).all()
                    topic.allowed_roles = roles
            else:
                # Default to Global Admin if no role specified
                admin_role = Role.query.filter_by(name='Global Admin').first()
                if admin_role:
                    topic.allowed_roles = [admin_role]
            
            g.db_session.add(topic)
            success_count += 1
            
        except Exception as e:
            error_count += 1
            errors.append(f'{file.filename}: Error processing file - {str(e)}')
            logger.error(f'Error processing help topic file {file.filename}: {str(e)}')
    
    try:
        if success_count > 0:
            g.db_session.commit()
            show_success(f'Successfully uploaded {success_count} help topics')
        else:
            g.db_session.rollback()
    except Exception as e:
        g.db_session.rollback()
        show_error(f'Error saving help topics: {str(e)}')
        logger.error(f'Error saving bulk uploaded help topics: {str(e)}')
    
    if errors:
        error_message = f'{error_count} files had errors: ' + '; '.join(errors[:5])
        if len(errors) > 5:
            error_message += f' (and {len(errors) - 5} more)'
        show_warning(error_message)
    
    return redirect(url_for('help.admin_help_topics'))