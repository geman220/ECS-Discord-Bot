# discord bot_rest_api.py - Refactored main application file

from fastapi import FastAPI
from shared_states import get_bot_instance, set_bot_instance, bot_ready, bot_state
import logging

# Import API utilities
from api.utils.api_client import startup_event, shutdown_event

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# FIX THIS AFTER TESTING
TEAM_ID = '9726'

# Initialize FastAPI app
app = FastAPI()

# Include existing routers
from ecs_fc_bot_api import router as ecs_fc_router
app.include_router(ecs_fc_router)

# Include new modular routers
from api.routes.server_routes import router as server_router
from api.routes.match_routes import router as match_router
from api.routes.league_routes import router as league_router
from api.routes.communication_routes import router as communication_router
from api.routes.ecs_fc_sub_routes import router as ecs_fc_sub_router
from api.routes.onboarding_routes import router as onboarding_router

app.include_router(server_router)
app.include_router(match_router, prefix="/api/server")
app.include_router(league_router)
app.include_router(communication_router)
app.include_router(ecs_fc_sub_router)
app.include_router(onboarding_router)

# Startup and shutdown events
app.add_event_handler("startup", startup_event)
app.add_event_handler("shutdown", shutdown_event)

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "message": "Bot REST API is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5001)