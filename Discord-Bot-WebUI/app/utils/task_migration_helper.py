"""
Task Migration Helper

Utility to identify and validate async Celery tasks that need migration
to the new two-phase pattern.
"""

import ast
import os
import logging
from typing import List, Dict, Any
import inspect

logger = logging.getLogger(__name__)


class TaskMigrationAnalyzer:
    """Analyzes Celery tasks to identify migration candidates."""
    
    def __init__(self, task_dir: str = "app/tasks"):
        self.task_dir = task_dir
        self.legacy_async_tasks = []
        self.migrated_tasks = []
        self.problematic_patterns = []
    
    def analyze_all_tasks(self) -> Dict[str, List[str]]:
        """
        Analyze all task files and categorize them.
        
        Returns:
            Dictionary with categorized task information
        """
        for filename in os.listdir(self.task_dir):
            if filename.endswith('.py') and not filename.startswith('__'):
                filepath = os.path.join(self.task_dir, filename)
                self._analyze_file(filepath)
        
        return {
            'legacy_async_tasks': self.legacy_async_tasks,
            'migrated_tasks': self.migrated_tasks,
            'problematic_patterns': self.problematic_patterns
        }
    
    def _analyze_file(self, filepath: str):
        """Analyze a single Python file for task patterns."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    self._analyze_function(node, filepath)
                    
        except Exception as e:
            logger.error(f"Error analyzing {filepath}: {e}")
    
    def _analyze_function(self, node: ast.FunctionDef, filepath: str):
        """Analyze a function to determine if it's a Celery task."""
        # Check if function has @celery_task decorator
        has_celery_decorator = any(
            (isinstance(d, ast.Name) and d.id == 'celery_task') or
            (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == 'celery_task')
            for d in node.decorator_list
        )
        
        if not has_celery_decorator:
            return
        
        func_name = node.name
        is_async = isinstance(node, ast.AsyncFunctionDef) or (
            hasattr(node, 'type') and node.type == 'async'
        )
        
        # Check if function is async
        if hasattr(node, 'type_comment') and 'async' in str(node.type_comment):
            is_async = True
        
        # Look for async patterns in the function body
        has_aiohttp = self._has_pattern_in_body(node, ['aiohttp', 'ClientSession'])
        has_asyncio_sleep = self._has_pattern_in_body(node, ['asyncio.sleep', 'await asyncio.sleep'])
        has_async_to_sync = self._has_pattern_in_body(node, ['async_to_sync'])
        has_session_param = any(arg.arg == 'session' for arg in node.args.args)
        
        # Check if task is migrated (has _extract_data attribute)
        task_info = {
            'name': func_name,
            'file': filepath,
            'is_async': is_async,
            'has_session': has_session_param,
            'has_aiohttp': has_aiohttp,
            'has_asyncio_sleep': has_asyncio_sleep,
            'has_async_to_sync': has_async_to_sync
        }
        
        # Determine category
        if is_async and has_session_param and (has_aiohttp or has_asyncio_sleep or has_async_to_sync):
            # Check if migrated by looking for _extract_data assignment
            if self._has_extract_data_assignment(filepath, func_name):
                self.migrated_tasks.append(task_info)
            else:
                self.legacy_async_tasks.append(task_info)
                
        elif has_session_param and (has_aiohttp or has_asyncio_sleep):
            self.problematic_patterns.append(task_info)
    
    def _has_pattern_in_body(self, node: ast.FunctionDef, patterns: List[str]) -> bool:
        """Check if function body contains any of the given patterns."""
        body_str = ast.dump(node)
        return any(pattern in body_str for pattern in patterns)
    
    def _has_extract_data_assignment(self, filepath: str, func_name: str) -> bool:
        """Check if file contains _extract_data assignment for the function."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            extract_pattern = f"{func_name}._extract_data"
            return extract_pattern in content
            
        except Exception:
            return False
    
    def generate_migration_report(self) -> str:
        """Generate a human-readable migration report."""
        analysis = self.analyze_all_tasks()
        
        report = []
        report.append("# Async Celery Task Migration Report\n")
        
        report.append(f"## Summary")
        report.append(f"- Legacy async tasks: {len(analysis['legacy_async_tasks'])}")
        report.append(f"- Migrated tasks: {len(analysis['migrated_tasks'])}")
        report.append(f"- Problematic patterns: {len(analysis['problematic_patterns'])}\n")
        
        if analysis['legacy_async_tasks']:
            report.append("## ⚠️ Legacy Async Tasks (Need Migration)")
            for task in analysis['legacy_async_tasks']:
                report.append(f"- **{task['name']}** in `{task['file']}`")
                details = []
                if task['has_aiohttp']:
                    details.append("uses aiohttp")
                if task['has_asyncio_sleep']:
                    details.append("uses asyncio.sleep")
                if task['has_async_to_sync']:
                    details.append("uses async_to_sync")
                if details:
                    report.append(f"  - {', '.join(details)}")
            report.append("")
        
        if analysis['migrated_tasks']:
            report.append("## ✅ Migrated Tasks")
            for task in analysis['migrated_tasks']:
                report.append(f"- **{task['name']}** in `{task['file']}`")
            report.append("")
        
        if analysis['problematic_patterns']:
            report.append("## 🔍 Potentially Problematic Patterns")
            for task in analysis['problematic_patterns']:
                report.append(f"- **{task['name']}** in `{task['file']}`")
            report.append("")
        
        return "\n".join(report)


def validate_migrated_task(task_func) -> Dict[str, Any]:
    """
    Validate that a task has been properly migrated.
    
    Args:
        task_func: The Celery task function to validate
        
    Returns:
        Validation result with success status and details
    """
    result = {
        'success': True,
        'issues': [],
        'task_name': getattr(task_func, '__name__', 'unknown')
    }
    
    # Check required attributes
    if not hasattr(task_func, '_extract_data'):
        result['issues'].append("Missing _extract_data function")
        result['success'] = False
    
    if not hasattr(task_func, '_execute_async'):
        result['issues'].append("Missing _execute_async function")
        result['success'] = False
    
    # Check if function is async
    if not inspect.iscoroutinefunction(task_func):
        result['issues'].append("Task function should be async")
        result['success'] = False
    
    # Check if extract_data is callable
    if hasattr(task_func, '_extract_data') and not callable(task_func._extract_data):
        result['issues'].append("_extract_data is not callable")
        result['success'] = False
    
    # Check if execute_async is async callable
    if hasattr(task_func, '_execute_async'):
        if not callable(task_func._execute_async):
            result['issues'].append("_execute_async is not callable")
            result['success'] = False
        elif not inspect.iscoroutinefunction(task_func._execute_async):
            result['issues'].append("_execute_async should be async")
            result['success'] = False
    
    # Check final update consistency
    has_final_update_flag = hasattr(task_func, '_requires_final_db_update')
    has_final_update_func = hasattr(task_func, '_final_db_update')
    
    if has_final_update_flag and not has_final_update_func:
        result['issues'].append("Has _requires_final_db_update but missing _final_db_update")
        result['success'] = False
    
    if has_final_update_func and not has_final_update_flag:
        result['issues'].append("Has _final_db_update but missing _requires_final_db_update flag")
        result['success'] = False
    
    return result


def create_migration_template(task_name: str, has_final_update: bool = False) -> str:
    """
    Create a template for migrating a task.
    
    Args:
        task_name: Name of the task to migrate
        has_final_update: Whether task needs final database update
        
    Returns:
        Template code for the migrated task
    """
    template = f'''def _extract_{task_name}_data(session, *args, **kwargs):
    """Extract data from database for {task_name}."""
    # TODO: Add database queries here
    # Example:
    # entity = session.query(SomeModel).get(entity_id)
    # if not entity:
    #     raise ValueError(f"Entity not found")
    
    return {{
        # TODO: Add extracted data
        # 'entity_id': entity.id,
        # 'discord_id': entity.discord_id,
    }}


async def _execute_{task_name}_async(data):
    """Execute async operations for {task_name}."""
    # TODO: Add async operations here (HTTP requests, etc.)
    # Example:
    # async with aiohttp.ClientSession() as session:
    #     result = await make_api_call(session, data['discord_id'])
    
    return {{
        'success': True,
        # TODO: Add result data
    }}

'''
    
    if has_final_update:
        template += f'''
def _update_{task_name}_final(session, result):
    """Final database update for {task_name}."""
    # TODO: Update database with async operation results
    # Example:
    # entity = session.query(SomeModel).get(result['entity_id'])
    # if entity:
    #     entity.some_field = result['some_value']
    #     entity.last_updated = datetime.utcnow()
    
    return result

'''
    
    template += f'''
@celery_task(name='{task_name}')
async def {task_name}(self, session, *args, **kwargs):
    """Migrated {task_name} using two-phase pattern."""
    pass


# Attach phase functions
{task_name}._extract_data = _extract_{task_name}_data
{task_name}._execute_async = _execute_{task_name}_async'''
    
    if has_final_update:
        template += f'''
{task_name}._requires_final_db_update = True
{task_name}._final_db_update = _update_{task_name}_final'''
    
    return template


if __name__ == "__main__":
    # Generate migration report
    analyzer = TaskMigrationAnalyzer()
    report = analyzer.generate_migration_report()
    print(report)