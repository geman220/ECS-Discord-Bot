#!/usr/bin/env python3
"""
Validate Scheduled Messages and Celery Queue Status

This script checks:
1. What scheduled messages are in the database
2. If the Celery beat schedule is configured correctly
3. What tasks are actually queued in Celery
4. The status of the process_scheduled_messages periodic task
"""

import os
import sys
from datetime import datetime, timedelta
import pytz
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from celery import Celery
from tabulate import tabulate
from colorama import init, Fore, Style

# Initialize colorama for colored output
init(autoreset=True)

# Add the app directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import app configuration
from app.config import Config
from app.models import ScheduledMessage, Match
from app.models.communication import ScheduledMessage as CommScheduledMessage

def get_db_session():
    """Create a database session."""
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    Session = sessionmaker(bind=engine)
    return Session()

def get_celery_app():
    """Get the Celery app instance."""
    celery = Celery('app')
    celery.config_from_object('app.config.celery_config:CeleryConfig')
    return celery

def check_scheduled_messages(session):
    """Check scheduled messages in the database."""
    print(f"\n{Fore.CYAN}{'='*80}")
    print(f"{Fore.CYAN}SCHEDULED MESSAGES IN DATABASE")
    print(f"{Fore.CYAN}{'='*80}\n")
    
    # Get timezone
    pst = pytz.timezone('America/Los_Angeles')
    now = datetime.now(pst)
    
    # Query scheduled messages
    messages = session.query(ScheduledMessage).filter(
        ScheduledMessage.status.in_(['PENDING', 'QUEUED'])
    ).order_by(ScheduledMessage.scheduled_send_time).all()
    
    if not messages:
        print(f"{Fore.YELLOW}No pending or queued messages found in database.")
        return []
    
    # Prepare data for table
    table_data = []
    upcoming_messages = []
    
    for msg in messages:
        # Convert UTC to PST for display
        send_time = msg.scheduled_send_time
        if send_time.tzinfo is None:
            send_time = pytz.utc.localize(send_time)
        send_time_pst = send_time.astimezone(pst)
        
        # Calculate time until sending
        time_diff = send_time_pst - now
        hours_until = time_diff.total_seconds() / 3600
        
        # Get match info
        match_info = "N/A"
        if msg.match:
            match_date = msg.match.date
            if isinstance(match_date, datetime):
                match_date_str = match_date.strftime("%Y-%m-%d")
            else:
                match_date_str = str(match_date)
            match_info = f"{match_date_str}"
            if hasattr(msg.match, 'home_team') and hasattr(msg.match, 'away_team'):
                if msg.match.home_team and msg.match.away_team:
                    match_info += f"\n{msg.match.home_team.name} vs {msg.match.away_team.name}"
        
        # Determine if this should be sent soon
        should_send = hours_until <= 0
        status_color = Fore.GREEN if should_send else (Fore.YELLOW if hours_until < 24 else Fore.WHITE)
        
        table_data.append([
            msg.id,
            msg.status,
            send_time_pst.strftime("%Y-%m-%d %H:%M PST"),
            f"{hours_until:.1f} hrs" if hours_until > 0 else f"{status_color}READY TO SEND",
            match_info,
            msg.message_type or "standard"
        ])
        
        if hours_until <= 72:  # Messages in next 3 days
            upcoming_messages.append({
                'id': msg.id,
                'send_time': send_time_pst,
                'hours_until': hours_until,
                'match_info': match_info,
                'status': msg.status
            })
    
    # Print table
    headers = ["ID", "Status", "Scheduled Send Time", "Time Until", "Match Info", "Type"]
    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    
    # Summary
    print(f"\n{Fore.GREEN}Summary:")
    print(f"  Total pending/queued messages: {len(messages)}")
    ready_count = sum(1 for m in messages if (m.scheduled_send_time <= datetime.utcnow()))
    if ready_count > 0:
        print(f"  {Fore.YELLOW}Messages ready to send: {ready_count}")
    
    return upcoming_messages

def check_celery_beat_schedule(celery_app):
    """Check if Celery beat schedule is configured correctly."""
    print(f"\n{Fore.CYAN}{'='*80}")
    print(f"{Fore.CYAN}CELERY BEAT SCHEDULE STATUS")
    print(f"{Fore.CYAN}{'='*80}\n")
    
    try:
        # Check if the beat schedule includes our task
        from app.config.celery_config import CeleryConfig
        beat_schedule = CeleryConfig.beat_schedule
        
        # Look for process-scheduled-messages task
        if 'process-scheduled-messages' in beat_schedule:
            task_config = beat_schedule['process-scheduled-messages']
            print(f"{Fore.GREEN}✓ 'process-scheduled-messages' task is configured in beat schedule")
            print(f"  Task: {task_config['task']}")
            print(f"  Schedule: {task_config['schedule']} (every 5 minutes)")
            print(f"  Queue: {task_config['options'].get('queue', 'default')}")
            return True
        else:
            print(f"{Fore.RED}✗ 'process-scheduled-messages' task NOT found in beat schedule!")
            return False
            
    except Exception as e:
        print(f"{Fore.RED}Error checking beat schedule: {e}")
        return False

def check_celery_workers_and_queues(celery_app):
    """Check Celery workers and queue status."""
    print(f"\n{Fore.CYAN}{'='*80}")
    print(f"{Fore.CYAN}CELERY WORKERS AND QUEUE STATUS")
    print(f"{Fore.CYAN}{'='*80}\n")
    
    try:
        # Get inspect instance
        inspect = celery_app.control.inspect()
        
        # Check active workers
        active_workers = inspect.active()
        if active_workers:
            print(f"{Fore.GREEN}Active Workers:")
            for worker, tasks in active_workers.items():
                print(f"  {worker}: {len(tasks)} active tasks")
        else:
            print(f"{Fore.YELLOW}No active workers found!")
        
        # Check scheduled tasks (tasks waiting to be executed)
        scheduled = inspect.scheduled()
        if scheduled:
            print(f"\n{Fore.GREEN}Scheduled Tasks (in Celery):")
            for worker, tasks in scheduled.items():
                print(f"  {worker}: {len(tasks)} scheduled tasks")
                # Show first few scheduled tasks
                for task in tasks[:3]:
                    task_name = task.get('request', {}).get('name', 'Unknown')
                    eta = task.get('eta', 'No ETA')
                    print(f"    - {task_name} (ETA: {eta})")
        else:
            print(f"\n{Fore.YELLOW}No scheduled tasks in Celery queues")
        
        # Check reserved tasks (tasks that have been picked up by workers)
        reserved = inspect.reserved()
        if reserved:
            print(f"\n{Fore.GREEN}Reserved Tasks (picked up by workers):")
            for worker, tasks in reserved.items():
                print(f"  {worker}: {len(tasks)} reserved tasks")
                for task in tasks[:3]:
                    task_name = task.get('name', 'Unknown')
                    print(f"    - {task_name}")
        
        # Check registered tasks
        registered = inspect.registered()
        if registered:
            for worker, tasks in registered.items():
                if 'app.tasks.tasks_rsvp.process_scheduled_messages' in tasks:
                    print(f"\n{Fore.GREEN}✓ process_scheduled_messages task is registered on {worker}")
                    break
        
        return True
        
    except Exception as e:
        print(f"{Fore.RED}Error connecting to Celery: {e}")
        print(f"{Fore.YELLOW}Make sure Celery workers are running!")
        return False

def check_recent_task_execution(session):
    """Check when process_scheduled_messages was last executed."""
    print(f"\n{Fore.CYAN}{'='*80}")
    print(f"{Fore.CYAN}RECENT TASK EXECUTION HISTORY")
    print(f"{Fore.CYAN}{'='*80}\n")
    
    try:
        # Check recently sent messages
        recent_sent = session.query(ScheduledMessage).filter(
            ScheduledMessage.status == 'SENT',
            ScheduledMessage.sent_time >= datetime.utcnow() - timedelta(hours=24)
        ).order_by(ScheduledMessage.sent_time.desc()).limit(5).all()
        
        if recent_sent:
            print(f"{Fore.GREEN}Recently sent messages (last 24 hours):")
            for msg in recent_sent:
                sent_time = msg.sent_time
                if sent_time:
                    if sent_time.tzinfo is None:
                        sent_time = pytz.utc.localize(sent_time)
                    sent_time_pst = sent_time.astimezone(pytz.timezone('America/Los_Angeles'))
                    print(f"  - Message {msg.id}: Sent at {sent_time_pst.strftime('%Y-%m-%d %H:%M PST')}")
        else:
            print(f"{Fore.YELLOW}No messages sent in the last 24 hours")
        
        # Check failed messages
        failed = session.query(ScheduledMessage).filter(
            ScheduledMessage.status == 'FAILED'
        ).count()
        
        if failed > 0:
            print(f"\n{Fore.RED}Warning: {failed} failed messages in database!")
            
    except Exception as e:
        print(f"{Fore.RED}Error checking execution history: {e}")

def provide_recommendations(upcoming_messages, celery_status):
    """Provide recommendations based on the validation results."""
    print(f"\n{Fore.CYAN}{'='*80}")
    print(f"{Fore.CYAN}RECOMMENDATIONS")
    print(f"{Fore.CYAN}{'='*80}\n")
    
    # Check for messages that should have been sent
    overdue = [m for m in upcoming_messages if m['hours_until'] <= 0 and m['status'] == 'PENDING']
    
    if overdue:
        print(f"{Fore.YELLOW}⚠ Found {len(overdue)} messages that should have been sent!")
        print(f"{Fore.YELLOW}  These messages are past their scheduled time but still PENDING.")
        print(f"\n{Fore.GREEN}Recommended Actions:")
        print("  1. Check if Celery beat is running: `docker-compose ps celerybeat`")
        print("  2. Check if Celery workers are running: `docker-compose ps celery`")
        print("  3. Force process messages: Click 'Process Messages Now' in admin panel")
        print("  4. Check logs: `docker-compose logs celery celerybeat`")
    
    if not celery_status:
        print(f"\n{Fore.RED}⚠ Celery connection issues detected!")
        print(f"{Fore.GREEN}Recommended Actions:")
        print("  1. Ensure Redis is running: `docker-compose ps redis`")
        print("  2. Restart Celery services: `docker-compose restart celery celerybeat`")
        print("  3. Check Celery logs for errors: `docker-compose logs celery`")
    
    # Messages coming up soon
    soon = [m for m in upcoming_messages if 0 < m['hours_until'] <= 24]
    if soon:
        print(f"\n{Fore.CYAN}ℹ {len(soon)} messages scheduled in the next 24 hours")
        for msg in soon[:3]:
            print(f"  - Message {msg['id']}: in {msg['hours_until']:.1f} hours")
    
    print(f"\n{Fore.GREEN}How the System Works:")
    print("1. Scheduled messages are stored in the database with status='PENDING'")
    print("2. Every 5 minutes, Celery beat triggers 'process_scheduled_messages'")
    print("3. This task checks for PENDING messages where scheduled_send_time <= now")
    print("4. It queues these messages for sending and updates status to 'QUEUED'")
    print("5. The send task sends the message and updates status to 'SENT' or 'FAILED'")

def main():
    """Main validation function."""
    print(f"{Fore.CYAN}Starting Scheduled Messages Validation...")
    print(f"{Fore.CYAN}Current Time: {datetime.now(pytz.timezone('America/Los_Angeles')).strftime('%Y-%m-%d %H:%M PST')}")
    
    # Get database session
    session = get_db_session()
    
    # Get Celery app
    celery_app = get_celery_app()
    
    try:
        # 1. Check scheduled messages in database
        upcoming = check_scheduled_messages(session)
        
        # 2. Check Celery beat schedule configuration
        beat_ok = check_celery_beat_schedule(celery_app)
        
        # 3. Check Celery workers and queues
        celery_ok = check_celery_workers_and_queues(celery_app)
        
        # 4. Check recent execution history
        check_recent_task_execution(session)
        
        # 5. Provide recommendations
        provide_recommendations(upcoming, celery_ok)
        
        print(f"\n{Fore.CYAN}{'='*80}")
        print(f"{Fore.GREEN}Validation Complete!")
        print(f"{Fore.CYAN}{'='*80}")
        
    finally:
        session.close()

if __name__ == "__main__":
    main()