# app/utils/sync_data_manager.py

"""
Sync Data Manager Module

This module provides helper functions for saving, retrieving, and deleting synchronization
data in Redis. The data is stored in JSON format under keys derived from a given task ID.
Each saved entry expires after one hour.
"""

import json
from app.utils.safe_redis import get_safe_redis


def save_sync_data(task_id, data):
    """
    Save synchronization data in Redis.

    The data is serialized as JSON and stored under a key based on the task_id.
    The key expires after 3600 seconds (1 hour).

    Args:
        task_id: A unique identifier for the task.
        data: The data to be saved (must be JSON serializable).
    """
    redis_client = get_safe_redis()
    key = f"player_sync_data:{task_id}"
    # Serialize the data to JSON and set an expiration of 1 hour.
    redis_client.set(key, json.dumps(data), ex=3600)


def get_sync_data(task_id):
    """
    Retrieve synchronization data from Redis.

    The data is retrieved using a key derived from the task_id and then deserialized from JSON.

    Args:
        task_id: The unique identifier for the task.

    Returns:
        The deserialized data if found, otherwise None.
    """
    redis_client = get_safe_redis()
    key = f"player_sync_data:{task_id}"
    data = redis_client.get(key)
    if data:
        return json.loads(data)
    return None


def delete_sync_data(task_id):
    """
    Delete synchronization data from Redis.

    The data is deleted using a key derived from the task_id.

    Args:
        task_id: The unique identifier for the task.
    """
    redis_client = get_safe_redis()
    key = f"player_sync_data:{task_id}"
    redis_client.delete(key)