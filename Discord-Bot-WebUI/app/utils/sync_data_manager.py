# app/utils/sync_data_manager.py

import json
from app.utils.redis_manager import RedisManager

def save_sync_data(task_id, data):
    """
    Save sync data (as JSON) in Redis under a key derived from the task_id.
    Expires after 1 hour.
    """
    redis_manager = RedisManager()
    key = f"player_sync_data:{task_id}"
    redis_manager.client.set(key, json.dumps(data), ex=3600)

def get_sync_data(task_id):
    """
    Retrieve sync data from Redis by task_id.
    """
    redis_manager = RedisManager()
    key = f"player_sync_data:{task_id}"
    data = redis_manager.client.get(key)
    if data:
        return json.loads(data)
    return None

def delete_sync_data(task_id):
    """
    Delete the sync data from Redis.
    """
    redis_manager = RedisManager()
    key = f"player_sync_data:{task_id}"
    redis_manager.client.delete(key)