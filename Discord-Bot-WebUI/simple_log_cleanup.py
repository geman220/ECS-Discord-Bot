#!/usr/bin/env python3
# simple_log_cleanup.py

"""
Simple Log Cleanup Script

This script provides immediate log cleanup without dependencies.
Run this to clean up your large log files.
"""

import os
import sys
import gzip
import shutil
from pathlib import Path
from datetime import datetime


def emergency_cleanup():
    """Emergency cleanup for very large log files."""
    # Files larger than this will be truncated
    EMERGENCY_SIZE_MB = 50
    
    script_dir = Path(__file__).parent
    log_files = list(script_dir.glob("*.log"))
    
    cleaned_files = 0
    space_freed = 0
    
    print("🚨 Emergency Log Cleanup Starting...")
    print(f"Looking for log files larger than {EMERGENCY_SIZE_MB} MB\n")
    
    for log_file in log_files:
        try:
            file_size_mb = log_file.stat().st_size / (1024 * 1024)
            
            if file_size_mb > EMERGENCY_SIZE_MB:
                print(f"🔍 Found large file: {log_file.name} ({file_size_mb:.1f} MB)")
                
                # Backup the original file
                backup_path = log_file.with_suffix(f'.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}.gz')
                
                print(f"📦 Creating compressed backup: {backup_path.name}")
                with open(log_file, 'rb') as f_in:
                    with gzip.open(backup_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                
                # Keep only the last 1000 lines of the original
                print(f"✂️  Truncating to last 1000 lines...")
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                
                if len(lines) > 1000:
                    # Keep last 1000 lines plus a header
                    header = f"# Log file truncated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    header += f"# Original file had {len(lines)} lines, kept last 1000\n"
                    header += f"# Full backup saved as {backup_path.name}\n\n"
                    
                    last_lines = [header] + lines[-1000:]
                    
                    # Write back to file
                    with open(log_file, 'w', encoding='utf-8') as f:
                        f.writelines(last_lines)
                    
                    new_size_mb = log_file.stat().st_size / (1024 * 1024)
                    freed_mb = file_size_mb - new_size_mb
                    
                    print(f"   ✅ Reduced from {file_size_mb:.1f} MB to {new_size_mb:.1f} MB")
                    print(f"   💾 Freed {freed_mb:.1f} MB\n")
                    
                    cleaned_files += 1
                    space_freed += freed_mb
                else:
                    print(f"   ℹ️  File only has {len(lines)} lines, no truncation needed\n")
                
        except Exception as e:
            print(f"❌ Error cleaning {log_file}: {e}")
    
    if cleaned_files > 0:
        print(f"🎉 Emergency cleanup completed!")
        print(f"   📁 Files cleaned: {cleaned_files}")
        print(f"   💾 Total space freed: {space_freed:.1f} MB")
        print(f"   📦 Backups created for all cleaned files")
    else:
        print("✅ No files needed emergency cleanup")


def show_status():
    """Show current log file status."""
    script_dir = Path(__file__).parent
    log_files = list(script_dir.glob("*.log"))
    
    total_size = 0
    large_files = []
    
    print("📊 Current Log File Status:\n")
    
    for log_file in log_files:
        try:
            file_size_mb = log_file.stat().st_size / (1024 * 1024)
            total_size += file_size_mb
            
            size_str = f"{file_size_mb:.1f} MB"
            
            status = ""
            if file_size_mb > 50:
                status = " 🔴 LARGE"
                large_files.append((log_file.name, file_size_mb))
            elif file_size_mb > 25:
                status = " 🟡 MEDIUM"
            else:
                status = " 🟢 OK"
            
            print(f"   📄 {log_file.name:<25} {size_str:<10}{status}")
                
        except Exception as e:
            print(f"   ❌ Error checking {log_file}: {e}")
    
    print(f"\n📊 Summary:")
    print(f"   📁 Total files: {len(log_files)}")
    print(f"   💾 Total size: {total_size:.1f} MB")
    
    if large_files:
        print(f"   ⚠️ Large files: {len(large_files)}")
        print(f"\n💡 Run 'python3 simple_log_cleanup.py emergency' to clean up large files")
    else:
        print(f"   ✅ All files are reasonable size")


def main():
    """Main function."""
    if len(sys.argv) == 1:
        print("""
🔧 Simple Log Cleanup Tool

Usage: python3 simple_log_cleanup.py <command>

Commands:
  status     - Show current log file sizes
  emergency  - Clean up large log files (>50MB)
  help       - Show this help

Example:
  python3 simple_log_cleanup.py status
  python3 simple_log_cleanup.py emergency
""")
        return
    
    command = sys.argv[1].lower()
    
    if command == "emergency":
        emergency_cleanup()
    elif command == "status":
        show_status()
    elif command == "help":
        main()  # Show help
    else:
        print(f"❌ Unknown command: {command}")
        print("Use 'help' to see available commands")


if __name__ == "__main__":
    main()