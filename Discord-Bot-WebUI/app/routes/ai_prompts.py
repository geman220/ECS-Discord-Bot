# app/routes/ai_prompts.py

"""
AI Prompt Configuration API Routes

RESTful API endpoints for managing AI prompt configurations
with full CRUD operations and versioning support.
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from typing import Dict, Any, Optional
import logging
from datetime import datetime

from app.models.ai_prompt_config import AIPromptConfig, AIPromptTemplate
from app.core.session_manager import managed_session
from app.core import db
from app.decorators import role_required

logger = logging.getLogger(__name__)

ai_prompts_bp = Blueprint('ai_prompts', __name__, url_prefix='/ai-prompts')


@ai_prompts_bp.route('/', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def list_prompts():
    """List all AI prompt configurations."""
    try:
        with managed_session() as session:
            # Get filter parameters
            prompt_type = request.args.get('type')
            active_only = request.args.get('active_only', 'true').lower() == 'true'
            
            # Build query
            query = session.query(AIPromptConfig)
            
            if active_only:
                query = query.filter_by(is_active=True)
            
            if prompt_type:
                query = query.filter_by(prompt_type=prompt_type)
            
            # Order by name and version
            prompts = query.order_by(AIPromptConfig.name, AIPromptConfig.version.desc()).all()
            
            # Get templates for the template library section
            templates = session.query(AIPromptTemplate).all()
            
            # Check if this is an API request
            if request.headers.get('Accept') == 'application/json':
                return jsonify({
                    'success': True,
                    'prompts': [p.to_dict() for p in prompts],
                    'count': len(prompts)
                })
            
            # Otherwise render template
            return render_template('ai_prompts/list_prompts.html', prompts=prompts, templates=templates)
            
    except Exception as e:
        logger.error(f"Error listing AI prompts: {e}", exc_info=True)
        if request.headers.get('Accept') == 'application/json':
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f"Error loading prompts: {e}", 'danger')
        return redirect(url_for('main.index'))


@ai_prompts_bp.route('/create', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def create_prompt():
    """Create a new AI prompt configuration."""
    if request.method == 'GET':
        # Load templates for the form
        with managed_session() as session:
            templates = session.query(AIPromptTemplate).all()
            return render_template('ai_prompts/create_prompt.html', templates=templates)
    
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        
        with managed_session() as session:
            # Create new prompt configuration
            prompt_config = AIPromptConfig(
                name=data.get('name'),
                description=data.get('description'),
                prompt_type=data.get('prompt_type', 'match_commentary'),
                system_prompt=data.get('system_prompt'),
                user_prompt_template=data.get('user_prompt_template'),
                competition_filter=data.get('competition_filter'),
                team_filter=data.get('team_filter'),
                event_types=data.get('event_types'),
                temperature=float(data.get('temperature', 0.7)),
                max_tokens=int(data.get('max_tokens', 150)),
                personality_traits=data.get('personality_traits'),
                forbidden_topics=data.get('forbidden_topics'),
                required_elements=data.get('required_elements'),
                rivalry_teams=data.get('rivalry_teams'),
                rivalry_intensity=int(data.get('rivalry_intensity', 5)),
                created_by=current_user.username if hasattr(current_user, 'username') else 'system'
            )
            
            session.add(prompt_config)
            session.commit()
            
            logger.info(f"Created AI prompt configuration: {prompt_config.name}")
            
            if request.is_json:
                return jsonify({
                    'success': True,
                    'prompt': prompt_config.to_dict(),
                    'message': f'Created prompt configuration: {prompt_config.name}'
                })
            
            flash(f'Successfully created prompt: {prompt_config.name}', 'success')
            return redirect(url_for('ai_prompts.list_prompts'))
            
    except Exception as e:
        logger.error(f"Error creating AI prompt: {e}", exc_info=True)
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        flash(f"Error creating prompt: {e}", 'danger')
        return redirect(url_for('ai_prompts.create_prompt'))


@ai_prompts_bp.route('/<int:prompt_id>', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_prompt(prompt_id: int):
    """Get a specific AI prompt configuration."""
    try:
        with managed_session() as session:
            prompt_config = session.query(AIPromptConfig).get(prompt_id)
            
            if not prompt_config:
                if request.headers.get('Accept') == 'application/json':
                    return jsonify({'success': False, 'error': 'Prompt not found'}), 404
                flash('Prompt configuration not found', 'warning')
                return redirect(url_for('ai_prompts.list_prompts'))
            
            if request.headers.get('Accept') == 'application/json':
                return jsonify({
                    'success': True,
                    'prompt': prompt_config.to_dict()
                })
            
            return render_template('ai_prompts/view_prompt.html', prompt=prompt_config)
            
    except Exception as e:
        logger.error(f"Error getting AI prompt {prompt_id}: {e}", exc_info=True)
        if request.headers.get('Accept') == 'application/json':
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f"Error loading prompt: {e}", 'danger')
        return redirect(url_for('ai_prompts.list_prompts'))


@ai_prompts_bp.route('/<int:prompt_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def edit_prompt(prompt_id: int):
    """Edit an AI prompt configuration (creates new version)."""
    try:
        with managed_session() as session:
            prompt_config = session.query(AIPromptConfig).get(prompt_id)
            
            if not prompt_config:
                if request.is_json:
                    return jsonify({'success': False, 'error': 'Prompt not found'}), 404
                flash('Prompt configuration not found', 'warning')
                return redirect(url_for('ai_prompts.list_prompts'))
            
            if request.method == 'GET':
                return render_template('ai_prompts/create_prompt.html', prompt=prompt_config)
            
            # Create new version with updates
            data = request.get_json() if request.is_json else request.form.to_dict()
            
            # Clone for new version
            new_version = prompt_config.clone_for_new_version()
            
            # Update fields
            if 'system_prompt' in data:
                new_version.system_prompt = data['system_prompt']
            if 'user_prompt_template' in data:
                new_version.user_prompt_template = data['user_prompt_template']
            if 'temperature' in data:
                new_version.temperature = float(data['temperature'])
            if 'max_tokens' in data:
                new_version.max_tokens = int(data['max_tokens'])
            if 'personality_traits' in data:
                new_version.personality_traits = data['personality_traits']
            if 'forbidden_topics' in data:
                new_version.forbidden_topics = data['forbidden_topics']
            if 'required_elements' in data:
                new_version.required_elements = data['required_elements']
            if 'rivalry_teams' in data:
                new_version.rivalry_teams = data['rivalry_teams']
            if 'rivalry_intensity' in data:
                new_version.rivalry_intensity = int(data['rivalry_intensity'])
            
            session.add(new_version)
            session.commit()
            
            logger.info(f"Created new version {new_version.version} of prompt: {new_version.name}")
            
            if request.is_json:
                return jsonify({
                    'success': True,
                    'prompt': new_version.to_dict(),
                    'message': f'Created version {new_version.version} of {new_version.name}'
                })
            
            flash(f'Successfully created version {new_version.version}', 'success')
            return redirect(url_for('ai_prompts.get_prompt', prompt_id=new_version.id))
            
    except Exception as e:
        logger.error(f"Error editing AI prompt {prompt_id}: {e}", exc_info=True)
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f"Error editing prompt: {e}", 'danger')
        return redirect(url_for('ai_prompts.list_prompts'))


@ai_prompts_bp.route('/<int:prompt_id>/toggle', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def toggle_prompt(prompt_id: int):
    """Toggle active status of a prompt configuration."""
    try:
        with managed_session() as session:
            prompt_config = session.query(AIPromptConfig).get(prompt_id)
            
            if not prompt_config:
                return jsonify({'success': False, 'error': 'Prompt not found'}), 404
            
            prompt_config.is_active = not prompt_config.is_active
            session.commit()
            
            status = "activated" if prompt_config.is_active else "deactivated"
            logger.info(f"Prompt {prompt_config.name} {status}")
            
            return jsonify({
                'success': True,
                'is_active': prompt_config.is_active,
                'message': f'Prompt {status} successfully'
            })
            
    except Exception as e:
        logger.error(f"Error toggling AI prompt {prompt_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@ai_prompts_bp.route('/active/<string:prompt_type>', methods=['GET'])
def get_active_prompt(prompt_type: str):
    """
    Get the active prompt configuration for a specific type.
    This is used by the AI client to fetch current configuration.
    """
    try:
        with managed_session() as session:
            # Get competition and team filters from query params
            competition = request.args.get('competition')
            team = request.args.get('team')
            
            # Find the best matching active prompt
            query = session.query(AIPromptConfig).filter(
                AIPromptConfig.prompt_type == prompt_type,
                AIPromptConfig.is_active == True
            )
            
            # Apply filters if provided
            if competition:
                query = query.filter(
                    db.or_(
                        AIPromptConfig.competition_filter == competition,
                        AIPromptConfig.competition_filter == 'all',
                        AIPromptConfig.competition_filter == None
                    )
                )
            
            # Get the highest version
            prompt_config = query.order_by(AIPromptConfig.version.desc()).first()
            
            if not prompt_config:
                # Return default configuration
                return jsonify({
                    'success': True,
                    'prompt': None,
                    'using_default': True
                })
            
            return jsonify({
                'success': True,
                'prompt': prompt_config.to_dict(),
                'using_default': False
            })
            
    except Exception as e:
        logger.error(f"Error getting active prompt for type {prompt_type}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@ai_prompts_bp.route('/templates', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def manage_templates():
    """Manage prompt templates."""
    if request.method == 'GET':
        with managed_session() as session:
            templates = session.query(AIPromptTemplate).all()
            
            if request.headers.get('Accept') == 'application/json':
                return jsonify({
                    'success': True,
                    'templates': [t.to_dict() for t in templates]
                })
            
            return render_template('ai_prompts/templates.html', templates=templates)
    
    # POST - Create new template
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        
        with managed_session() as session:
            template = AIPromptTemplate(
                name=data.get('name'),
                category=data.get('category'),
                description=data.get('description'),
                template_data=data.get('template_data'),
                is_default=data.get('is_default', False)
            )
            
            session.add(template)
            session.commit()
            
            logger.info(f"Created AI prompt template: {template.name}")
            
            if request.is_json:
                return jsonify({
                    'success': True,
                    'template': template.to_dict()
                })
            
            flash(f'Successfully created template: {template.name}', 'success')
            return redirect(url_for('ai_prompts.manage_templates'))
            
    except Exception as e:
        logger.error(f"Error creating template: {e}", exc_info=True)
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        flash(f"Error creating template: {e}", 'danger')
        return redirect(url_for('ai_prompts.manage_templates'))


@ai_prompts_bp.route('/<int:prompt_id>/duplicate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def duplicate_prompt(prompt_id: int):
    """Duplicate an existing AI prompt configuration."""
    try:
        with managed_session() as session:
            original_prompt = session.query(AIPromptConfig).get(prompt_id)
            
            if not original_prompt:
                flash('Prompt configuration not found', 'warning')
                return redirect(url_for('ai_prompts.list_prompts'))
            
            # Create a copy with a new name
            new_prompt = AIPromptConfig(
                name=f"{original_prompt.name} (Copy)",
                description=original_prompt.description,
                prompt_type=original_prompt.prompt_type,
                system_prompt=original_prompt.system_prompt,
                user_prompt_template=original_prompt.user_prompt_template,
                competition_filter=original_prompt.competition_filter,
                temperature=original_prompt.temperature,
                max_tokens=original_prompt.max_tokens,
                personality_traits=original_prompt.personality_traits,
                forbidden_topics=original_prompt.forbidden_topics,
                rivalry_teams=original_prompt.rivalry_teams,
                rivalry_intensity=original_prompt.rivalry_intensity,
                is_active=False,  # New copies are inactive by default
                created_by=current_user.username if hasattr(current_user, 'username') else 'system'
            )
            
            session.add(new_prompt)
            session.commit()
            
            flash(f'Successfully duplicated prompt: {new_prompt.name}', 'success')
            return redirect(url_for('ai_prompts.edit_prompt', prompt_id=new_prompt.id))
            
    except Exception as e:
        logger.error(f"Error duplicating AI prompt {prompt_id}: {e}", exc_info=True)
        flash(f"Error duplicating prompt: {e}", 'danger')
        return redirect(url_for('ai_prompts.list_prompts'))


@ai_prompts_bp.route('/<int:prompt_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def delete_prompt(prompt_id: int):
    """Delete an AI prompt configuration."""
    try:
        with managed_session() as session:
            prompt_config = session.query(AIPromptConfig).get(prompt_id)
            
            if not prompt_config:
                flash('Prompt configuration not found', 'warning')
                return redirect(url_for('ai_prompts.list_prompts'))
            
            prompt_name = prompt_config.name
            session.delete(prompt_config)
            session.commit()
            
            logger.info(f"Deleted AI prompt configuration: {prompt_name}")
            flash(f'Successfully deleted prompt: {prompt_name}', 'success')
            
    except Exception as e:
        logger.error(f"Error deleting AI prompt {prompt_id}: {e}", exc_info=True)
        flash(f"Error deleting prompt: {e}", 'danger')
    
    return redirect(url_for('ai_prompts.list_prompts'))


@ai_prompts_bp.route('/<int:prompt_id>/view', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin']) 
def view_prompt(prompt_id: int):
    """View a specific AI prompt configuration."""
    return get_prompt(prompt_id)