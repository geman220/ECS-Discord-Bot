#!/usr/bin/env python3
"""
Help Topics Import Script

This script helps import help topics from the help_topics_import directory
into the application database. It can be run independently or used as a reference.

Usage:
    python import_help_topics.py

Requirements:
    - Flask app must be running or available
    - Database must be accessible
    - Help topic markdown files must be in help_topics_import/ directory
"""

import os
import sys
from pathlib import Path

# Add the app directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

def import_help_topics():
    """Import help topics from markdown files"""
    try:
        from app import create_app
        from app.models import HelpTopic, Role, db
        
        # Create Flask app context
        app = create_app()
        
        with app.app_context():
            import_directory = Path(__file__).parent / 'help_topics_import'
            
            if not import_directory.exists():
                print(f"Import directory {import_directory} does not exist")
                return False
            
            md_files = list(import_directory.glob('*.md'))
            if not md_files:
                print(f"No markdown files found in {import_directory}")
                return False
            
            success_count = 0
            error_count = 0
            
            for md_file in md_files:
                try:
                    with open(md_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Parse the markdown content
                    lines = content.split('\n')
                    title = None
                    role_access = None
                    
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
                        print(f"Error: {md_file.name} - No title found")
                        error_count += 1
                        continue
                    
                    # Check if topic already exists
                    existing_topic = HelpTopic.query.filter_by(title=title).first()
                    if existing_topic:
                        print(f"Skipping: {md_file.name} - Topic '{title}' already exists")
                        continue
                    
                    # Create new help topic
                    topic = HelpTopic(
                        title=title,
                        markdown_content=content
                    )
                    
                    # Assign roles
                    if role_access:
                        role_names = [name.strip() for name in role_access.split(',')]
                        roles = Role.query.filter(Role.name.in_(role_names)).all()
                        topic.allowed_roles = roles
                        print(f"Assigned roles {role_names} to '{title}'")
                    else:
                        # Default to Global Admin
                        admin_role = Role.query.filter_by(name='Global Admin').first()
                        if admin_role:
                            topic.allowed_roles = [admin_role]
                            print(f"Assigned default Global Admin role to '{title}'")
                    
                    db.session.add(topic)
                    success_count += 1
                    print(f"Success: {md_file.name} - Created '{title}'")
                    
                except Exception as e:
                    print(f"Error: {md_file.name} - {str(e)}")
                    error_count += 1
            
            if success_count > 0:
                try:
                    db.session.commit()
                    print(f"\nImport completed successfully!")
                    print(f"✓ {success_count} topics imported")
                    if error_count > 0:
                        print(f"✗ {error_count} topics had errors")
                except Exception as e:
                    db.session.rollback()
                    print(f"Error saving to database: {str(e)}")
                    return False
            else:
                print("No topics were imported")
                return False
            
            return True
            
    except ImportError as e:
        print(f"Error importing Flask app: {str(e)}")
        print("Make sure the Flask app is properly configured")
        return False
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return False

def list_help_topics():
    """List existing help topics in the database"""
    try:
        from app import create_app
        from app.models import HelpTopic
        
        app = create_app()
        with app.app_context():
            topics = HelpTopic.query.all()
            
            if not topics:
                print("No help topics found in database")
                return
            
            print(f"\nExisting Help Topics ({len(topics)}):")
            print("-" * 50)
            for topic in topics:
                roles = [role.name for role in topic.allowed_roles]
                print(f"• {topic.title}")
                print(f"  Roles: {', '.join(roles)}")
                print(f"  Created: {topic.created_at}")
                print()
                
    except Exception as e:
        print(f"Error listing help topics: {str(e)}")

if __name__ == "__main__":
    print("Help Topics Import Script")
    print("=" * 30)
    
    if len(sys.argv) > 1 and sys.argv[1] == 'list':
        list_help_topics()
    else:
        print("Importing help topics...")
        success = import_help_topics()
        
        if success:
            print("\n" + "=" * 50)
            print("Import process completed successfully!")
            print("\nTo view the imported topics:")
            print("1. Go to your web application")
            print("2. Navigate to /help/admin")
            print("3. Review the imported help topics")
            print("\nTo list existing topics, run:")
            print("python import_help_topics.py list")
        else:
            print("\nImport process failed. Please check the errors above.")
            sys.exit(1)