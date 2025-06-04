# app/log_management.py

"""
Log Management Module

This module provides automatic log cleanup, rotation, and configuration
for managing log file sizes and maintaining system performance.
"""

import logging
import os
import glob
import gzip
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any

# Set up module logger
logger = logging.getLogger(__name__)


class LogManager:
    """Manages log files with automatic cleanup and rotation."""
    
    def __init__(self, log_directory: str = ".", config: Dict[str, Any] = None):
        """
        Initialize the LogManager.
        
        Args:
            log_directory: Directory containing log files
            config: Configuration dictionary for log management
        """
        self.log_directory = Path(log_directory)
        self.config = config or self._get_default_config()
        
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration for log management."""
        return {
            'max_file_size_mb': 50,          # Max size before rotation
            'max_age_days': 30,              # Max age before deletion
            'max_files_per_log': 5,          # Max rotated files to keep
            'compress_rotated': True,         # Compress rotated logs
            'cleanup_interval_hours': 24,    # How often to run cleanup
            'log_patterns': [                # Log files to manage
                '*.log',
                'db_operations.log',
                'requests.log',
                'auth.log',
                'session_tracking.log',
                'errors.log',
                'resource_monitor.log'
            ]
        }
    
    def get_log_files(self) -> List[Path]:
        """Get all log files matching configured patterns."""
        log_files = []
        for pattern in self.config['log_patterns']:
            files = list(self.log_directory.glob(pattern))
            log_files.extend(files)
        
        # Remove duplicates and sort by modification time
        unique_files = list(set(log_files))
        unique_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        
        return unique_files
    
    def get_file_size_mb(self, file_path: Path) -> float:
        """Get file size in megabytes."""
        try:
            return file_path.stat().st_size / (1024 * 1024)
        except (OSError, FileNotFoundError):
            return 0.0
    
    def get_file_age_days(self, file_path: Path) -> int:
        """Get file age in days."""
        try:
            file_time = datetime.fromtimestamp(file_path.stat().st_mtime)
            age = datetime.now() - file_time
            return age.days
        except (OSError, FileNotFoundError):
            return 0
    
    def rotate_log(self, log_file: Path) -> bool:
        """
        Rotate a log file by moving it to a numbered backup.
        
        Args:
            log_file: Path to the log file to rotate
            
        Returns:
            bool: True if rotation was successful
        """
        try:
            # Find the next rotation number
            base_name = log_file.name
            rotation_num = 1
            
            while (log_file.parent / f"{base_name}.{rotation_num}").exists():
                rotation_num += 1
            
            # Move current log to rotated name
            rotated_path = log_file.parent / f"{base_name}.{rotation_num}"
            shutil.move(str(log_file), str(rotated_path))
            
            # Compress if configured
            if self.config['compress_rotated']:
                self.compress_file(rotated_path)
            
            # Create new empty log file
            log_file.touch()
            
            logger.info(f"Rotated log file: {log_file} -> {rotated_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to rotate log file {log_file}: {e}")
            return False
    
    def compress_file(self, file_path: Path) -> bool:
        """
        Compress a file using gzip.
        
        Args:
            file_path: Path to the file to compress
            
        Returns:
            bool: True if compression was successful
        """
        try:
            compressed_path = file_path.with_suffix(file_path.suffix + '.gz')
            
            with open(file_path, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # Remove original file
            file_path.unlink()
            
            logger.info(f"Compressed log file: {file_path} -> {compressed_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to compress file {file_path}: {e}")
            return False
    
    def cleanup_old_logs(self) -> Dict[str, int]:
        """
        Clean up old log files based on age and rotation limits.
        
        Returns:
            dict: Statistics about cleanup operation
        """
        stats = {
            'files_deleted': 0,
            'files_compressed': 0,
            'space_freed_mb': 0
        }
        
        try:
            log_files = self.get_log_files()
            
            # Group files by base name for rotation cleanup
            base_files = {}
            for log_file in log_files:
                # Extract base name (remove rotation numbers and .gz)
                base_name = log_file.name.split('.')[0] + '.log'
                if base_name not in base_files:
                    base_files[base_name] = []
                base_files[base_name].append(log_file)
            
            # Clean up each group
            for base_name, files in base_files.items():
                # Sort by modification time (newest first)
                files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                
                for i, log_file in enumerate(files):
                    file_age = self.get_file_age_days(log_file)
                    file_size = self.get_file_size_mb(log_file)
                    
                    should_delete = False
                    
                    # Delete if too old
                    if file_age > self.config['max_age_days']:
                        should_delete = True
                        logger.info(f"Deleting old log file: {log_file} (age: {file_age} days)")
                    
                    # Delete if too many rotations
                    elif i >= self.config['max_files_per_log']:
                        should_delete = True
                        logger.info(f"Deleting excess rotation: {log_file} (keeping {self.config['max_files_per_log']} files)")
                    
                    if should_delete:
                        try:
                            stats['space_freed_mb'] += file_size
                            log_file.unlink()
                            stats['files_deleted'] += 1
                        except Exception as e:
                            logger.error(f"Failed to delete {log_file}: {e}")
            
            logger.info(f"Log cleanup completed: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error during log cleanup: {e}")
            return stats
    
    def check_rotation_needed(self) -> List[Path]:
        """
        Check which log files need rotation based on size.
        
        Returns:
            list: List of files that need rotation
        """
        files_to_rotate = []
        
        try:
            log_files = self.get_log_files()
            
            for log_file in log_files:
                # Skip already rotated files (files with numbers)
                if '.' in log_file.stem and log_file.stem.split('.')[-1].isdigit():
                    continue
                
                file_size = self.get_file_size_mb(log_file)
                
                if file_size > self.config['max_file_size_mb']:
                    files_to_rotate.append(log_file)
                    logger.info(f"File needs rotation: {log_file} ({file_size:.1f} MB)")
        
        except Exception as e:
            logger.error(f"Error checking rotation needs: {e}")
        
        return files_to_rotate
    
    def run_maintenance(self) -> Dict[str, Any]:
        """
        Run complete log maintenance: rotation and cleanup.
        
        Returns:
            dict: Statistics about maintenance operation
        """
        logger.info("Starting log maintenance")
        
        stats = {
            'files_rotated': 0,
            'files_deleted': 0,
            'files_compressed': 0,
            'space_freed_mb': 0,
            'errors': []
        }
        
        try:
            # Step 1: Rotate large files
            files_to_rotate = self.check_rotation_needed()
            for log_file in files_to_rotate:
                if self.rotate_log(log_file):
                    stats['files_rotated'] += 1
                else:
                    stats['errors'].append(f"Failed to rotate {log_file}")
            
            # Step 2: Clean up old files
            cleanup_stats = self.cleanup_old_logs()
            stats['files_deleted'] = cleanup_stats['files_deleted']
            stats['files_compressed'] = cleanup_stats['files_compressed']
            stats['space_freed_mb'] = cleanup_stats['space_freed_mb']
            
            logger.info(f"Log maintenance completed: {stats}")
            
        except Exception as e:
            logger.error(f"Error during log maintenance: {e}")
            stats['errors'].append(str(e))
        
        return stats
    
    def get_log_summary(self) -> Dict[str, Any]:
        """
        Get summary information about all log files.
        
        Returns:
            dict: Summary of log files and their sizes
        """
        summary = {
            'total_files': 0,
            'total_size_mb': 0,
            'files': []
        }
        
        try:
            log_files = self.get_log_files()
            
            for log_file in log_files:
                file_size = self.get_file_size_mb(log_file)
                file_age = self.get_file_age_days(log_file)
                
                file_info = {
                    'name': log_file.name,
                    'size_mb': round(file_size, 2),
                    'age_days': file_age,
                    'needs_rotation': file_size > self.config['max_file_size_mb'],
                    'needs_cleanup': file_age > self.config['max_age_days']
                }
                
                summary['files'].append(file_info)
                summary['total_size_mb'] += file_size
            
            summary['total_files'] = len(log_files)
            summary['total_size_mb'] = round(summary['total_size_mb'], 2)
            
            # Sort by size (largest first)
            summary['files'].sort(key=lambda f: f['size_mb'], reverse=True)
            
        except Exception as e:
            logger.error(f"Error generating log summary: {e}")
        
        return summary


def setup_log_rotation():
    """Set up rotating file handlers to replace basic file handlers."""
    from logging.handlers import RotatingFileHandler
    import logging.config
    
    # Updated logging configuration with rotation
    ROTATING_LOGGING_CONFIG = {
        'version': 1,
        'disable_existing_loggers': False,
        
        'formatters': {
            'detailed': {
                'format': '%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s'
            },
            'simple': {
                'format': '%(asctime)s [%(levelname)s] %(message)s'
            },
            'focused': {
                'format': '%(asctime)s [%(levelname)s] %(name)s - %(message)s'
            }
        },
        
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'simple',
                'level': 'INFO',
            },
            'db_file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': 'db_operations.log',
                'formatter': 'detailed',
                'level': 'WARNING',  # Reduced from INFO to WARNING
                'maxBytes': 50 * 1024 * 1024,  # 50MB
                'backupCount': 3,
                'encoding': 'utf-8'
            },
            'requests_file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': 'requests.log',
                'formatter': 'detailed',
                'level': 'WARNING',  # Reduced from INFO to WARNING
                'maxBytes': 25 * 1024 * 1024,  # 25MB
                'backupCount': 2,
                'encoding': 'utf-8'
            },
            'auth_file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': 'auth.log',
                'formatter': 'detailed',
                'level': 'INFO',
                'maxBytes': 10 * 1024 * 1024,  # 10MB
                'backupCount': 3,
                'encoding': 'utf-8'
            },
            'session_tracking': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': 'session_tracking.log',
                'formatter': 'focused',
                'level': 'WARNING',  # Reduced from INFO to WARNING
                'maxBytes': 25 * 1024 * 1024,  # 25MB
                'backupCount': 2,
                'encoding': 'utf-8'
            },
            'errors_file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': 'errors.log',
                'formatter': 'detailed',
                'level': 'WARNING',
                'maxBytes': 25 * 1024 * 1024,  # 25MB
                'backupCount': 3,
                'encoding': 'utf-8'
            }
        },
        
        'loggers': {
            'sqlalchemy.engine': {
                'handlers': ['db_file'],
                'level': 'ERROR',  # Only log SQL errors, not queries or warnings
                'propagate': False
            },
            'app.db_management': {
                'handlers': ['db_file', 'errors_file'],
                'level': 'WARNING',
                'propagate': False
            },
            'app.database.pool': {
                'handlers': ['db_file', 'errors_file'],
                'level': 'ERROR',  # Only log serious connection errors
                'propagate': False
            },
            'app.utils.task_monitor': {
                'handlers': ['console'],
                'level': 'ERROR',  # Reduced significantly
                'propagate': False
            },
            'app.request': {
                'handlers': ['requests_file'],
                'level': 'ERROR',  # Only log request errors
                'propagate': False
            },
            'app.main': {
                'handlers': ['console'],
                'level': 'ERROR',  # Minimal logging
                'propagate': False
            },
            'app.match_pages': {
                'handlers': ['requests_file'],
                'level': 'ERROR',
                'propagate': False
            },
            'app.availability_api_helpers': {
                'handlers': ['requests_file'],
                'level': 'ERROR',
                'propagate': False
            },
            'app.sms_helpers': {
                'handlers': ['console', 'requests_file'],
                'level': 'INFO',  # Keep SMS at INFO for debugging
                'propagate': False
            },
            'app.auth': {
                'handlers': ['console', 'auth_file'],
                'level': 'INFO',  # Keep auth at INFO for security
                'propagate': False
            },
            'app.core': {
                'handlers': ['console'],
                'level': 'ERROR',
                'propagate': False
            },
            'app.core.session_manager': {
                'handlers': ['session_tracking', 'errors_file'],
                'level': 'ERROR',  # Only log serious session errors
                'propagate': False
            },
            'flask_login': {
                'handlers': ['auth_file'],
                'level': 'WARNING',
                'propagate': False
            },
            'werkzeug': {
                'handlers': ['requests_file'],
                'level': 'ERROR',
                'propagate': False
            },
            'app.tasks': {
                'handlers': ['console'],
                'level': 'ERROR',
                'propagate': False
            },
            'app.lifecycle': {
                'handlers': ['console'],
                'level': 'ERROR',
                'propagate': False
            },
            'app.redis_manager': {
                'handlers': ['console'],
                'level': 'ERROR',
                'propagate': False
            }
        },
        
        'root': {
            'handlers': ['console', 'errors_file'],
            'level': 'WARNING',
        }
    }
    
    # Apply the new configuration
    logging.config.dictConfig(ROTATING_LOGGING_CONFIG)
    logger.info("Log rotation configuration applied")


# Initialize global log manager
log_manager = LogManager()


def run_log_maintenance():
    """Convenience function to run log maintenance."""
    return log_manager.run_maintenance()


def get_log_summary():
    """Convenience function to get log summary."""
    return log_manager.get_log_summary()


if __name__ == "__main__":
    # CLI usage for manual log maintenance
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "maintenance":
            print("Running log maintenance...")
            stats = run_log_maintenance()
            print(f"Maintenance completed: {stats}")
            
        elif command == "summary":
            print("Log file summary:")
            summary = get_log_summary()
            print(f"Total files: {summary['total_files']}")
            print(f"Total size: {summary['total_size_mb']} MB")
            for file_info in summary['files']:
                print(f"  {file_info['name']}: {file_info['size_mb']} MB ({file_info['age_days']} days old)")
                
        elif command == "setup":
            print("Setting up log rotation...")
            setup_log_rotation()
            print("Log rotation setup completed")
            
        else:
            print("Usage: python log_management.py [maintenance|summary|setup]")
    else:
        print("Usage: python log_management.py [maintenance|summary|setup]")