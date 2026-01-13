# app/monitoring/tasks.py

"""
Task Monitoring Routes

Provides endpoints for monitoring and managing Celery tasks:
- Task dashboard
- Task status
- Task revocation
- Task rescheduling
"""

import json
import logging
from datetime import datetime, timedelta

from flask import jsonify, request, render_template
from flask_login import login_required
from celery.result import AsyncResult
from sqlalchemy import or_

from app.monitoring import monitoring_bp
from app.monitoring.task_monitor import task_monitor
from app.decorators import role_required
from app.utils.safe_redis import get_safe_redis
from app.core import celery
from app.core.helpers import get_match
from app.core.session_manager import managed_session
from app.models import MLSMatch
from app.tasks.tasks_live_reporting import start_live_reporting, force_create_mls_thread_task

logger = logging.getLogger(__name__)


@monitoring_bp.route('/', endpoint='monitor_dashboard')
@login_required
@role_required('Global Admin')
def monitor_dashboard():
    """
    Render the monitoring dashboard page.

    Accessible only to Global Admin users.
    """
    return render_template('monitoring_flowbite.html', title='Monitoring Dashboard')


@monitoring_bp.route('/tasks/all', endpoint='get_all_tasks')
@login_required
@role_required('Global Admin')
def get_all_tasks():
    """
    Retrieve the scheduled tasks for all matches with detailed match information.

    Returns:
        JSON response with scheduled tasks details including match names and teams.
    """
    try:
        with managed_session() as session:
            # Get active matches (same criteria as cache system)
            now = datetime.utcnow()
            matches = session.query(MLSMatch).filter(
                MLSMatch.date_time >= now - timedelta(days=2),
                MLSMatch.date_time <= now + timedelta(days=7)
            ).order_by(MLSMatch.date_time).all()

            # Collect all tasks for the frontend (flattened format)
            all_tasks = []
            matches_info = []

            for match in matches:
                # Use enhanced task status with cache
                try:
                    from app.utils.task_status_helper import get_enhanced_match_task_status
                    tasks_info = get_enhanced_match_task_status(match.id)
                except ImportError:
                    # Fallback to original monitoring logic
                    tasks_info = task_monitor.verify_scheduled_tasks(str(match.id))

                # Create match info
                match_info = {
                    'id': match.id,
                    'match_id': match.match_id,
                    'home_team': 'Seattle Sounders FC' if match.is_home_game else match.opponent,
                    'away_team': match.opponent if match.is_home_game else 'Seattle Sounders FC',
                    'opponent': match.opponent,
                    'date': match.date_time.isoformat() if match.date_time else None,
                    'venue': match.venue,
                    'competition': match.competition,
                    'is_home_game': match.is_home_game,
                    'discord_thread_id': match.discord_thread_id,
                    'tasks': tasks_info
                }
                matches_info.append(match_info)

                # Flatten tasks for the frontend
                if tasks_info.get('success') and tasks_info.get('tasks'):
                    tasks = tasks_info['tasks']
                    match_display = f"{'Sounders vs ' + match.opponent if match.is_home_game else match.opponent + ' vs Sounders'}"

                    # Add thread creation task if exists
                    if 'thread' in tasks:
                        thread_task = tasks['thread']
                        all_tasks.append({
                            'name': f"Thread Creation - {match_display}",
                            'type': 'Thread Creation',
                            'match_id': match.id,
                            'status': thread_task.get('status', 'UNKNOWN'),
                            'task_id': thread_task.get('task_id', 'unknown'),
                            'eta': thread_task.get('eta'),
                            'result': thread_task.get('result'),
                            'message': thread_task.get('message', ''),
                            'fallback': thread_task.get('fallback', False),
                            'timestamp': tasks_info.get('timestamp')
                        })

                    # Add live reporting task if exists
                    if 'reporting' in tasks:
                        reporting_task = tasks['reporting']
                        all_tasks.append({
                            'name': f"Live Reporting - {match_display}",
                            'type': 'Live Reporting',
                            'match_id': match.id,
                            'status': reporting_task.get('status', 'UNKNOWN'),
                            'task_id': reporting_task.get('task_id', 'unknown'),
                            'eta': reporting_task.get('eta'),
                            'result': reporting_task.get('result'),
                            'message': reporting_task.get('message', ''),
                            'fallback': reporting_task.get('fallback', False),
                            'timestamp': tasks_info.get('timestamp')
                        })

            return jsonify({
                'success': True,
                'matches': matches_info,
                'tasks': all_tasks,  # Flattened for frontend compatibility
                'total_matches': len(matches_info),
                'total_tasks': len(all_tasks)
            })
    except Exception as e:
        logger.error(f"Error getting all tasks: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/tasks/dashboard', endpoint='get_task_dashboard')
@login_required
@role_required('Global Admin')
def get_task_dashboard():
    """
    Enhanced task monitoring dashboard with comprehensive match and task details.

    Returns:
        JSON response with detailed task monitoring information.
    """
    try:
        with managed_session() as session:
            # Only show matches that are upcoming or recently completed (within 3 hours)
            cutoff_time = datetime.utcnow() - timedelta(hours=3)

            matches = session.query(MLSMatch).filter(
                (MLSMatch.date_time >= cutoff_time) &
                (
                    (MLSMatch.live_reporting_scheduled == True) |
                    (MLSMatch.thread_creation_scheduled == True) |
                    (MLSMatch.thread_created == True) |
                    (MLSMatch.live_reporting_started == True)
                )
            ).order_by(MLSMatch.date_time.asc()).all()

            dashboard_data = {
                'success': True,
                'summary': {
                    'total_matches': len(matches),
                    'live_reporting_scheduled': 0,
                    'thread_creation_scheduled': 0,
                    'active_tasks': 0,
                    'failed_tasks': 0
                },
                'matches': []
            }

            for match in matches:
                tasks_info = task_monitor.verify_scheduled_tasks(str(match.id))

                # Count task statuses for summary
                if tasks_info.get('success') and tasks_info.get('thread_task', {}).get('is_scheduled'):
                    dashboard_data['summary']['thread_creation_scheduled'] += 1
                    thread_status = tasks_info['thread_task']['status']
                    if thread_status and thread_status.get('status') in ['PENDING', 'STARTED']:
                        dashboard_data['summary']['active_tasks'] += 1
                    elif thread_status and thread_status.get('status') == 'FAILURE':
                        dashboard_data['summary']['failed_tasks'] += 1

                if tasks_info.get('success') and tasks_info.get('reporting_task', {}).get('is_scheduled'):
                    dashboard_data['summary']['live_reporting_scheduled'] += 1
                    reporting_status = tasks_info['reporting_task']['status']
                    if reporting_status and reporting_status.get('status') in ['PENDING', 'STARTED']:
                        dashboard_data['summary']['active_tasks'] += 1
                    elif reporting_status and reporting_status.get('status') == 'FAILURE':
                        dashboard_data['summary']['failed_tasks'] += 1

                # Enhanced match information for dashboard
                match_info = {
                    'id': match.id,
                    'match_id': match.match_id,
                    'display_name': f"{'vs' if not match.is_home_game else ''} {match.opponent}",
                    'home_team': 'Seattle Sounders FC' if match.is_home_game else match.opponent,
                    'away_team': match.opponent if match.is_home_game else 'Seattle Sounders FC',
                    'opponent': match.opponent,
                    'date': match.date_time.isoformat() if match.date_time else None,
                    'venue': match.venue,
                    'competition': match.competition,
                    'is_home_game': match.is_home_game,
                    'match_status': {
                        'live_reporting_scheduled': match.live_reporting_scheduled,
                        'live_reporting_started': match.live_reporting_started,
                        'live_reporting_status': match.live_reporting_status,
                        'thread_created': match.thread_created,
                        'thread_creation_scheduled': match.thread_creation_scheduled,
                        'discord_thread_id': match.discord_thread_id
                    },
                    'scheduling_info': {
                        'thread_creation_time': match.thread_creation_time.isoformat() if match.thread_creation_time else None,
                        'last_thread_scheduling_attempt': match.last_thread_scheduling_attempt.isoformat() if match.last_thread_scheduling_attempt else None,
                        'live_reporting_task_id': match.live_reporting_task_id,
                        'thread_creation_task_id': match.thread_creation_task_id
                    },
                    'tasks': tasks_info,
                    'links': {
                        'summary_link': match.summary_link,
                        'stats_link': match.stats_link,
                        'commentary_link': match.commentary_link
                    }
                }
                dashboard_data['matches'].append(match_info)

            return jsonify(dashboard_data)

    except Exception as e:
        logger.error(f"Error generating task dashboard: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/tasks/match/<match_id>', endpoint='get_match_tasks')
@login_required
def get_match_tasks(match_id):
    """
    Retrieve scheduled tasks for a specific match using enhanced logic.

    Parameters:
        match_id (str): The match identifier.

    Returns:
        JSON response with the scheduled tasks for the match.
    """
    try:
        # Try to call the enhanced task status logic directly
        try:
            from app.utils.task_status_helper import get_enhanced_match_task_status
            result = get_enhanced_match_task_status(int(match_id))
            response = jsonify(result)
            response.headers['Cache-Control'] = 'max-age=30, public'
            return response

        except ImportError:
            # Fallback to original monitoring logic if helper doesn't exist yet
            result = task_monitor.verify_scheduled_tasks(match_id)
            return jsonify(result)

    except Exception as e:
        logger.error(f"Error getting tasks for match {match_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/tasks/revoke', endpoint='revoke_task', methods=['POST'])
@login_required
@role_required('Global Admin')
def revoke_task():
    """
    Revoke a specific scheduled task and clean up its Redis key.

    Expects JSON payload with either:
    1. 'key' and 'task_id' (for Redis-based tasks)
    2. 'worker' and either 'task_name' or 'task_id' (for scheduled tasks on workers)

    Returns:
        JSON response indicating revocation status.
    """
    try:
        data = request.get_json()
        logger.info(f"Revoke task request payload: {data}")

        if not data:
            return jsonify({'success': False, 'error': 'No JSON payload provided'}), 400

        key = data.get('key')
        task_id = data.get('task_id')
        worker = data.get('worker')
        task_name = data.get('task_name')

        logger.info(f"Parsed parameters: key={key}, task_id={task_id}, worker={worker}, task_name={task_name}")

        # Check which mode we're operating in
        if key and task_id:
            # Mode 1: Revoke Redis-based task
            logger.info(f"Revoking task {task_id} and cleaning up Redis key {key}")
            celery.control.revoke(task_id, terminate=True)
            redis_client = get_safe_redis()
            redis_client.delete(key)
            with managed_session() as session:
                if 'thread' in key:
                    match_id = key.split(':')[1]
                    match = get_match(session, match_id)
                    if match:
                        match.thread_creation_time = None
                elif 'reporting' in key:
                    match_id = key.split(':')[1]
                    match = get_match(session, match_id)
                    if match:
                        match.live_reporting_scheduled = False
                        match.live_reporting_started = False
                        match.live_reporting_status = 'not_started'
            return jsonify({'success': True, 'message': f'Task {task_id} revoked and Redis key {key} removed'})

        elif worker:
            # Mode 2: Revoke a scheduled task on a worker
            return _revoke_worker_task(worker, task_id, task_name)

        else:
            return jsonify({'success': False, 'error': 'Missing required parameters. Need either (key and task_id) or (worker)'}), 400

    except Exception as e:
        logger.error(f"Error revoking task: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


def _revoke_worker_task(worker, task_id, task_name):
    """Helper function to revoke tasks on a specific worker."""
    logger.info(f"Revoking task on worker {worker}")

    # If we have a task_id, use it directly
    if task_id:
        try:
            celery.control.revoke(task_id, terminate=True, destination=[worker])
            logger.info(f"Directly revoked task {task_id} on worker {worker}")
            return jsonify({'success': True, 'message': f'Task {task_id} revoked on worker {worker}'})
        except Exception as e:
            logger.warning(f"Direct revoke failed, trying without destination: {e}")
            celery.control.revoke(task_id, terminate=True)
            logger.info(f"Revoked task {task_id} globally")
            return jsonify({'success': True, 'message': f'Task {task_id} revoked globally'})

    # No task_id - try to find and revoke scheduled tasks
    i = celery.control.inspect(timeout=3.0)
    scheduled = i.scheduled() or {}
    worker_tasks = scheduled.get(worker, [])

    if not worker_tasks:
        # Try additional methods
        active = i.active([worker]) or {}
        reserved = i.reserved([worker]) or {}
        worker_tasks = worker_tasks + active.get(worker, []) + reserved.get(worker, [])

    logger.info(f"Found {len(worker_tasks)} tasks on worker {worker}")

    revoked_count = 0
    task_ids = [task.get('id') for task in worker_tasks if task.get('id')]

    for tid in task_ids:
        try:
            celery.control.revoke(tid, terminate=True)
            revoked_count += 1
            logger.info(f"Revoked task {tid}")
        except Exception as e:
            logger.warning(f"Error revoking task {tid}: {e}")

    if revoked_count > 0:
        return jsonify({'success': True, 'message': f'Revoked {revoked_count} tasks on worker {worker}'})

    # Last resort - purge all queues
    try:
        result = celery.control.purge()
        logger.info(f"Purged all queues: {result}")
        return jsonify({'success': True, 'message': f'Purged all queues: {result}'})
    except Exception as e:
        logger.warning(f"Error purging all queues: {e}")
        return jsonify({'success': False, 'error': f'Failed to revoke tasks on worker {worker}'}), 500


@monitoring_bp.route('/tasks/revoke-all', endpoint='revoke_all_tasks', methods=['POST'])
@login_required
@role_required('Global Admin')
def revoke_all_tasks():
    """
    Revoke all scheduled tasks by cleaning up all Redis keys and updating match records.

    Returns:
        JSON response with the number of revoked tasks and any failures.
    """
    try:
        redis_client = get_safe_redis()

        # Step 1: Get all scheduler keys
        keys = redis_client.keys('match_scheduler:*')
        revoked_count = 0
        failed_tasks = []
        task_ids = []

        logger.info(f"Attempting to revoke {len(keys)} scheduled tasks")

        # Step 2: Process each key and collect task IDs
        for key in keys:
            try:
                key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                value = redis_client.get(key)
                if value:
                    value_str = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                    try:
                        task_data = json.loads(value_str)
                        task_id = task_data.get('task_id', value_str)
                    except:
                        task_id = value_str

                    if task_id and len(task_id) == 36:  # Valid UUID
                        task_ids.append(task_id)
                        logger.info(f"Found task {task_id} for key {key_str}")

                    redis_client.delete(key)
                    revoked_count += 1
                else:
                    redis_client.delete(key)
                    logger.info(f"Deleted empty key: {key_str}")

            except Exception as key_error:
                logger.error(f"Error processing key {key}: {key_error}")
                failed_tasks.append({'key': str(key), 'error': str(key_error)})

        # Step 3: Revoke all collected task IDs
        successfully_revoked = 0
        for task_id in task_ids:
            try:
                logger.info(f"Revoking task {task_id}")
                celery.control.revoke(task_id, terminate=True)
                successfully_revoked += 1
            except Exception as revoke_error:
                logger.error(f"Error revoking task {task_id}: {revoke_error}")
                failed_tasks.append({'task_id': task_id, 'error': str(revoke_error)})

        # Step 4: Additional cleanup - purge all queues
        try:
            logger.info("Purging all Celery queues")
            celery.control.purge()
        except Exception as purge_error:
            logger.warning(f"Error purging queues: {purge_error}")

        # Step 5: Reset match statuses in database
        try:
            with managed_session() as session:
                matches = session.query(MLSMatch).all()
                reset_count = 0
                for match in matches:
                    if (match.thread_creation_time or
                        match.live_reporting_scheduled or
                        match.live_reporting_started or
                        match.live_reporting_status != 'not_started'):

                        match.thread_creation_time = None
                        match.thread_creation_scheduled = False
                        match.live_reporting_scheduled = False
                        match.live_reporting_started = False
                        match.live_reporting_status = 'not_started'
                        reset_count += 1

                logger.info(f"Reset {reset_count} match statuses")
        except Exception as db_error:
            logger.error(f"Error resetting match statuses: {db_error}")
            failed_tasks.append({'error': f'Database reset failed: {str(db_error)}'})

        total_revoked = successfully_revoked + revoked_count
        message = f'Revoked {total_revoked} tasks ({successfully_revoked} task IDs, {revoked_count} Redis keys)'

        response_data = {
            'success': True,
            'message': message,
            'revoked_count': total_revoked,
            'task_ids_revoked': successfully_revoked,
            'redis_keys_cleaned': revoked_count
        }

        if failed_tasks:
            response_data['failed_tasks'] = failed_tasks
            response_data['warning'] = f'Some operations failed ({len(failed_tasks)} failures)'

        logger.info(f"Revoke all completed: {message}")
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error revoking all tasks: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/tasks/reschedule', endpoint='reschedule_task', methods=['POST'])
@login_required
@role_required('Global Admin')
def reschedule_task():
    """
    Reschedule a task by revoking the existing task and scheduling a new one.

    Expects JSON payload with key and task_id

    Returns:
        JSON response with new task ID and status.
    """
    try:
        data = request.get_json()
        key = data.get('key')
        task_id = data.get('task_id')
        if not key or not task_id:
            return jsonify({'success': False, 'error': 'Missing key or task_id'}), 400

        logger.info(f"Rescheduling task {task_id} for key {key}")
        match_id = key.split(':')[1]

        with managed_session() as session:
            match = get_match(session, match_id)
            if not match:
                return jsonify({'success': False, 'error': 'Match not found'}), 404

            celery.control.revoke(task_id, terminate=True)
            redis_client = get_safe_redis()
            redis_client.delete(key)

            if 'thread' in key:
                thread_time = match.date_time - timedelta(hours=48)
                new_task = force_create_mls_thread_task.apply_async(args=[match_id], eta=thread_time)
                match.thread_creation_time = thread_time
                redis_client.setex(key, 172800, new_task.id)
            else:
                reporting_time = match.date_time - timedelta(minutes=5)
                new_task = start_live_reporting.apply_async(args=[str(match_id)], eta=reporting_time)
                match.live_reporting_scheduled = True
                redis_client.setex(key, 172800, new_task.id)

        return jsonify({
            'success': True,
            'message': f'Task rescheduled successfully. New task ID: {new_task.id}',
            'new_task_id': new_task.id
        })
    except Exception as e:
        logger.error(f"Error rescheduling task {task_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/tasks/nuclear_reset', methods=['POST'], endpoint='nuclear_reset')
@login_required
@role_required('Global Admin')
def nuclear_reset():
    """
    Nuclear reset - completely restart the task system from scratch.

    This is the most aggressive approach to clear stuck tasks.
    """
    try:
        logger.warning("NUCLEAR RESET - Restarting entire task system")

        results = {
            'containers_restarted': 0,
            'redis_flushed': False,
            'details': []
        }

        # Step 1: Kill all worker containers
        try:
            import docker
            client = docker.from_env()

            containers_to_restart = [
                'celery-worker', 'celery-live-reporting-worker',
                'celery-discord-worker', 'celery-beat'
                # Note: celery-player-sync-worker removed - consolidated into celery-worker
            ]

            for container in client.containers.list():
                if any(name in container.name for name in containers_to_restart):
                    try:
                        logger.warning(f"KILLING container: {container.name}")
                        container.kill()
                        container.start()
                        results['containers_restarted'] += 1
                        results['details'].append(f"Killed and restarted {container.name}")
                    except Exception as e:
                        results['details'].append(f"Failed to restart {container.name}: {str(e)}")

        except Exception as e:
            results['details'].append(f"Docker operations failed: {str(e)}")

        # Step 2: Nuclear Redis cleanup
        try:
            redis_client = get_safe_redis()

            patterns = [
                'match_scheduler:*',
                'celery-*',
                '_kombu*',
                'live_reporting*',
                'scheduled_*'
            ]

            deleted_count = 0
            for pattern in patterns:
                try:
                    keys = redis_client.keys(pattern)
                    if keys:
                        redis_client.delete(*keys)
                        deleted_count += len(keys)
                        logger.warning(f"Deleted {len(keys)} keys matching {pattern}")
                except Exception as e:
                    results['details'].append(f"Pattern {pattern} cleanup failed: {str(e)}")

            results['redis_flushed'] = deleted_count > 0
            results['details'].append(f"Deleted {deleted_count} Redis keys")

        except Exception as e:
            results['details'].append(f"Redis cleanup failed: {str(e)}")

        # Step 3: Clear database scheduling flags
        try:
            with managed_session() as session:
                matches = session.query(MLSMatch).filter(
                    or_(
                        MLSMatch.live_reporting_scheduled == True,
                        MLSMatch.thread_creation_scheduled == True
                    )
                ).all()

                reset_count = 0
                for match in matches:
                    match.live_reporting_scheduled = False
                    match.thread_creation_scheduled = False
                    match.thread_creation_time = None
                    reset_count += 1

                session.commit()
                results['details'].append(f"Reset scheduling flags for {reset_count} matches")

        except Exception as e:
            results['details'].append(f"Database cleanup failed: {str(e)}")

        # Step 4: Wait and verify
        import time
        time.sleep(3)

        logger.warning(f"Nuclear reset completed: {results}")

        return jsonify({
            'success': True,
            'message': f"Nuclear reset completed. Restarted {results['containers_restarted']} containers, cleared Redis",
            'results': results
        })

    except Exception as e:
        logger.error(f"Nuclear reset failed: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@monitoring_bp.route('/inspect-task/<task_id>', endpoint='inspect_task')
@login_required
@role_required('Global Admin')
def inspect_task(task_id):
    """
    Get detailed information about a specific task.

    Parameters:
        task_id: The ID of the task to inspect.

    Returns:
        JSON response with task details.
    """
    try:
        task = AsyncResult(task_id, app=celery)

        result = {
            'id': task_id,
            'state': task.state,
            'ready': task.ready(),
            'successful': task.successful() if task.ready() else None,
            'result': str(task.result) if task.ready() else None,
            'traceback': str(task.traceback) if task.failed() else None
        }

        # Try to get additional info from Redis
        redis_client = get_safe_redis()
        keys = redis_client.keys('*')
        related_keys = []

        for key in keys:
            key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
            value = redis_client.get(key)
            if value:
                value_str = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                if task_id in value_str:
                    related_keys.append({
                        'key': key_str,
                        'value': value_str,
                        'ttl': redis_client.ttl(key)
                    })

        result['related_redis_keys'] = related_keys

        # Try to get task info from workers
        i = celery.control.inspect(timeout=1.0)
        active = i.active() or {}
        scheduled = i.scheduled() or {}
        reserved = i.reserved() or {}

        result['active_on'] = []
        result['scheduled_on'] = []
        result['reserved_on'] = []

        for worker, tasks in active.items():
            for t in tasks:
                if t.get('id') == task_id:
                    result['active_on'].append({'worker': worker, 'task': t})

        for worker, tasks in scheduled.items():
            for t in tasks:
                if t.get('id') == task_id:
                    result['scheduled_on'].append({'worker': worker, 'task': t})

        for worker, tasks in reserved.items():
            for t in tasks:
                if t.get('id') == task_id:
                    result['reserved_on'].append({'worker': worker, 'task': t})

        return jsonify({'success': True, 'task': result})
    except Exception as e:
        logger.error(f"Error inspecting task {task_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/cleanup-orphaned-tasks', endpoint='cleanup_orphaned_tasks', methods=['POST'])
@login_required
@role_required('Global Admin')
def cleanup_orphaned_tasks():
    """
    Cleanup orphaned tasks that might be stuck in Redis or in the worker queues.

    Returns:
        JSON response with cleanup status and details.
    """
    try:
        redis_client = get_safe_redis()
        scheduler_keys = redis_client.keys('match_scheduler:*')
        cleaned_keys = []

        for key in scheduler_keys:
            try:
                key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                parts = key_str.split(':')

                if len(parts) != 3:
                    redis_client.delete(key)
                    cleaned_keys.append(key_str)
                    continue

                value = redis_client.get(key)
                if not value:
                    redis_client.delete(key)
                    cleaned_keys.append(key_str)
                    continue

                task_id = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                if len(task_id) != 36:
                    redis_client.delete(key)
                    cleaned_keys.append(key_str)
                    continue

                task = AsyncResult(task_id, app=celery)
                if task.state in ('SUCCESS', 'FAILURE', 'REVOKED'):
                    redis_client.delete(key)
                    cleaned_keys.append(key_str)
            except Exception as e:
                logger.warning(f"Error cleaning up key {key}: {e}")

        # Check for database inconsistencies
        match_ids = []
        try:
            with managed_session() as session:
                from sqlalchemy import text
                table_exists = session.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'mls_match'
                    )
                """)).scalar()

                if table_exists:
                    updated_matches = session.execute(text("""
                        UPDATE mls_match
                        SET live_reporting_scheduled = false,
                            live_reporting_started = false,
                            live_reporting_status = 'not_started'
                        WHERE live_reporting_status IN ('preparing', 'scheduled')
                        AND date_time < NOW() - INTERVAL '3 hours'
                        RETURNING id
                    """))
                    match_ids = [row[0] for row in updated_matches]
        except Exception as db_error:
            logger.warning(f"Error updating match statuses: {db_error}")

        return jsonify({
            'success': True,
            'cleaned_redis_keys': len(cleaned_keys),
            'cleaned_keys': cleaned_keys,
            'reset_matches': len(match_ids),
            'match_ids': match_ids
        })
    except Exception as e:
        logger.error(f"Error cleaning up orphaned tasks: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
