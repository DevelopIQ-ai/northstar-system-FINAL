"""
FastAPI application for Bid Reminder Agent
Single endpoint to run bid reminder workflow
"""

import os
import signal
import asyncio
import logging
from typing import Optional
from datetime import datetime
from contextlib import asynccontextmanager

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from fastapi import FastAPI, HTTPException, status, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from bid_reminder_agent import run_bid_reminder, send_health_error_notification

# Load environment variables
load_dotenv()

# Initialize Sentry with comprehensive logging
sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[
            FastApiIntegration(
                failed_request_status_codes=[400, range(500, 600)]
            ),
            StarletteIntegration(
                failed_request_status_codes=[400, range(500, 600)]
            ),
            LoggingIntegration(
                level=logging.INFO,        # Capture info and above as breadcrumbs
                event_level=logging.WARNING  # Send warnings and above as events
            ),
        ],
        traces_sample_rate=0.1,
        environment=os.getenv("ENVIRONMENT", "production"),
        release=os.getenv("RELEASE_VERSION", "1.0.0"),
        send_default_pii=False,
        # Enhanced configuration for better logging
        debug=os.getenv("SENTRY_DEBUG", "false").lower() == "true",
        attach_stacktrace=True,
        max_breadcrumbs=50,
        before_send=lambda event, hint: event if event.get('level') != 'debug' else None,
    )

# Configure logging - optimized for Railway + Sentry
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Railway captures stdout/stderr
    ]
)

# Configure Sentry logging if available
if sentry_dsn:
    # Add custom Sentry handler for explicit log forwarding
    sentry_handler = sentry_sdk.integrations.logging.SentryHandler()
    sentry_handler.setLevel(logging.WARNING)  # Only send warnings and above
    
    # Get root logger and add Sentry handler
    root_logger = logging.getLogger()
    root_logger.addHandler(sentry_handler)

logger = logging.getLogger(__name__)

# Global state for graceful shutdown
shutdown_event = asyncio.Event()
active_connections = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    logger.info("🚀 Starting Bid Reminder Agent API...")
    
    # Check environment configuration (only client credentials)
    outlook_vars = ['MS_CLIENT_ID', 'MS_CLIENT_SECRET', 'ENCRYPTION_KEY']
    building_vars = ['AUTODESK_CLIENT_ID', 'AUTODESK_CLIENT_SECRET', 'AUTODESK_ENCRYPTION_KEY']
    
    missing_outlook = [var for var in outlook_vars if not os.getenv(var)]
    missing_building = [var for var in building_vars if not os.getenv(var)]
    
    if missing_outlook or missing_building:
        logger.warning("⚠️  Missing environment variables:")
        if missing_outlook:
            logger.warning(f"  Outlook: {', '.join(missing_outlook)}")
        if missing_building:
            logger.warning(f"  BuildingConnected: {', '.join(missing_building)}")
        logger.warning("Please run 'python setup_bid_reminder.py' to configure authentication")
        logger.warning("API will start but bid reminder may fail until configured")
    else:
        logger.info("✅ Environment properly configured")
    
    logger.info("📖 API Documentation: http://localhost:8000/docs")
    
    yield
    
    # Shutdown
    logger.info("🔄 Initiating graceful shutdown...")
    shutdown_event.set()
    
    # Wait for active connections to finish (with timeout)
    timeout = 30  # seconds
    start_time = asyncio.get_event_loop().time()
    
    while active_connections > 0:
        if asyncio.get_event_loop().time() - start_time > timeout:
            logger.warning(f"⚠️  Shutdown timeout reached. {active_connections} connections still active.")
            break
        
        logger.info(f"⏳ Waiting for {active_connections} active connections to finish...")
        await asyncio.sleep(1)
    
    logger.info("✅ Graceful shutdown completed")


class ConnectionTrackingMiddleware(BaseHTTPMiddleware):
    """Middleware to track active connections for graceful shutdown"""
    
    async def dispatch(self, request: Request, call_next):
        global active_connections
        
        # Check if shutdown has been initiated
        if shutdown_event.is_set():
            return Response(
                content="Server is shutting down",
                status_code=503,
                headers={"Retry-After": "30"}
            )
        
        # Increment active connections
        active_connections += 1
        
        try:
            response = await call_next(request)
            return response
        finally:
            # Decrement active connections
            active_connections -= 1


# Initialize FastAPI app with lifespan
app = FastAPI(
    title="Bid Reminder Agent API",
    description="REST API for running BuildingConnected bid reminder workflow",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Add middleware
app.add_middleware(ConnectionTrackingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# API Models
class BidReminderResponse(BaseModel):
    """Bid reminder response model"""
    workflow_successful: bool = Field(..., description="Whether the workflow completed successfully")
    result_message: Optional[str] = Field(None, description="Result message")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    projects_found: int = Field(0, description="Number of projects due in 5-10 days")
    email_sent: bool = Field(False, description="Whether reminder email was sent")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")


class HealthResponse(BaseModel):
    """Health check response model"""
    status: str = Field(..., description="Service status")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Health check timestamp")
    outlook_configured: bool = Field(..., description="Whether Outlook is configured")
    building_configured: bool = Field(..., description="Whether BuildingConnected is configured")


# API Endpoints
@app.get("/", summary="Root endpoint")
async def root():
    """Root endpoint with basic information"""
    return {
        "message": "Bid Reminder Agent API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "workflow": "/run-bid-reminder"
    }


@app.get("/health", response_model=HealthResponse, summary="Health check")
async def health_check():
    """
    Health check endpoint that runs the full bid reminder workflow
    
    This endpoint:
    1. Runs the complete bid reminder workflow 
    2. Checks BuildingConnected for projects due in 5-10 days
    3. Logs bidding invitations that would be sent (but doesn't send them)
    4. Sends a health success email to kush@developiq.ai and evan@developiq.ai
    5. Returns configuration status
    """
    outlook_vars = ['MS_CLIENT_ID', 'MS_CLIENT_SECRET', 'ENCRYPTION_KEY']
    building_vars = ['AUTODESK_CLIENT_ID', 'AUTODESK_CLIENT_SECRET', 'AUTODESK_ENCRYPTION_KEY']
    
    outlook_configured = all(os.getenv(var) for var in outlook_vars)
    building_configured = all(os.getenv(var) for var in building_vars)
    
    both_configured = outlook_configured and building_configured
    
    # Run the bid reminder workflow in health check mode if both systems are configured
    if both_configured:
        try:
            logger.info("🏥 Running health check workflow")
            result = await run_bid_reminder(is_health=True)
            
            if result.get('workflow_successful', False):
                logger.info("✅ Health check workflow completed successfully")
                status = "healthy"
            else:
                error_msg = result.get('error_message', 'Unknown error')
                logger.warning(f"⚠️ Health check workflow failed: {error_msg}")
                status = "degraded"
                
                # Send error notification email
                try:
                    logger.info("📧 Sending health error notification")
                    error_sent = await send_health_error_notification(
                        error_message=error_msg,
                        error_stage="Workflow Execution"
                    )
                    if error_sent:
                        logger.info("✅ Health error notification sent successfully")
                    else:
                        logger.warning("⚠️ Failed to send health error notification")
                except Exception as email_error:
                    logger.error(f"❌ Error sending health error notification: {str(email_error)}")
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Health check workflow error: {error_msg}")
            status = "degraded"
            
            # Send error notification email for unexpected exceptions
            try:
                logger.info("📧 Sending health error notification for exception")
                error_sent = await send_health_error_notification(
                    error_message=f"Health check threw an exception: {error_msg}",
                    error_stage="Workflow Exception"
                )
                if error_sent:
                    logger.info("✅ Health exception notification sent successfully")
                else:
                    logger.warning("⚠️ Failed to send health exception notification")
            except Exception as email_error:
                logger.error(f"❌ Error sending health exception notification: {str(email_error)}")
                
    else:
        status = "degraded"
        error_msg = f"Health check skipped - missing configuration. Outlook: {outlook_configured}, BuildingConnected: {building_configured}"
        logger.warning(f"⚠️ {error_msg}")
        
        # Send error notification for configuration issues
        try:
            logger.info("📧 Sending health error notification for configuration")
            error_sent = await send_health_error_notification(
                error_message=error_msg,
                error_stage="Configuration Check"
            )
            if error_sent:
                logger.info("✅ Health configuration error notification sent successfully")
            else:
                logger.warning("⚠️ Failed to send health configuration error notification")
        except Exception as email_error:
            logger.error(f"❌ Error sending health configuration error notification: {str(email_error)}")
    
    return HealthResponse(
        status=status,
        outlook_configured=outlook_configured,
        building_configured=building_configured
    )


@app.post("/run-bid-reminder", response_model=BidReminderResponse, summary="Run bid reminder workflow")
async def run_bid_reminder_workflow():
    """
    Run the bid reminder workflow
    
    This endpoint:
    1. Checks BuildingConnected for projects due in 5-10 days
    2. Sends reminder email about those projects
    3. Returns the results
    """
    try:
        # Run the bid reminder workflow
        result = await run_bid_reminder(is_health=False)
        
        # Extract project count
        upcoming_projects = result.get("upcoming_projects", [])
        projects_found = len(upcoming_projects) if upcoming_projects else 0
        
        return BidReminderResponse(
            workflow_successful=result.get('workflow_successful', False),
            result_message=result.get('result_message'),
            error_message=result.get('error_message'),
            projects_found=projects_found,
            email_sent=result.get('reminder_email_sent', False)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to run bid reminder workflow: {str(e)}"
        )



def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    def signal_handler(signum, frame):
        logger.info(f"🛑 Received signal {signum}. Initiating graceful shutdown...")
        raise KeyboardInterrupt()
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination signal
    
    # On Unix systems, also handle SIGHUP
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, signal_handler)


if __name__ == "__main__":
    import uvicorn
    
    # Setup signal handlers
    setup_signal_handlers()
    
    try:
        uvicorn.run(
            "app:app",
            host="0.0.0.0",
            port=8000,
            reload=False,  # Disable reload for proper signal handling
            log_level="info",
            access_log=True
        )
    except KeyboardInterrupt:
        logger.info("🛑 Shutdown signal received")
    except Exception as e:
        logger.error(f"❌ Server error: {e}")
    finally:
        logger.info("🔚 Server stopped")