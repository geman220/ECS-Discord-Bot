# app/admin_panel/routes/api_management.py

import logging
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, text, func
import json
import re
from app.models import db, User, AdminAuditLog
from app.models.admin_config import AdminConfig
from app.decorators import role_required
from .. import admin_panel_bp

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/api/management')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_management():
    """API Management hub with overview statistics"""
    try:
        # Get API endpoint statistics
        endpoints = _get_api_endpoints()
        endpoint_stats = _get_endpoint_statistics(endpoints)
        
        # Get recent API activity from audit logs
        recent_activity = _get_recent_api_activity()
        
        # Get API usage analytics
        usage_analytics = _get_api_usage_analytics()
        
        stats = {
            'total_endpoints': len(endpoints),
            'active_endpoints': len([e for e in endpoints if e.get('status') == 'active']),
            'total_requests_today': usage_analytics.get('requests_today', 0),
            'avg_response_time': usage_analytics.get('avg_response_time', 0),
            'error_rate': usage_analytics.get('error_rate', 0),
            'endpoint_breakdown': endpoint_stats
        }
        
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='api_management_viewed',
            resource_type='admin_panel',
            resource_id='api_management',
            new_value=f"Viewed API management dashboard",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return render_template('admin_panel/api/management.html',
                             stats=stats,
                             recent_activity=recent_activity,
                             endpoints=endpoints[:10])  # Show top 10 endpoints
        
    except Exception as e:
        flash(f'Error loading API management: {str(e)}', 'error')
        return redirect(url_for('admin_panel.dashboard'))


@admin_panel_bp.route('/api/endpoints')
@role_required(['Global Admin', 'Pub League Admin'])
def api_endpoints():
    """List all API endpoints with filtering and search"""
    try:
        # Get filter parameters
        endpoint_filter = request.args.get('filter', 'all')
        method_filter = request.args.get('method', 'all')
        search_query = request.args.get('search', '').strip()
        page = request.args.get('page', 1, type=int)
        per_page = 20
        
        # Get all endpoints
        all_endpoints = _get_api_endpoints()
        
        # Filter endpoints
        filtered_endpoints = []
        for endpoint in all_endpoints:
            # Apply filters
            if endpoint_filter != 'all' and endpoint.get('blueprint') != endpoint_filter:
                continue
            if method_filter != 'all' and method_filter not in endpoint.get('methods', []):
                continue
            if search_query and search_query.lower() not in endpoint.get('path', '').lower():
                continue
            
            filtered_endpoints.append(endpoint)
        
        # Pagination
        total = len(filtered_endpoints)
        start = (page - 1) * per_page
        end = start + per_page
        endpoints_page = filtered_endpoints[start:end]
        
        # Get available filters
        blueprints = list(set(e.get('blueprint', 'unknown') for e in all_endpoints))
        methods = list(set(method for e in all_endpoints for method in e.get('methods', [])))
        
        # Pagination info
        pagination = {
            'page': page,
            'per_page': per_page,
            'total': total,
            'pages': (total + per_page - 1) // per_page,
            'has_prev': page > 1,
            'has_next': page * per_page < total,
            'prev_num': page - 1 if page > 1 else None,
            'next_num': page + 1 if page * per_page < total else None
        }
        
        current_filters = {
            'filter': endpoint_filter,
            'method': method_filter,
            'search': search_query
        }
        
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='api_endpoints_viewed',
            resource_type='admin_panel',
            resource_id='api_endpoints',
            new_value=f"Viewed API endpoints list with filters: {current_filters}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return render_template('admin_panel/api/endpoints.html',
                             endpoints=endpoints_page,
                             pagination=pagination,
                             blueprints=blueprints,
                             methods=methods,
                             current_filters=current_filters)
        
    except Exception as e:
        flash(f'Error loading API endpoints: {str(e)}', 'error')
        return redirect(url_for('admin_panel.api_management'))


@admin_panel_bp.route('/api/analytics')
@role_required(['Global Admin', 'Pub League Admin'])
def api_analytics():
    """API usage analytics and monitoring"""
    try:
        # Get date range from parameters
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        
        if not date_from:
            date_from = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
        if not date_to:
            date_to = datetime.utcnow().strftime('%Y-%m-%d')
        
        # Get analytics data
        analytics = _get_detailed_api_analytics(date_from, date_to)
        
        # Get endpoint performance data
        endpoint_performance = _get_endpoint_performance_data(date_from, date_to)
        
        # Get error analysis
        error_analysis = _get_api_error_analysis(date_from, date_to)
        
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='api_analytics_viewed',
            resource_type='admin_panel',
            resource_id='api_analytics',
            new_value=f"Viewed API analytics for period {date_from} to {date_to}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return render_template('admin_panel/api/analytics.html',
                             analytics=analytics,
                             endpoint_performance=endpoint_performance,
                             error_analysis=error_analysis,
                             date_range={'start': date_from, 'end': date_to})
        
    except Exception as e:
        flash(f'Error loading API analytics: {str(e)}', 'error')
        return redirect(url_for('admin_panel.api_management'))


@admin_panel_bp.route('/api/endpoint/<path:endpoint_path>/details')
@role_required(['Global Admin', 'Pub League Admin'])
def api_endpoint_details(endpoint_path):
    """Get detailed information about a specific API endpoint"""
    try:
        endpoints = _get_api_endpoints()
        endpoint = None
        
        for ep in endpoints:
            if ep.get('path') == f'/{endpoint_path}':
                endpoint = ep
                break
        
        if not endpoint:
            return jsonify({'success': False, 'error': 'Endpoint not found'}), 404
        
        # Get usage statistics for this endpoint
        usage_stats = _get_endpoint_usage_stats(endpoint['path'])
        
        # Get recent activity for this endpoint
        recent_activity = _get_endpoint_recent_activity(endpoint['path'])
        
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='api_endpoint_details_viewed',
            resource_type='admin_panel',
            resource_id=endpoint['path'],
            new_value=f"Viewed details for API endpoint: {endpoint['path']}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify({
            'success': True,
            'endpoint': endpoint,
            'usage_stats': usage_stats,
            'recent_activity': recent_activity
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/test-endpoint', methods=['POST'])
@role_required(['Global Admin'])
def test_api_endpoint_legacy():
    """Test an API endpoint with custom parameters"""
    try:
        data = request.get_json()
        endpoint_path = data.get('endpoint')
        method = data.get('method', 'GET')
        parameters = data.get('parameters', {})
        
        # NOTE: This is a mock implementation for testing
        # In a real implementation, you would make actual HTTP requests
        # to test the endpoints, but that requires careful security considerations
        
        result = {
            'success': True,
            'status_code': 200,
            'response_time': 0.123,
            'response_data': {'message': 'Endpoint test successful (mock)'},
            'headers': {'Content-Type': 'application/json'},
            'timestamp': datetime.utcnow().isoformat()
        }
        
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='api_endpoint_tested',
            resource_type='admin_panel',
            resource_id=endpoint_path,
            new_value=f"Tested API endpoint: {endpoint_path} with method {method}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def _get_api_endpoints():
    """Get all API endpoints from the Flask application"""
    try:
        from app import create_app
        
        endpoints = []
        
        # This is a static list of known API endpoints from our codebase analysis
        # In a real implementation, you would dynamically discover these from Flask's routing
        known_endpoints = [
            {
                'path': '/api/discord_bot_last_online',
                'methods': ['GET', 'POST'],
                'blueprint': 'smart_sync',
                'description': 'Discord bot last online status',
                'status': 'active',
                'authentication': 'required'
            },
            {
                'path': '/api/matches_with_rsvp_activity_since',
                'methods': ['GET'],
                'blueprint': 'smart_sync',
                'description': 'Get matches with RSVP activity',
                'status': 'active',
                'authentication': 'required'
            },
            {
                'path': '/api/sync_stats',
                'methods': ['GET'],
                'blueprint': 'smart_sync',
                'description': 'Get synchronization statistics',
                'status': 'active',
                'authentication': 'required'
            },
            {
                'path': '/api/batch/get_message_info',
                'methods': ['POST'],
                'blueprint': 'batch',
                'description': 'Batch message information retrieval',
                'status': 'active',
                'authentication': 'required'
            },
            {
                'path': '/api/sms/config',
                'methods': ['GET'],
                'blueprint': 'account',
                'description': 'SMS configuration settings',
                'status': 'active',
                'authentication': 'required'
            },
            {
                'path': '/api/player/<int:player_id>/eligibility',
                'methods': ['GET'],
                'blueprint': 'wallet_admin',
                'description': 'Player wallet eligibility check',
                'status': 'active',
                'authentication': 'admin'
            },
            {
                'path': '/api/generate-bulk',
                'methods': ['POST'],
                'blueprint': 'wallet_admin',
                'description': 'Bulk wallet pass generation',
                'status': 'active',
                'authentication': 'admin'
            },
            {
                'path': '/api/config/test',
                'methods': ['GET'],
                'blueprint': 'wallet_admin',
                'description': 'Test wallet configuration',
                'status': 'active',
                'authentication': 'admin'
            },
            {
                'path': '/api/player_profile/<int:player_id>',
                'methods': ['GET'],
                'blueprint': 'players',
                'description': 'Get player profile data',
                'status': 'active',
                'authentication': 'required'
            },
            {
                'path': '/api/role-impersonation/available-roles',
                'methods': ['GET'],
                'blueprint': 'role_impersonation',
                'description': 'Get available roles for impersonation',
                'status': 'active',
                'authentication': 'admin'
            },
            {
                'path': '/api/role-impersonation/start',
                'methods': ['POST'],
                'blueprint': 'role_impersonation',
                'description': 'Start role impersonation session',
                'status': 'active',
                'authentication': 'admin'
            },
            {
                'path': '/api/role-impersonation/stop',
                'methods': ['POST'],
                'blueprint': 'role_impersonation',
                'description': 'Stop role impersonation session',
                'status': 'active',
                'authentication': 'admin'
            },
            {
                'path': '/api/stats',
                'methods': ['GET'],
                'blueprint': 'redis',
                'description': 'Redis cache statistics',
                'status': 'active',
                'authentication': 'admin'
            },
            {
                'path': '/api/draft-cache-stats',
                'methods': ['GET'],
                'blueprint': 'redis',
                'description': 'Draft cache statistics',
                'status': 'active',
                'authentication': 'admin'
            },
            {
                'path': '/api/template/<int:template_id>',
                'methods': ['GET', 'POST', 'PUT'],
                'blueprint': 'message_config',
                'description': 'Message template management',
                'status': 'active',
                'authentication': 'admin'
            },
            {
                'path': '/api/draft-player',
                'methods': ['POST'],
                'blueprint': 'draft_enhanced',
                'description': 'Draft player endpoint',
                'status': 'active',
                'authentication': 'required'
            }
        ]
        
        for endpoint_data in known_endpoints:
            endpoint_data['last_used'] = datetime.utcnow() - timedelta(
                hours=hash(endpoint_data['path']) % 24
            )
            endpoint_data['request_count'] = hash(endpoint_data['path']) % 1000 + 100
            endpoint_data['avg_response_time'] = (hash(endpoint_data['path']) % 500 + 50) / 1000
            endpoints.append(endpoint_data)
        
        return sorted(endpoints, key=lambda x: x['path'])
        
    except Exception as e:
        print(f"Error getting API endpoints: {e}")
        return []


def _get_endpoint_statistics(endpoints):
    """Get statistics breakdown by blueprint"""
    stats = {}
    
    for endpoint in endpoints:
        blueprint = endpoint.get('blueprint', 'unknown')
        if blueprint not in stats:
            stats[blueprint] = {
                'count': 0,
                'active': 0,
                'total_requests': 0,
                'avg_response_time': 0
            }
        
        stats[blueprint]['count'] += 1
        if endpoint.get('status') == 'active':
            stats[blueprint]['active'] += 1
        stats[blueprint]['total_requests'] += endpoint.get('request_count', 0)
        stats[blueprint]['avg_response_time'] += endpoint.get('avg_response_time', 0)
    
    # Calculate averages
    for blueprint_stats in stats.values():
        if blueprint_stats['count'] > 0:
            blueprint_stats['avg_response_time'] /= blueprint_stats['count']
    
    return stats


def _get_recent_api_activity(limit=10):
    """Get recent API-related activity from audit logs"""
    try:
        activities = db.session.query(AdminAuditLog).filter(
            AdminAuditLog.action.like('%api%')
        ).order_by(desc(AdminAuditLog.created_at)).limit(limit).all()
        
        return [{
            'id': activity.id,
            'action': activity.action,
            'description': activity.details or activity.action,
            'user': activity.user.username if activity.user else 'System',
            'timestamp': activity.created_at,
            'type': 'api'
        } for activity in activities]
        
    except Exception as e:
        print(f"Error getting recent API activity: {e}")
        return []


def _get_api_usage_analytics():
    """Get API usage analytics (mocked for now)"""
    return {
        'requests_today': 1247,
        'requests_week': 8934,
        'avg_response_time': 0.156,
        'error_rate': 2.3,
        'top_endpoints': [
            {'path': '/api/player_profile/<int:player_id>', 'requests': 234},
            {'path': '/api/sync_stats', 'requests': 189},
            {'path': '/api/discord_bot_last_online', 'requests': 156}
        ]
    }


def _get_detailed_api_analytics(date_from, date_to):
    """Get detailed API analytics for date range (mocked for now)"""
    import random
    
    # Generate mock daily data
    start_date = datetime.strptime(date_from, '%Y-%m-%d')
    end_date = datetime.strptime(date_to, '%Y-%m-%d')
    
    daily_requests = []
    current_date = start_date
    
    while current_date <= end_date:
        daily_requests.append({
            'date': current_date.strftime('%Y-%m-%d'),
            'requests': random.randint(800, 1500),
            'errors': random.randint(10, 50),
            'avg_response_time': random.uniform(0.1, 0.3)
        })
        current_date += timedelta(days=1)
    
    return {
        'daily_requests': daily_requests,
        'total_requests': sum(d['requests'] for d in daily_requests),
        'total_errors': sum(d['errors'] for d in daily_requests),
        'avg_response_time': sum(d['avg_response_time'] for d in daily_requests) / len(daily_requests),
        'error_rate': (sum(d['errors'] for d in daily_requests) / sum(d['requests'] for d in daily_requests)) * 100
    }


def _get_endpoint_performance_data(date_from, date_to):
    """Get endpoint performance data (mocked for now)"""
    import random
    
    endpoints = [
        '/api/player_profile/<int:player_id>',
        '/api/sync_stats',
        '/api/discord_bot_last_online',
        '/api/matches_with_rsvp_activity_since',
        '/api/batch/get_message_info'
    ]
    
    performance_data = []
    for endpoint in endpoints:
        performance_data.append({
            'endpoint': endpoint,
            'requests': random.randint(100, 500),
            'avg_response_time': random.uniform(0.05, 0.4),
            'error_count': random.randint(1, 20),
            'success_rate': random.uniform(95, 99.9)
        })
    
    return sorted(performance_data, key=lambda x: x['requests'], reverse=True)


def _get_api_error_analysis(date_from, date_to):
    """Get API error analysis (mocked for now)"""
    import random
    
    error_types = [
        {'type': '500 Internal Server Error', 'count': random.randint(10, 30)},
        {'type': '404 Not Found', 'count': random.randint(5, 15)},
        {'type': '401 Unauthorized', 'count': random.randint(8, 25)},
        {'type': '400 Bad Request', 'count': random.randint(12, 20)},
        {'type': '429 Too Many Requests', 'count': random.randint(3, 10)}
    ]
    
    top_error_endpoints = [
        {'endpoint': '/api/player_profile/<int:player_id>', 'errors': random.randint(5, 15)},
        {'endpoint': '/api/batch/get_message_info', 'errors': random.randint(3, 12)},
        {'endpoint': '/api/sync_stats', 'errors': random.randint(2, 8)}
    ]
    
    return {
        'error_types': error_types,
        'top_error_endpoints': top_error_endpoints,
        'total_errors': sum(e['count'] for e in error_types)
    }


def _get_endpoint_usage_stats(endpoint_path):
    """Get usage statistics for a specific endpoint (mocked for now)"""
    import random
    
    return {
        'total_requests': random.randint(500, 2000),
        'avg_response_time': random.uniform(0.1, 0.5),
        'error_count': random.randint(5, 50),
        'success_rate': random.uniform(95, 99.8),
        'last_24h_requests': random.randint(50, 200),
        'peak_hour': f"{random.randint(9, 17)}:00",
        'most_common_errors': [
            {'error': '500 Internal Server Error', 'count': random.randint(2, 10)},
            {'error': '404 Not Found', 'count': random.randint(1, 5)}
        ]
    }


def _get_endpoint_recent_activity(endpoint_path, limit=10):
    """Get recent activity for a specific endpoint (mocked for now)"""
    import random
    
    activities = []
    for i in range(limit):
        activities.append({
            'timestamp': datetime.utcnow() - timedelta(minutes=random.randint(1, 1440)),
            'method': random.choice(['GET', 'POST', 'PUT']),
            'status_code': random.choice([200, 200, 200, 200, 400, 404, 500]),
            'response_time': random.uniform(0.05, 0.8),
            'user_agent': random.choice([
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'ECS Discord Bot/1.0',
                'ECS Mobile App/2.1'
            ])
        })
    
    return sorted(activities, key=lambda x: x['timestamp'], reverse=True)


# API Management Endpoints

@admin_panel_bp.route('/api-management/test-endpoint', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def test_api_endpoint():
    """Test API endpoint functionality."""
    try:
        import requests
        import time
        
        data = request.get_json()
        endpoint_url = data.get('endpoint_url')
        method = data.get('method', 'GET')
        test_data = data.get('test_data', {})
        
        if not endpoint_url:
            return jsonify({'success': False, 'message': 'Endpoint URL is required'}), 400
        
        # Record start time
        start_time = time.time()
        
        try:
            # Make the API request
            if method.upper() == 'GET':
                response = requests.get(endpoint_url, timeout=10)
            elif method.upper() == 'POST':
                response = requests.post(endpoint_url, json=test_data, timeout=10)
            else:
                return jsonify({'success': False, 'message': 'Method not supported'}), 400
            
            # Calculate response time
            response_time = round((time.time() - start_time) * 1000)  # Convert to milliseconds
            
            test_result = {
                'status': 'success' if response.status_code < 400 else 'error',
                'response_time': f'{response_time}ms',
                'status_code': response.status_code,
                'response_size': f'{len(response.content)}B',
                'headers': dict(response.headers),
                'content_type': response.headers.get('Content-Type', 'unknown')
            }
            
            # Log the test
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='test_api_endpoint',
                resource_type='api_management',
                resource_id=endpoint_url,
                new_value=f'Tested {method} {endpoint_url} - Status: {response.status_code}',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            return jsonify({
                'success': True,
                'result': test_result
            })
            
        except requests.exceptions.Timeout:
            return jsonify({
                'success': False,
                'message': 'Request timed out',
                'result': {'status': 'timeout', 'response_time': '>10000ms'}
            })
        except requests.exceptions.ConnectionError:
            return jsonify({
                'success': False,
                'message': 'Connection failed',
                'result': {'status': 'connection_error'}
            })
        
    except Exception as e:
        logger.error(f"API endpoint test error: {e}")
        return jsonify({'success': False, 'message': 'Test failed'}), 500


@admin_panel_bp.route('/api-management/rate-limits', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin'])
def manage_rate_limits():
    """Manage API rate limits."""
    if request.method == 'POST':
        try:
            data = request.get_json()
            limit_per_minute = data.get('limit_per_minute', type=int)
            limit_per_hour = data.get('limit_per_hour', type=int)
            limit_per_day = data.get('limit_per_day', type=int)
            
            if not all([limit_per_minute, limit_per_hour, limit_per_day]):
                return jsonify({'success': False, 'message': 'All rate limits are required'}), 400
            
            # Save rate limits to AdminConfig
            AdminConfig.set_setting('api_rate_limit_minute', str(limit_per_minute), current_user.id)
            AdminConfig.set_setting('api_rate_limit_hour', str(limit_per_hour), current_user.id)
            AdminConfig.set_setting('api_rate_limit_day', str(limit_per_day), current_user.id)
            
            # Log the change
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='update_rate_limits',
                resource_type='api_management',
                resource_id='rate_limits',
                new_value=f'Updated rate limits: {limit_per_minute}/min, {limit_per_hour}/hr, {limit_per_day}/day',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            return jsonify({
                'success': True,
                'message': 'Rate limits updated successfully'
            })
            
        except Exception as e:
            logger.error(f"Rate limit update error: {e}")
            return jsonify({'success': False, 'message': 'Update failed'}), 500
    
    # GET request - return current limits
    try:
        current_limits = {
            'per_minute': int(AdminConfig.get_setting_value('api_rate_limit_minute', '60')),
            'per_hour': int(AdminConfig.get_setting_value('api_rate_limit_hour', '1000')),
            'per_day': int(AdminConfig.get_setting_value('api_rate_limit_day', '10000'))
        }
        return jsonify(current_limits)
    except Exception as e:
        logger.error(f"Error getting rate limits: {e}")
        return jsonify({'error': str(e)}), 500


@admin_panel_bp.route('/api-management/api-keys', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin'])
def manage_api_keys():
    """Manage API keys and authentication."""
    if request.method == 'POST':
        try:
            data = request.get_json()
            action = data.get('action')  # 'generate', 'revoke', 'update'
            key_name = data.get('key_name', '')
            
            if action == 'generate':
                import secrets
                
                # Generate a new API key
                api_key = f"ecs_{secrets.token_urlsafe(32)}"
                
                # Store the key (in production, would use proper API key model)
                key_setting = f"api_key_{key_name.replace(' ', '_').lower()}"
                AdminConfig.set_setting(key_setting, api_key, current_user.id)
                
                # Log the generation
                AdminAuditLog.log_action(
                    user_id=current_user.id,
                    action='generate_api_key',
                    resource_type='api_management',
                    resource_id=key_name,
                    new_value=f'Generated API key for {key_name}',
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get('User-Agent')
                )
                
                return jsonify({
                    'success': True,
                    'message': f'API key generated for {key_name}',
                    'api_key': api_key
                })
                
            elif action == 'revoke':
                key_setting = f"api_key_{key_name.replace(' ', '_').lower()}"
                
                # Remove the key
                key_config = AdminConfig.query.filter_by(key=key_setting).first()
                if key_config:
                    db.session.delete(key_config)
                    db.session.commit()
                
                # Log the revocation
                AdminAuditLog.log_action(
                    user_id=current_user.id,
                    action='revoke_api_key',
                    resource_type='api_management',
                    resource_id=key_name,
                    new_value=f'Revoked API key for {key_name}',
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get('User-Agent')
                )
                
                return jsonify({
                    'success': True,
                    'message': f'API key revoked for {key_name}'
                })
            
        except Exception as e:
            logger.error(f"API key management error: {e}")
            return jsonify({'success': False, 'message': 'Operation failed'}), 500
    
    # GET request - return current API keys (masked for security)
    try:
        api_keys = []
        api_configs = AdminConfig.query.filter(AdminConfig.key.like('api_key_%')).all()
        
        for config in api_configs:
            key_name = config.key.replace('api_key_', '').replace('_', ' ').title()
            masked_key = f"{config.value[:8]}...{config.value[-4:]}" if config.value else "None"
            
            api_keys.append({
                'name': key_name,
                'key': masked_key,
                'created_at': config.created_at.isoformat() if config.created_at else None,
                'last_used': 'Never'  # Would track usage in production
            })
        
        return jsonify({'api_keys': api_keys})
        
    except Exception as e:
        logger.error(f"Error getting API keys: {e}")
        return jsonify({'error': str(e)}), 500