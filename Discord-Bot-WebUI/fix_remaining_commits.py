#!/usr/bin/env python3
"""
Script to fix all remaining unprotected session.commit() calls in the codebase.
This script will wrap each commit in a try-except block with proper error handling.
"""

import os
import re
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_commit_in_file(file_path, commit_patterns):
    """
    Fix unprotected session.commit() calls in a single file.
    
    Args:
        file_path (str): Path to the file to fix
        commit_patterns (list): List of patterns to identify commits that need fixing
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        changes_made = 0
        
        # Pattern to find unprotected session.commit() calls
        # This looks for commits that are NOT already inside a try block
        commit_pattern = r'(\s+)((?:session|db_session|g\.db_session)\.commit\(\))'
        
        lines = content.split('\n')
        new_lines = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Check if this line contains a commit
            commit_match = re.search(commit_pattern, line)
            if commit_match:
                indent = commit_match.group(1)
                commit_call = commit_match.group(2)
                
                # Check if this commit is already protected
                # Look backwards for try/except blocks
                already_protected = False
                for j in range(max(0, i-10), i):
                    if 'try:' in lines[j] and len(lines[j]) - len(lines[j].lstrip()) <= len(indent):
                        already_protected = True
                        break
                
                if not already_protected:
                    # Replace the commit line with a try-except block
                    session_var = commit_call.split('.')[0]
                    if session_var == 'g':
                        session_var = 'g.db_session'
                    
                    new_lines.append(f"{indent}try:")
                    new_lines.append(f"{indent}    {commit_call}")
                    
                    # Look ahead for what comes after the commit
                    next_line_idx = i + 1
                    success_actions = []
                    
                    # Collect lines that should be in the try block
                    while next_line_idx < len(lines):
                        next_line = lines[next_line_idx]
                        if not next_line.strip():
                            next_line_idx += 1
                            continue
                        
                        # Check if this line should be in the try block
                        if any(keyword in next_line for keyword in ['show_success', 'logger.info', 'return redirect', 'return jsonify']):
                            success_actions.append(next_line)
                            next_line_idx += 1
                        else:
                            break
                    
                    # Add success actions to try block
                    for action in success_actions:
                        new_lines.append(action)
                    
                    # Add except block
                    new_lines.append(f"{indent}except Exception as e:")
                    new_lines.append(f"{indent}    {session_var}.rollback()")
                    new_lines.append(f"{indent}    logger.exception(f\"Database error: {{str(e)}}\")")
                    
                    # Add appropriate error handling based on context
                    if any('return jsonify' in action for action in success_actions):
                        new_lines.append(f"{indent}    return jsonify({{'success': False, 'message': 'Database error'}}), 500")
                    elif any('show_success' in action for action in success_actions):
                        new_lines.append(f"{indent}    show_error('Database error occurred.')")
                    
                    # Skip the original commit line and processed success actions
                    i = next_line_idx
                    changes_made += 1
                    continue
            
            new_lines.append(line)
            i += 1
        
        if changes_made > 0:
            # Write the modified content back
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(new_lines))
            
            logger.info(f"Fixed {changes_made} unprotected commits in {file_path}")
            return changes_made
        else:
            logger.info(f"No unprotected commits found in {file_path}")
            return 0
            
    except Exception as e:
        logger.error(f"Error processing {file_path}: {e}")
        return 0

def main():
    """
    Main function to fix all files with unprotected commits.
    """
    # Files that need fixing based on our analysis
    files_to_fix = [
        '/mnt/c/Users/geman/source/repos/ECS-Discord-Bot/Discord-Bot-WebUI/app/admin_routes.py',
        '/mnt/c/Users/geman/source/repos/ECS-Discord-Bot/Discord-Bot-WebUI/app/teams_helpers.py',
        '/mnt/c/Users/geman/source/repos/ECS-Discord-Bot/Discord-Bot-WebUI/app/user_management.py',
        '/mnt/c/Users/geman/source/repos/ECS-Discord-Bot/Discord-Bot-WebUI/app/admin_helpers.py',
        '/mnt/c/Users/geman/source/repos/ECS-Discord-Bot/Discord-Bot-WebUI/app/players.py',
        '/mnt/c/Users/geman/source/repos/ECS-Discord-Bot/Discord-Bot-WebUI/app/teams.py',
        '/mnt/c/Users/geman/source/repos/ECS-Discord-Bot/Discord-Bot-WebUI/app/publeague.py',
    ]
    
    total_fixes = 0
    
    for file_path in files_to_fix:
        if os.path.exists(file_path):
            fixes = fix_commit_in_file(file_path, [])
            total_fixes += fixes
        else:
            logger.warning(f"File not found: {file_path}")
    
    logger.info(f"Total fixes applied: {total_fixes}")
    
    if total_fixes > 0:
        logger.info("All unprotected session.commit() calls have been fixed!")
        logger.info("The database operations should now provide proper error handling and logging.")
    else:
        logger.info("No unprotected commits found to fix.")

if __name__ == "__main__":
    main()