# api/routes/websocket_routes.py

"""
WebSocket API Routes

Provides endpoints for monitoring and managing the Discord bot's WebSocket
connection to the Flask app for real-time RSVP synchronization.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/websocket", tags=["websocket"])


@router.get("/stats")
async def get_websocket_stats():
    """
    Get WebSocket connection statistics and status.
    
    Returns information about:
    - Connection status
    - Events received/processed
    - Active match rooms
    - Recent activity
    """
    try:
        from websocket_rsvp_manager import get_websocket_manager
        
        manager = get_websocket_manager()
        if not manager:
            return JSONResponse({
                "status": "not_initialized",
                "message": "WebSocket manager not initialized",
                "stats": {}
            })
        
        stats = manager.get_stats()
        stats["status"] = "initialized"
        
        return JSONResponse({
            "status": "success",
            "message": "WebSocket statistics retrieved",
            "stats": stats
        })
        
    except Exception as e:
        logger.error(f"Error getting WebSocket stats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting WebSocket stats: {str(e)}")


@router.get("/events/recent")
async def get_recent_websocket_events(limit: int = 50):
    """
    Get recent WebSocket RSVP events for debugging and validation.
    
    Parameters:
    - limit: Maximum number of events to return (default: 50, max: 500)
    """
    try:
        from websocket_rsvp_manager import get_websocket_manager
        
        # Validate limit
        if limit > 500:
            limit = 500
        elif limit < 1:
            limit = 1
        
        manager = get_websocket_manager()
        if not manager:
            return JSONResponse({
                "status": "not_initialized",
                "message": "WebSocket manager not initialized",
                "events": []
            })
        
        events = manager.get_recent_events(limit)
        
        return JSONResponse({
            "status": "success",
            "message": f"Retrieved {len(events)} recent WebSocket events",
            "events": events,
            "total_events": len(events)
        })
        
    except Exception as e:
        logger.error(f"Error getting recent WebSocket events: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting recent events: {str(e)}")


@router.post("/connection/reconnect")
async def force_websocket_reconnect():
    """
    Force a WebSocket reconnection.
    
    Useful for debugging or if the connection gets stuck.
    """
    try:
        from websocket_rsvp_manager import get_websocket_manager
        
        manager = get_websocket_manager()
        if not manager:
            return JSONResponse({
                "status": "not_initialized",
                "message": "WebSocket manager not initialized"
            })
        
        # Disconnect and reconnect
        await manager.disconnect()
        success = await manager.connect()
        
        if success:
            return JSONResponse({
                "status": "success",
                "message": "WebSocket reconnection successful"
            })
        else:
            return JSONResponse({
                "status": "failed",
                "message": "WebSocket reconnection failed"
            })
        
    except Exception as e:
        logger.error(f"Error forcing WebSocket reconnection: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error reconnecting: {str(e)}")


@router.post("/matches/{match_id}/join")
async def join_match_websocket_room(match_id: int):
    """
    Manually join a specific match's WebSocket room.
    
    Useful for testing or if the bot missed joining a room.
    
    Parameters:
    - match_id: ID of the match to join
    """
    try:
        from websocket_rsvp_manager import get_websocket_manager
        
        manager = get_websocket_manager()
        if not manager:
            raise HTTPException(status_code=503, detail="WebSocket manager not initialized")
        
        if not manager.connected:
            raise HTTPException(status_code=503, detail="WebSocket not connected")
        
        success = await manager.join_match(match_id)
        
        if success:
            return JSONResponse({
                "status": "success",
                "message": f"Successfully joined WebSocket room for match {match_id}",
                "match_id": match_id
            })
        else:
            return JSONResponse({
                "status": "failed",
                "message": f"Failed to join WebSocket room for match {match_id}",
                "match_id": match_id
            })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error joining match WebSocket room: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error joining match room: {str(e)}")


@router.get("/validation/compare/{match_id}")
async def compare_websocket_vs_rest_data(match_id: int):
    """
    Compare WebSocket RSVP data with REST API data for validation.
    
    This helps ensure both systems are in sync and can identify discrepancies.
    
    Parameters:
    - match_id: ID of the match to compare
    """
    try:
        from websocket_rsvp_manager import get_websocket_manager
        import aiohttp
        import os
        
        manager = get_websocket_manager()
        if not manager:
            raise HTTPException(status_code=503, detail="WebSocket manager not initialized")
        
        # Get recent WebSocket events for this match
        recent_events = manager.get_recent_events(100)
        match_events = [e for e in recent_events if e.get('match_id') == match_id]
        
        # Get REST API data for comparison
        webui_url = os.getenv('WEBUI_API_URL', 'http://webui:5000')
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{webui_url}/api/get_match_rsvps/{match_id}") as response:
                    if response.status == 200:
                        rest_data = await response.json()
                    else:
                        rest_data = {"error": f"HTTP {response.status}"}
        except Exception as e:
            rest_data = {"error": f"Connection failed: {str(e)}"}
        
        return JSONResponse({
            "status": "success",
            "match_id": match_id,
            "websocket_events": match_events,
            "websocket_event_count": len(match_events),
            "rest_api_data": rest_data,
            "comparison": {
                "websocket_has_events": len(match_events) > 0,
                "rest_api_accessible": "error" not in rest_data,
                "last_websocket_event": match_events[-1] if match_events else None
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error comparing WebSocket vs REST data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error comparing data: {str(e)}")


@router.get("/health")
async def websocket_health_check():
    """
    Health check specifically for WebSocket functionality.
    
    Returns detailed health information about the WebSocket connection.
    """
    try:
        from websocket_rsvp_manager import get_websocket_manager
        
        manager = get_websocket_manager()
        
        if not manager:
            return JSONResponse({
                "status": "unhealthy",
                "message": "WebSocket manager not initialized",
                "details": {
                    "initialized": False,
                    "connected": False,
                    "active_matches": 0
                }
            })
        
        stats = manager.get_stats()
        is_healthy = stats.get('connected', False)
        
        return JSONResponse({
            "status": "healthy" if is_healthy else "unhealthy",
            "message": "WebSocket connection active" if is_healthy else "WebSocket connection inactive",
            "details": {
                "initialized": True,
                "connected": stats.get('connected', False),
                "active_matches": stats.get('active_matches', 0),
                "events_received": stats.get('events_received', 0),
                "events_processed": stats.get('events_processed', 0),
                "last_event_time": stats.get('last_event_time')
            }
        })
        
    except Exception as e:
        logger.error(f"Error in WebSocket health check: {str(e)}")
        return JSONResponse({
            "status": "error",
            "message": f"Health check failed: {str(e)}",
            "details": {
                "initialized": False,
                "connected": False,
                "error": str(e)
            }
        })