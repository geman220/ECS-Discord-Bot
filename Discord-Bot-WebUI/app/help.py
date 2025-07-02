# app/help.py

"""
Help Module

This module defines the endpoints for the help system in the application.
It includes routes for viewing help topics, searching for topics, and administrative
actions to create, edit, and delete help topics as well as upload images for help content.
Access to topics is controlled based on user roles, and Markdown content is converted to HTML for display.
"""

import os
import markdown
from flask import Blueprint, render_template, request, redirect, url_for, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.core import db
from app.models import Role, HelpTopic
from app.forms import HelpTopicForm
from app.decorators import role_required
from app.alert_helpers import show_success, show_error, show_warning, show_info
import logging

logger = logging.getLogger(__name__)

# Define blueprint for the help system.
help_bp = Blueprint('help', __name__, template_folder='templates/help', static_folder='static/help')

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

@help_bp.route('/')
@login_required
def index():
    """
    Display the list of help topics accessible to the current user.

    Returns:
        Rendered template of the help topics index.
    """
    # Get topics allowed based on the current user's roles.
    user_role_names = [role.name for role in current_user.roles]
    topics = HelpTopic.query.join(HelpTopic.allowed_roles).filter(Role.name.in_(user_role_names)).all()
    return render_template('help/index.html', topics=topics, title="Help Topics")

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
    topic = HelpTopic.query.get_or_404(topic_id)
    allowed_role_names = [role.name for role in topic.allowed_roles]
    if not set(allowed_role_names) & set(role.name for role in current_user.roles):
        show_error('You do not have permission to view this help topic.')
        return redirect(url_for('help.index'))
    # Convert Markdown to HTML using the fenced code extension for code blocks.
    html_content = markdown.markdown(topic.markdown_content, extensions=['fenced_code'])
    return render_template('help/view_topic.html', topic=topic, content=html_content, title=topic.title)

@help_bp.route('/search_topics', methods=['GET'])
@login_required
def search_topics():
    """
    Search help topics based on a query string and return results as JSON.

    Returns:
        JSON response containing a list of help topics matching the query.
    """
    query = request.args.get('query', '').strip()
    # Get topics allowed based on the current user's roles.
    user_role_names = [role.name for role in current_user.roles]
    topics_query = HelpTopic.query.join(HelpTopic.allowed_roles).filter(Role.name.in_(user_role_names))
    if query:
        topics_query = topics_query.filter(HelpTopic.title.ilike(f"%{query}%"))
    topics = topics_query.all()
    topics_data = [{"id": topic.id, "title": topic.title} for topic in topics]
    return jsonify({"topics": topics_data})

# --- ADMIN ROUTES ---

@help_bp.route('/admin')
@login_required
@role_required('Global Admin')
def admin_help_topics():
    """
    Display all help topics for administrative management.

    Returns:
        Rendered template of the admin help topics list.
    """
    topics = HelpTopic.query.all()
    return render_template('help/admin/list_help_topics.html', topics=topics, title="Admin - Help Topics")

@help_bp.route('/admin/new', methods=['GET', 'POST'])
@login_required
@role_required('Global Admin')
def new_help_topic():
    """
    Create a new help topic.

    Returns:
        Redirects to the admin help topics list upon successful creation,
        or renders the new help topic form.
    """
    form = HelpTopicForm()
    form.roles.choices = [(role.id, role.name) for role in Role.query.all()]
    if form.validate_on_submit():
        topic = HelpTopic(
            title=form.title.data,
            markdown_content=form.markdown_content.data
        )
        selected_roles = Role.query.filter(Role.id.in_(form.roles.data)).all()
        topic.allowed_roles = selected_roles
        db.session.add(topic)
        db.session.commit()
        show_success('Help topic created successfully!')
        return redirect(url_for('help.admin_help_topics'))
    return render_template('help/admin/new_help_topic.html', form=form, title="Create New Help Topic")

@help_bp.route('/admin/edit/<int:topic_id>', methods=['GET', 'POST'])
@login_required
@role_required('Global Admin')
def edit_help_topic(topic_id):
    """
    Edit an existing help topic.

    Parameters:
        topic_id (int): The ID of the help topic to edit.

    Returns:
        Redirects to the admin help topics list upon successful update,
        or renders the edit form.
    """
    topic = HelpTopic.query.get_or_404(topic_id)
    form = HelpTopicForm(obj=topic)
    form.roles.choices = [(role.id, role.name) for role in Role.query.all()]
    if request.method == 'GET':
        form.roles.data = [role.id for role in topic.allowed_roles]
    if form.validate_on_submit():
        topic.title = form.title.data
        topic.markdown_content = form.markdown_content.data
        selected_roles = Role.query.filter(Role.id.in_(form.roles.data)).all()
        topic.allowed_roles = selected_roles
        db.session.commit()
        show_success('Help topic updated successfully!')
        return redirect(url_for('help.admin_help_topics'))
    return render_template('help/admin/edit_help_topic.html', form=form, topic=topic, title="Edit Help Topic")

@help_bp.route('/admin/delete/<int:topic_id>', methods=['POST'])
@login_required
@role_required('Global Admin')
def delete_help_topic(topic_id):
    """
    Delete a help topic.

    Parameters:
        topic_id (int): The ID of the help topic to delete.

    Returns:
        Redirects to the admin help topics list after deletion.
    """
    topic = HelpTopic.query.get_or_404(topic_id)
    db.session.delete(topic)
    db.session.commit()
    show_success('Help topic deleted successfully!')
    return redirect(url_for('help.admin_help_topics'))

@help_bp.route('/admin/upload_image', methods=['POST'])
@login_required
@role_required('Global Admin')
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