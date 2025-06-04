#!/usr/bin/env python3
# cleanup_logs.py

"""
Log Cleanup Script

This script provides manual log cleanup and maintenance for the ECS Discord Bot.
It can be run manually or scheduled as a cron job.
"""

import os
import sys
import logging
from pathlib import Path

# Add the app directory to the Python path
script_dir = Path(__file__).parent
app_dir = script_dir / "app"
sys.path.insert(0, str(app_dir))

from app.log_management import LogManager, run_log_maintenance, get_log_summary


def main():
    """Main function to handle command line arguments and run log maintenance."""
    
    # Set up basic logging for this script
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    
    # Change to the application directory
    os.chdir(script_dir)
    
    if len(sys.argv) == 1:
        # No arguments - show help
        print_help()
        return
    
    command = sys.argv[1].lower()
    
    try:
        if command == "clean":
            print("🧹 Running log cleanup...")
            stats = run_log_maintenance()
            print_stats(stats)
            
        elif command == "summary":
            print("📊 Log file summary:")
            summary = get_log_summary()
            print_summary(summary)
            
        elif command == "emergency":
            print("🚨 Emergency cleanup - removing large logs immediately...")
            emergency_cleanup()
            
        elif command == "status":
            print("📈 Current log status:")
            check_log_status()
            
        else:
            print(f"❌ Unknown command: {command}")
            print_help()
            
    except Exception as e:
        logger.error(f"Error running command '{command}': {e}")
        sys.exit(1)


def print_help():
    """Print help information."""
    print("""
🔧 ECS Discord Bot Log Cleanup Tool

Usage: python cleanup_logs.py <command>

Commands:
  clean      - Run automatic log cleanup and rotation
  summary    - Show summary of all log files
  emergency  - Emergency cleanup of very large log files
  status     - Check current log file status
  help       - Show this help message

Examples:
  python cleanup_logs.py clean
  python cleanup_logs.py summary
  python cleanup_logs.py emergency
""")


def print_stats(stats):
    """Print cleanup statistics in a readable format."""
    print(f"✅ Cleanup completed successfully!")
    print(f"   📁 Files rotated: {stats['files_rotated']}")
    print(f"   🗑️  Files deleted: {stats['files_deleted']}")
    print(f"   📦 Files compressed: {stats['files_compressed']}")
    print(f"   💾 Space freed: {stats['space_freed_mb']:.1f} MB")
    
    if stats['errors']:
        print(f"   ⚠️  Errors: {len(stats['errors'])}")
        for error in stats['errors']:
            print(f"      - {error}")


def print_summary(summary):
    """Print log summary in a readable format."""
    print(f"📊 Total files: {summary['total_files']}")
    print(f"💾 Total size: {summary['total_size_mb']:.1f} MB")
    print("\n📄 Individual files:")
    
    for file_info in summary['files']:
        size_str = f"{file_info['size_mb']:.1f} MB"
        age_str = f"{file_info['age_days']} days"
        
        status = []
        if file_info['needs_rotation']:
            status.append("🔄 NEEDS ROTATION")
        if file_info['needs_cleanup']:
            status.append("🗑️ NEEDS CLEANUP")
        
        status_str = " " + " ".join(status) if status else ""
        
        print(f"   📄 {file_info['name']:<25} {size_str:<10} {age_str:<10}{status_str}")


def emergency_cleanup():
    """Emergency cleanup for very large log files."""
    logger = logging.getLogger(__name__)
    
    # Files larger than this will be truncated
    EMERGENCY_SIZE_MB = 100
    
    script_dir = Path(__file__).parent
    log_files = list(script_dir.glob("*.log"))
    
    cleaned_files = 0
    space_freed = 0
    
    for log_file in log_files:
        try:
            file_size_mb = log_file.stat().st_size / (1024 * 1024)
            
            if file_size_mb > EMERGENCY_SIZE_MB:
                print(f"🚨 Emergency cleaning: {log_file.name} ({file_size_mb:.1f} MB)")
                
                # Keep only the last 1000 lines
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                
                if len(lines) > 1000:
                    # Keep last 1000 lines
                    last_lines = lines[-1000:]
                    
                    # Write back to file
                    with open(log_file, 'w', encoding='utf-8') as f:
                        f.writelines(last_lines)
                    
                    new_size_mb = log_file.stat().st_size / (1024 * 1024)
                    freed_mb = file_size_mb - new_size_mb
                    
                    print(f"   ✅ Reduced from {file_size_mb:.1f} MB to {new_size_mb:.1f} MB")
                    print(f"   💾 Freed {freed_mb:.1f} MB")
                    
                    cleaned_files += 1
                    space_freed += freed_mb
                
        except Exception as e:
            logger.error(f"Error cleaning {log_file}: {e}")
    
    if cleaned_files > 0:
        print(f"\n🎉 Emergency cleanup completed!")
        print(f"   📁 Files cleaned: {cleaned_files}")
        print(f"   💾 Total space freed: {space_freed:.1f} MB")
    else:
        print("✅ No files needed emergency cleanup")


def check_log_status():
    """Check and report current log file status."""
    script_dir = Path(__file__).parent
    log_files = list(script_dir.glob("*.log"))
    
    total_size = 0
    large_files = []
    old_files = []
    
    print("📈 Current log status:\n")
    
    for log_file in log_files:
        try:
            file_size_mb = log_file.stat().st_size / (1024 * 1024)
            file_age_days = (Path(__file__).stat().st_mtime - log_file.stat().st_mtime) / (24 * 3600)
            
            total_size += file_size_mb
            
            # Check for issues
            if file_size_mb > 50:
                large_files.append((log_file.name, file_size_mb))
            
            if file_age_days > 30:
                old_files.append((log_file.name, file_age_days))
                
        except Exception as e:
            print(f"   ⚠️ Error checking {log_file}: {e}")
    
    print(f"📊 Total log size: {total_size:.1f} MB")
    print(f"📁 Total log files: {len(log_files)}")
    
    if large_files:
        print(f"\n⚠️ Large files (>50MB):")
        for filename, size in large_files:
            print(f"   📄 {filename}: {size:.1f} MB")
    
    if old_files:
        print(f"\n⚠️ Old files (>30 days):")
        for filename, age in old_files:
            print(f"   📄 {filename}: {age:.0f} days old")
    
    if not large_files and not old_files:
        print("\n✅ All log files are within normal parameters")
    else:
        print(f"\n💡 Recommendation: Run 'python cleanup_logs.py clean' to clean up these files")


if __name__ == "__main__":
    main()