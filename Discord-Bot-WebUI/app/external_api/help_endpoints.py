# app/external_api/help_endpoints.py

"""
Help system endpoints for external API (Discord bot integration).
"""

import logging
import markdown
import re
from flask import jsonify, request
from sqlalchemy import or_

from app.core import db
from app.models import HelpTopic, Role
from . import external_api_bp
from .auth import api_key_required

logger = logging.getLogger(__name__)


def process_discord_links_for_api(content):
    """
    Convert Discord channel references to Discord-compatible format.
    Converts [[#channel-name]] to plain #channel-name for Discord.
    """
    # Pattern for [[#channel-name]] format
    pattern = r'\[\[#([\w-]+)\]\]'
    # Replace with simple #channel-name format that Discord understands
    content = re.sub(pattern, r'#\1', content)
    return content


@external_api_bp.route('/help/topics', methods=['GET'])
@api_key_required
def get_help_topics():
    """
    Get help topics accessible by Discord bot.
    
    Query parameters:
    - role: Filter by specific role (optional)
    - search: Search in title (optional)
    """
    try:
        # Get query parameters
        role_filter = request.args.get('role')
        search_query = request.args.get('search', '').strip()
        
        # Base query
        query = db.session.query(HelpTopic)
        
        # Apply role filter if specified
        if role_filter:
            # Get topics that either have no roles (public) or include the specified role
            query = query.outerjoin(HelpTopic.allowed_roles).filter(
                or_(
                    ~HelpTopic.allowed_roles.any(),  # Public topics
                    Role.name == role_filter
                )
            )
        else:
            # Get all public topics (no roles assigned)
            query = query.filter(~HelpTopic.allowed_roles.any())
        
        # Apply search filter if specified
        if search_query:
            query = query.filter(HelpTopic.title.ilike(f'%{search_query}%'))
        
        # Get distinct topics
        topics = query.distinct().all()
        
        # Serialize topics
        topics_data = []
        for topic in topics:
            topics_data.append({
                'id': topic.id,
                'title': topic.title,
                'roles': [role.name for role in topic.allowed_roles],
                'is_public': len(topic.allowed_roles) == 0
            })
        
        return jsonify({
            'success': True,
            'topics': topics_data,
            'count': len(topics_data)
        })
        
    except Exception as e:
        logger.error(f"Error fetching help topics: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch help topics'
        }), 500


@external_api_bp.route('/help/topics/<int:topic_id>', methods=['GET'])
@api_key_required
def get_help_topic(topic_id):
    """
    Get a specific help topic with rendered content.
    
    Query parameters:
    - format: 'markdown' (default) or 'plain' (simplified for Discord)
    """
    try:
        topic = db.session.query(HelpTopic).get(topic_id)
        if not topic:
            return jsonify({
                'success': False,
                'error': 'Topic not found'
            }), 404
        
        # Get format preference
        output_format = request.args.get('format', 'markdown')
        
        # Get the content
        content = topic.markdown_content
        
        if output_format == 'plain':
            # Convert markdown to plain text for Discord
            # First convert Discord channel references
            content = process_discord_links_for_api(content)
            
            # Convert to HTML then strip tags for plain text
            html_content = markdown.markdown(
                content,
                extensions=['tables', 'fenced_code']
            )
            
            # Simple HTML to text conversion
            # Remove HTML tags but keep the content
            import re
            # Replace <br> and </p> with newlines
            html_content = re.sub(r'<br\s*/?>', '\n', html_content)
            html_content = re.sub(r'</p>', '\n\n', html_content)
            # Remove all other HTML tags
            plain_content = re.sub(r'<[^>]+>', '', html_content)
            # Clean up multiple newlines
            plain_content = re.sub(r'\n{3,}', '\n\n', plain_content)
            content = plain_content.strip()
        else:
            # Keep as markdown but process Discord links
            content = process_discord_links_for_api(content)
        
        return jsonify({
            'success': True,
            'topic': {
                'id': topic.id,
                'title': topic.title,
                'content': content,
                'format': output_format,
                'roles': [role.name for role in topic.allowed_roles],
                'is_public': len(topic.allowed_roles) == 0
            }
        })
        
    except Exception as e:
        logger.error(f"Error fetching help topic {topic_id}: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch help topic'
        }), 500


@external_api_bp.route('/help/search', methods=['GET'])
@api_key_required
def search_help_topics():
    """
    Search help topics by title and content.
    
    Query parameters:
    - q: Search query (required)
    - limit: Maximum number of results (default: 10)
    """
    try:
        search_query = request.args.get('q', '').strip()
        if not search_query:
            return jsonify({
                'success': False,
                'error': 'Search query is required'
            }), 400
        
        limit = min(int(request.args.get('limit', 10)), 50)  # Cap at 50
        
        # Search in both title and content
        topics = db.session.query(HelpTopic).filter(
            or_(
                HelpTopic.title.ilike(f'%{search_query}%'),
                HelpTopic.markdown_content.ilike(f'%{search_query}%')
            )
        ).filter(
            # Only return public topics for Discord
            ~HelpTopic.allowed_roles.any()
        ).limit(limit).all()
        
        # Serialize results
        results = []
        for topic in topics:
            # Extract a snippet from content if it contains the search term
            content = topic.markdown_content
            snippet = ''
            
            # Find the search term in content (case insensitive)
            import re
            match = re.search(f'(?i){re.escape(search_query)}', content)
            if match:
                start = max(0, match.start() - 50)
                end = min(len(content), match.end() + 50)
                snippet = '...' + content[start:end] + '...'
            else:
                # Use first 100 chars as snippet
                snippet = content[:100] + '...' if len(content) > 100 else content
            
            results.append({
                'id': topic.id,
                'title': topic.title,
                'snippet': snippet,
                'roles': [role.name for role in topic.allowed_roles],
                'is_public': len(topic.allowed_roles) == 0
            })
        
        return jsonify({
            'success': True,
            'results': results,
            'count': len(results),
            'query': search_query
        })
        
    except Exception as e:
        logger.error(f"Error searching help topics: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to search help topics'
        }), 500