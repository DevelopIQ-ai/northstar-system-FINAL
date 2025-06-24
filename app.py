"""
FastAPI application for Bid Reminder Agent
Single endpoint to run bid reminder workflow
"""

import os
import signal
import asyncio
import logging
import sys
import subprocess
import json
from typing import Optional, Dict, Any, List
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

from bid_reminder_agent import run_bid_reminder

# Import test suite components
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from clients.graph_api_client import MSGraphClient
from auth.auth_helpers import create_token_manager_from_env

# Test suite imports (conditional imports to handle missing files gracefully)
try:
    sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test-suite'))
    from test_auth_health import run_auth_health_check
    from test_auth_gaps import run_auth_gaps_check
    from test_msgraph import run_msgraph_tests
    from test_buildingconnected import run_buildingconnected_tests
    from test_auth_8am_preflight import PreFlightChecker
    TEST_SUITES_AVAILABLE = True
except ImportError as e:
    logger.warning(f"⚠️  Test suite imports failed: {e}")
    TEST_SUITES_AVAILABLE = False

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
    
    # Check environment configuration
    outlook_vars = ['MS_CLIENT_ID', 'MS_CLIENT_SECRET', 'ENCRYPTED_REFRESH_TOKEN', 'ENCRYPTION_KEY']
    building_vars = ['AUTODESK_CLIENT_ID', 'AUTODESK_CLIENT_SECRET', 'AUTODESK_ENCRYPTED_REFRESH_TOKEN', 'AUTODESK_ENCRYPTION_KEY']
    
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
    test_suite_executed: bool = Field(False, description="Whether test suite was executed")
    test_results_summary: Optional[Dict[str, Any]] = Field(None, description="Summary of test results")
    email_report_sent: bool = Field(False, description="Whether email report was sent successfully")


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


async def run_comprehensive_test_suite():
    """Run all test suites and return aggregated results"""
    logger.info("🧪 Starting comprehensive test suite execution")
    
    if not TEST_SUITES_AVAILABLE:
        return {
            "execution_timestamp": datetime.utcnow().isoformat(),
            "test_suites": {},
            "overall_summary": {
                "overall_status": "ERROR",
                "total_tests": 0,
                "total_passed": 0,
                "total_failed": 0,
                "critical_failures": 0,
                "pass_rate": 0,
                "error": "Test suites not available - import failed"
            }
        }
    
    test_results = {
        "execution_timestamp": datetime.utcnow().isoformat(),
        "test_suites": {},
        "overall_summary": {}
    }
    
    total_tests = 0
    total_passed = 0
    total_failed = 0
    critical_failures = 0
    all_passed = True
    
    # Test Suite 1: Authentication Health Check
    try:
        logger.info("📋 Running Authentication Health Check...")
        auth_health_report = await run_auth_health_check()
        test_results["test_suites"]["auth_health"] = {
            "status": auth_health_report.overall_status,
            "total_tests": auth_health_report.total_tests,
            "passed_tests": auth_health_report.passed_tests,
            "failed_tests": auth_health_report.failed_tests,
            "execution_time_ms": auth_health_report.execution_time_ms,
            "critical_failures": auth_health_report.critical_failures,
            "warnings": auth_health_report.warnings
        }
        total_tests += auth_health_report.total_tests
        total_passed += auth_health_report.passed_tests
        total_failed += auth_health_report.failed_tests
        if auth_health_report.overall_status != "PASS":
            all_passed = False
    except Exception as e:
        logger.error(f"❌ Authentication Health Check failed: {str(e)}")
        test_results["test_suites"]["auth_health"] = {
            "status": "ERROR",
            "error": str(e)
        }
        all_passed = False

    # Test Suite 2: Authentication Gaps Check
    try:
        logger.info("🔍 Running Authentication Gaps Check...")
        auth_gaps_report = await run_auth_gaps_check()
        test_results["test_suites"]["auth_gaps"] = {
            "status": auth_gaps_report.overall_status,
            "total_tests": auth_gaps_report.total_tests,
            "passed_tests": auth_gaps_report.passed_tests,
            "failed_tests": auth_gaps_report.failed_tests,
            "execution_time_ms": auth_gaps_report.execution_time_ms,
            "critical_issues": len(auth_gaps_report.critical_issues),
            "warnings": len(auth_gaps_report.warnings)
        }
        total_tests += auth_gaps_report.total_tests
        total_passed += auth_gaps_report.passed_tests
        total_failed += auth_gaps_report.failed_tests
        if auth_gaps_report.overall_status != "PASS":
            all_passed = False
    except Exception as e:
        logger.error(f"❌ Authentication Gaps Check failed: {str(e)}")
        test_results["test_suites"]["auth_gaps"] = {
            "status": "ERROR",
            "error": str(e)
        }
        all_passed = False

    # Test Suite 3: Microsoft Graph Tests
    try:
        logger.info("📧 Running Microsoft Graph Tests...")
        msgraph_report = await run_msgraph_tests()
        test_results["test_suites"]["msgraph"] = {
            "status": msgraph_report.overall_status,
            "total_tests": msgraph_report.total_tests,
            "passed_tests": msgraph_report.passed_tests,
            "failed_tests": msgraph_report.failed_tests,
            "execution_time_ms": msgraph_report.execution_time_ms,
            "critical_failures": msgraph_report.critical_failures,
            "recommendations": msgraph_report.recommendations[:3]  # Top 3 recommendations
        }
        total_tests += msgraph_report.total_tests
        total_passed += msgraph_report.passed_tests
        total_failed += msgraph_report.failed_tests
        critical_failures += msgraph_report.critical_failures
        if msgraph_report.overall_status != "PASS":
            all_passed = False
    except Exception as e:
        logger.error(f"❌ Microsoft Graph Tests failed: {str(e)}")
        test_results["test_suites"]["msgraph"] = {
            "status": "ERROR",
            "error": str(e)
        }
        all_passed = False

    # Test Suite 4: BuildingConnected Tests
    try:
        logger.info("🏗️  Running BuildingConnected Tests...")
        bc_report = await run_buildingconnected_tests()
        test_results["test_suites"]["buildingconnected"] = {
            "status": bc_report.overall_status,
            "total_tests": bc_report.total_tests,
            "passed_tests": bc_report.passed_tests,
            "failed_tests": bc_report.failed_tests,
            "execution_time_ms": bc_report.execution_time_ms,
            "critical_failures": bc_report.critical_failures,
            "recommendations": bc_report.recommendations[:3]  # Top 3 recommendations
        }
        total_tests += bc_report.total_tests
        total_passed += bc_report.passed_tests
        total_failed += bc_report.failed_tests
        critical_failures += bc_report.critical_failures
        if bc_report.overall_status != "PASS":
            all_passed = False
    except Exception as e:
        logger.error(f"❌ BuildingConnected Tests failed: {str(e)}")
        test_results["test_suites"]["buildingconnected"] = {
            "status": "ERROR",
            "error": str(e)
        }
        all_passed = False

    # Test Suite 5: 8AM Pre-Flight Check (Comprehensive)
    try:
        logger.info("🌅 Running 8AM Pre-Flight Check...")
        preflight_checker = PreFlightChecker()
        preflight_report = await preflight_checker.run_8am_preflight_check()
        test_results["test_suites"]["preflight_8am"] = {
            "status": preflight_report.overall_status,
            "workflow_ready": preflight_report.workflow_ready,
            "total_tests": len(preflight_report.workflow_tests),
            "passed_tests": sum(1 for t in preflight_report.workflow_tests if t.passed),
            "failed_tests": sum(1 for t in preflight_report.workflow_tests if not t.passed),
            "execution_time_ms": preflight_report.total_execution_time_ms,
            "critical_blockers": len(preflight_report.critical_blockers),
            "warnings": len(preflight_report.warnings),
            "recommendations": preflight_report.recommendations[:3]  # Top 3 recommendations
        }
        # Add to totals
        preflight_tests = len(preflight_report.workflow_tests)
        preflight_passed = sum(1 for t in preflight_report.workflow_tests if t.passed)
        preflight_failed = preflight_tests - preflight_passed
        total_tests += preflight_tests
        total_passed += preflight_passed
        total_failed += preflight_failed
        if not preflight_report.workflow_ready:
            all_passed = False
    except Exception as e:
        logger.error(f"❌ 8AM Pre-Flight Check failed: {str(e)}")
        test_results["test_suites"]["preflight_8am"] = {
            "status": "ERROR",
            "error": str(e)
        }
        all_passed = False

    # Overall summary
    test_results["overall_summary"] = {
        "overall_status": "PASS" if all_passed else "FAIL",
        "total_tests": total_tests,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "critical_failures": critical_failures,
        "pass_rate": round((total_passed / total_tests * 100) if total_tests > 0 else 0, 2)
    }
    
    # Log comprehensive failure summary for easy debugging
    if total_failed > 0:
        logger.info("\n" + "="*80)
        logger.info("🚨 COMPREHENSIVE TEST FAILURE SUMMARY")
        logger.info("="*80)
        logger.info(f"Total Failures: {total_failed} out of {total_tests} tests")
        logger.info("This summary provides context for all failing tests across all suites.")
        logger.info("Copy and paste this section for debugging assistance.")
        logger.info("-"*80)
        
        # Simple failure summary since we don't have detailed test data at this level
        for suite_name, suite_data in test_results["test_suites"].items():
            if suite_data.get("failed_tests", 0) > 0:
                logger.info(f"\n🔴 TEST SUITE: {suite_name.upper()}")
                logger.info(f"   Status: {suite_data.get('status', 'UNKNOWN')}")
                logger.info(f"   Failed Tests: {suite_data.get('failed_tests', 0)}")
                logger.info(f"   Total Tests: {suite_data.get('total_tests', 0)}")
                if 'error' in suite_data:
                    logger.info(f"   Suite Error: {suite_data['error']}")
                logger.info("   " + "-"*60)
        
        logger.info("\n💡 DEBUGGING TIPS:")
        logger.info("   1. Check the detailed test logs above for specific test failures")
        logger.info("   2. The test suite logs show individual test names and error messages")
        logger.info("   3. Copy specific test failure details when reporting issues")
        logger.info("   4. Check environment configuration if auth tests are failing")
        logger.info("\n" + "="*80)
        logger.info("END FAILURE SUMMARY")
        logger.info("="*80)
    
    logger.info(f"✅ Test suite execution completed. Overall: {test_results['overall_summary']['overall_status']}")
    return test_results

async def send_test_results_email(test_results: Dict[str, Any]) -> bool:
    """Send detailed test results via email to specified recipients"""
    try:
        # Import and create token manager
        from auth.auth_helpers import create_token_manager_from_env
        from clients.graph_api_client import MSGraphClient
        
        token_manager = create_token_manager_from_env()
        ms_client = MSGraphClient(token_manager)
        
        recipients = "evan@developiq.ai,kush@developiq.ai"
        subject = f"🏥 Northstar System Health Check Report - {test_results['overall_summary']['overall_status']}"
        
        # Create comprehensive HTML email
        status_emoji = "✅" if test_results["overall_summary"]["overall_status"] == "PASS" else "❌"
        
        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .summary {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .test-suite {{ background: white; padding: 15px; border-radius: 8px; margin: 15px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
                .metric {{ margin: 10px 0; }}
                .pass {{ color: #28a745; font-weight: bold; }}
                .fail {{ color: #dc3545; font-weight: bold; }}
                .warning {{ color: #ffc107; font-weight: bold; }}
                .error {{ color: #dc3545; background: #f8d7da; padding: 5px; border-radius: 3px; }}
                .recommendations {{ margin-top: 10px; padding: 10px; background: #d1ecf1; border-radius: 5px; }}
                .recommendations ul {{ margin: 5px 0; padding-left: 20px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>{status_emoji} System Health Check Report</h1>
                <p>Comprehensive test suite execution results</p>
                <p><strong>Overall Status:</strong> {test_results["overall_summary"]["overall_status"]}</p>
            </div>
            
            <div class="content">
                <div class="summary">
                <h3>📊 Executive Summary</h3>
                <div class="metric"><strong>Total Tests:</strong> {test_results["overall_summary"]["total_tests"]}</div>
                <div class="metric"><strong>Passed:</strong> <span class="pass">{test_results["overall_summary"]["total_passed"]}</span></div>
                <div class="metric"><strong>Failed:</strong> <span class="fail">{test_results["overall_summary"]["total_failed"]}</span></div>
                <div class="metric"><strong>Critical Failures:</strong> <span class="fail">{test_results["overall_summary"]["critical_failures"]}</span></div>
                <div class="metric"><strong>Pass Rate:</strong> {test_results["overall_summary"]["pass_rate"]}%</div>
            </div>
        """
        
        # Add details for each test suite
        for suite_name, suite_data in test_results["test_suites"].items():
            status_class = "pass" if suite_data.get("status") == "PASS" else "fail" if suite_data.get("status") in ["FAIL", "ERROR"] else "warning"
            suite_emoji = "✅" if suite_data.get("status") == "PASS" else "❌" if suite_data.get("status") in ["FAIL", "ERROR"] else "⚠️"
            
            html_body += f"""
            <div class="test-suite">
                <h3>{suite_emoji} {suite_name.replace('_', ' ').title()}</h3>
                <p><strong>Status:</strong> <span class="{status_class}">{suite_data.get('status', 'UNKNOWN')}</span></p>
            """
            
            if 'error' in suite_data:
                html_body += f'<p><strong>Error:</strong> <span class="error">{suite_data["error"]}</span></p>'
            else:
                if 'total_tests' in suite_data:
                    html_body += f"""
                    <div class="metric"><strong>Tests:</strong> {suite_data.get('passed_tests', 0)}/{suite_data.get('total_tests', 0)} passed</div>
                    <div class="metric"><strong>Execution Time:</strong> {suite_data.get('execution_time_ms', 0)/1000:.2f}s</div>
                    """
                
                if suite_data.get('recommendations'):
                    html_body += '<div class="recommendations"><strong>Key Recommendations:</strong><ul>'
                    for rec in suite_data['recommendations']:
                        html_body += f'<li>{rec}</li>'
                    html_body += '</ul></div>'
            
            html_body += '</div>'
        
        html_body += """
            <div class="summary">
                <h3>🔗 Next Steps</h3>
                <ul>
                    <li>Review any failed tests and address critical issues</li>
                    <li>Check application logs for detailed error information</li>
                    <li>Verify environment configuration if authentication tests failed</li>
                    <li>Monitor system performance and API response times</li>
                </ul>
                
                <p><strong>Health Check Endpoint:</strong> This report was generated automatically when the /health endpoint was accessed.</p>
                <p><strong>Generated at:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
            </div>
        </body>
        </html>
        """
        
        # Send email
        result = await ms_client.send_email(
            to=recipients,
            subject=subject,
            body=html_body,
            importance="high"
        )
        
        if result.success:
            logger.info(f"✅ Test results email sent successfully to {recipients}")
            return True
        else:
            logger.error(f"❌ Failed to send test results email: {result.error}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error sending test results email: {str(e)}")
        return False

async def proactive_buildingconnected_token_refresh():
    """Proactively refresh BuildingConnected token for health check test suites"""
    logger.info("🔄 Starting proactive BuildingConnected token refresh for health check")
    
    try:
        # Import here to avoid circular imports
        from auth.auth_helpers import create_buildingconnected_token_manager_from_env
        
        # Create fresh token manager
        building_token_manager = create_buildingconnected_token_manager_from_env()
        logger.info("✅ Fresh BuildingConnected token manager created for proactive refresh")
        
        # Force a token refresh by clearing the cached token
        building_token_manager._cached_token = None
        
        # Get a fresh access token (this will refresh and rotate the refresh token)
        fresh_token = await building_token_manager.get_access_token()
        
        if fresh_token and len(fresh_token) > 50:
            logger.info("✅ Proactive token refresh successful - next health check will have fresh tokens")
            logger.info(f"   New token expires at: {datetime.fromtimestamp(building_token_manager._cached_token.expires_at/1000) if building_token_manager._cached_token else 'Unknown'}")
            logger.info("   📝 New refresh token saved to .env and runtime environment")
            return True
        else:
            logger.warning("⚠️ Proactive token refresh returned invalid token")
            return False
            
    except Exception as e:
        # Don't fail the health check if proactive refresh fails
        logger.warning(f"⚠️ Proactive token refresh failed: {str(e)}")
        
        # If this is an invalid_grant error, provide guidance
        if "invalid_grant" in str(e).lower():
            logger.warning("   This suggests the refresh token is already expired")
            logger.warning("   🔧 Solution: Run fresh OAuth flow with:")
            logger.warning("   python -c \"import asyncio; from auth.oauth_setup import setup_autodesk_auth_flow; asyncio.run(setup_autodesk_auth_flow())\"")
        else:
            logger.info("   Next health check may need to handle token refresh")
        
        return False

@app.get("/health", response_model=HealthResponse, summary="Health check with comprehensive test suite")
async def health_check():
    """
    Health check endpoint that runs comprehensive test suite and emails results
    
    This endpoint:
    1. Verifies service status and configuration
    2. Runs all test suites (auth, msgraph, buildingconnected)
    3. Sends detailed email report to evan@developiq.ai and kush@developiq.ai
    4. Proactively refreshes BuildingConnected tokens for next run
    5. Returns health status with test summary
    """
    outlook_vars = ['MS_CLIENT_ID', 'MS_CLIENT_SECRET', 'ENCRYPTED_REFRESH_TOKEN', 'ENCRYPTION_KEY']
    building_vars = ['AUTODESK_CLIENT_ID', 'AUTODESK_CLIENT_SECRET', 'AUTODESK_ENCRYPTED_REFRESH_TOKEN', 'AUTODESK_ENCRYPTION_KEY']
    
    outlook_configured = all(os.getenv(var) for var in outlook_vars)
    building_configured = all(os.getenv(var) for var in building_vars)
    
    both_configured = outlook_configured and building_configured
    
    # Run comprehensive test suite
    test_suite_executed = False
    test_results_summary = None
    email_report_sent = False
    
    try:
        logger.info("🏥 Health check triggered - executing comprehensive test suite")
        test_results = await run_comprehensive_test_suite()
        test_suite_executed = True
        test_results_summary = test_results["overall_summary"]
        
        # Send email report
        if outlook_configured:
            email_report_sent = await send_test_results_email(test_results)
        else:
            logger.warning("⚠️  Outlook not configured - skipping email report")
            
    except Exception as e:
        logger.error(f"❌ Failed to run test suite: {str(e)}")
        test_results_summary = {
            "overall_status": "ERROR",
            "error": str(e)
        }
    
    # Proactively refresh BuildingConnected token for next health check
    # This prevents invalid_grant errors on subsequent health checks
    if building_configured:
        try:
            logger.info("🔄 Running proactive BuildingConnected token refresh for next health check")
            await proactive_buildingconnected_token_refresh()
        except Exception as e:
            logger.warning(f"⚠️ Proactive token refresh failed (non-critical): {str(e)}")
    else:
        logger.info("⏭️ Skipping proactive token refresh - BuildingConnected not configured")
    
    # Determine overall status
    service_status = "healthy" if both_configured else "degraded"
    if test_results_summary and test_results_summary.get("overall_status") != "PASS":
        service_status = "degraded"
    
    return HealthResponse(
        status=service_status,
        outlook_configured=outlook_configured,
        building_configured=building_configured,
        test_suite_executed=test_suite_executed,
        test_results_summary=test_results_summary,
        email_report_sent=email_report_sent
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
        result = await run_bid_reminder()
        
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