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
from sentry_config import (
    init_sentry, set_health_check_context, capture_exception_with_context,
    capture_message_with_context, add_breadcrumb, create_transaction,
    SentryOperations, SentryComponents, SentrySeverity
)

from fastapi import FastAPI, HTTPException, status, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from bid_reminder_agent import run_bid_reminder

# Load environment variables
load_dotenv()

# Configure logging first - optimized for Railway + Sentry
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Railway captures stdout/stderr
    ]
)

# Sentry logging is now handled by centralized configuration
logger = logging.getLogger(__name__)

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

# Initialize Sentry with enhanced configuration
sentry_initialized = init_sentry(component=SentryComponents.API)
if sentry_initialized:
    logger.info("✅ Sentry initialized for API component with enhanced configuration")
else:
    logger.warning("⚠️ Sentry not initialized - SENTRY_DSN not configured")

# Global state for graceful shutdown
shutdown_event = asyncio.Event()
active_connections = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    logger.info("🚀 Starting Bid Reminder Agent API...")
    
    # Add Sentry breadcrumb for startup
    add_breadcrumb(
        message="API startup initiated",
        category="lifecycle",
        level="info",
        data={"component": "api", "action": "startup"}
    )
    
    # Check environment configuration
    outlook_vars = ['MS_CLIENT_ID', 'MS_CLIENT_SECRET', 'MS_ENCRYPTED_REFRESH_TOKEN', 'MS_ENCRYPTION_KEY']
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
    
    # Add Sentry breadcrumb for shutdown
    add_breadcrumb(
        message="API shutdown initiated",
        category="lifecycle",
        level="info",
        data={"component": "api", "action": "shutdown"}
    )
    
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
    """Proactively refresh both Microsoft Graph and BuildingConnected tokens after health check"""
    logger.info("🔄 Starting proactive token refresh for both services (post-health-check)")
    
    ms_success = False
    bc_success = False
    
    try:
        # Import here to avoid circular imports
        from auth.auth_helpers import create_token_manager_from_env, create_buildingconnected_token_manager_from_env
        
        # Refresh Microsoft Graph tokens
        try:
            logger.info("   🔄 Refreshing Microsoft Graph tokens...")
            ms_token_manager = create_token_manager_from_env()
            ms_token_manager._cached_token = None  # Force refresh
            fresh_ms_token = await ms_token_manager.get_access_token()
            
            if fresh_ms_token and len(fresh_ms_token) > 50:
                ms_success = True
                logger.info("   ✅ Microsoft Graph token refresh successful")
                logger.info(f"      New token expires at: {datetime.fromtimestamp(ms_token_manager._cached_token.expires_at/1000) if ms_token_manager._cached_token else 'Unknown'}")
            else:
                logger.warning("   ⚠️ Microsoft Graph token refresh returned invalid token")
        except Exception as e:
            logger.error(f"   ❌ Microsoft Graph token refresh failed: {str(e)}")
        
        # Refresh BuildingConnected tokens 
        try:
            logger.info("   🔄 Refreshing BuildingConnected tokens...")
            bc_token_manager = create_buildingconnected_token_manager_from_env()
            bc_token_manager._cached_token = None  # Force refresh
            fresh_bc_token = await bc_token_manager.get_access_token()
            
            if fresh_bc_token and len(fresh_bc_token) > 50:
                bc_success = True
                logger.info("   ✅ BuildingConnected token refresh successful")
                logger.info(f"      New token expires at: {datetime.fromtimestamp(bc_token_manager._cached_token.expires_at/1000) if bc_token_manager._cached_token else 'Unknown'}")
                logger.info("      📝 New refresh token rotated and saved to .env file")
            else:
                logger.warning("   ⚠️ BuildingConnected token refresh returned invalid token")
        except Exception as e:
            logger.error(f"   ❌ BuildingConnected token refresh failed: {str(e)}")
            
            # If this is an invalid_grant error, provide guidance
            if "invalid_grant" in str(e).lower():
                logger.warning("      This suggests the refresh token is already expired")
                logger.warning("      🔧 Solution: Run fresh OAuth flow with:")
                logger.warning("      python -c \"import asyncio; from auth.oauth_setup import setup_autodesk_auth_flow; asyncio.run(setup_autodesk_auth_flow())\"")
        
        # Summary
        if ms_success and bc_success:
            logger.info("🎉 Both token refreshes successful - fresh tokens ready for bid reminders")
            return True
        elif ms_success or bc_success:
            logger.warning(f"⚠️ Partial token refresh success: MS={ms_success}, BC={bc_success}")
            return True  # Partial success is still useful
        else:
            logger.error("❌ All token refreshes failed")
            return False
            
    except Exception as e:
        # Don't fail the health check if proactive refresh fails
        logger.error(f"❌ Critical error in proactive token refresh: {str(e)}")
        return False

@app.get("/health", response_model=HealthResponse, summary="Health check with comprehensive test suite")
async def health_check():
    """
    Comprehensive health check that runs full test suite and reports results
    
    This endpoint:
    1. Validates environment configuration
    2. Runs comprehensive authentication tests
    3. Tests API connectivity and functionality
    4. Sends email report of test results
    5. Refreshes tokens to ensure fresh tokens for bid reminders
    
    Returns summary of health status and test results.
    """
    # Set health check context for Sentry
    set_health_check_context("comprehensive", "starting")
    
    # Create Sentry transaction for performance monitoring
    with create_transaction(
        name="health_check_comprehensive",
        operation=SentryOperations.HEALTH_CHECK,
        component=SentryComponents.API,
        description="Comprehensive health check with test suites"
    ) as transaction:
        
        logger.info("🏥 Starting comprehensive health check...")
        
        add_breadcrumb(
            message="Health check started",
            category="health_check",
            level="info",
            data={"type": "comprehensive"}
        )
    
    # Check basic environment configuration
    outlook_configured = all(os.getenv(var) for var in ['MS_CLIENT_ID', 'MS_CLIENT_SECRET', 'MS_ENCRYPTION_KEY'])
    building_configured = all(os.getenv(var) for var in ['AUTODESK_CLIENT_ID', 'AUTODESK_CLIENT_SECRET', 'AUTODESK_ENCRYPTION_KEY'])
    
    test_results_summary = None
    test_suite_executed = False
    email_report_sent = False
    
    try:
        if TEST_SUITES_AVAILABLE and outlook_configured and building_configured:
            logger.info("📋 Running comprehensive test suite...")
            
            add_breadcrumb(
                message="Starting test suite execution",
                category="health_check", 
                level="info",
                data={"outlook_configured": outlook_configured, "building_configured": building_configured}
            )
            
            set_health_check_context("test_suite", "running")
            test_results = await run_comprehensive_test_suite()
            test_results_summary = test_results
            test_suite_executed = True
            
            # Send email report of test results
            try:
                set_health_check_context("email_report", "sending")
                email_report_sent = await send_test_results_email(test_results)
                
                add_breadcrumb(
                    message="Email report sent",
                    category="health_check",
                    level="info", 
                    data={"success": email_report_sent}
                )
            except Exception as e:
                logger.error(f"❌ Failed to send test results email: {e}")
                
                capture_exception_with_context(
                    e,
                    operation=SentryOperations.HEALTH_CHECK,
                    component=SentryComponents.API,
                    severity=SentrySeverity.MEDIUM,
                    extra_context={"stage": "email_report", "action": "send_results"}
                )
            
            # CRITICAL: Refresh tokens after health check to leave fresh tokens for bid reminders
            logger.info("🔄 Refreshing tokens to ensure fresh tokens for bid reminders...")
            
            set_health_check_context("token_refresh", "starting")
            try:
                await proactive_buildingconnected_token_refresh()
                logger.info("✅ Token refresh completed - fresh tokens ready for bid reminders")
                
                add_breadcrumb(
                    message="Token refresh completed",
                    category="health_check",
                    level="info",
                    data={"action": "proactive_refresh"}
                )
            except Exception as e:
                logger.error(f"❌ Failed to refresh tokens after health check: {e}")
                
                capture_exception_with_context(
                    e,
                    operation=SentryOperations.HEALTH_CHECK,
                    component=SentryComponents.API,
                    severity=SentrySeverity.HIGH,
                    extra_context={"stage": "token_refresh", "action": "proactive_refresh"}
                )
        else:
            set_health_check_context("configuration", "degraded")
            
            config_issues = []
            if not TEST_SUITES_AVAILABLE:
                logger.warning("⚠️  Test suites not available")
                config_issues.append("test_suites_unavailable")
            if not outlook_configured:
                logger.warning("⚠️  Outlook not configured")
                config_issues.append("outlook_not_configured")
            if not building_configured:
                logger.warning("⚠️  BuildingConnected not configured")
                config_issues.append("building_connected_not_configured")
            
            capture_message_with_context(
                "Health check configuration issues detected",
                "warning",
                operation=SentryOperations.HEALTH_CHECK,
                component=SentryComponents.API,
                extra_context={"issues": config_issues}
            )
    
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        
        # Capture the health check failure
        capture_exception_with_context(
            e,
            operation=SentryOperations.HEALTH_CHECK,
            component=SentryComponents.API,
            severity=SentrySeverity.CRITICAL,
            extra_context={"stage": "main_health_check"}
        )
        
        # Even if health check fails, try to refresh tokens
        try:
            logger.info("🔄 Attempting token refresh despite health check failure...")
            set_health_check_context("token_refresh", "fallback")
            await proactive_buildingconnected_token_refresh()
            logger.info("✅ Token refresh completed despite health check failure")
        except Exception as refresh_error:
            logger.error(f"❌ Failed to refresh tokens after health check failure: {refresh_error}")
            
            capture_exception_with_context(
                refresh_error,
                operation=SentryOperations.HEALTH_CHECK,
                component=SentryComponents.API,
                severity=SentrySeverity.CRITICAL,
                extra_context={"stage": "fallback_token_refresh"}
            )
    
        status = "healthy" if (outlook_configured and building_configured) else "degraded"
        
        # Final health check status
        set_health_check_context("final", status)
        
        add_breadcrumb(
            message="Health check completed",
            category="health_check",
            level="info",
            data={
                "status": status,
                "test_suite_executed": test_suite_executed,
                "email_report_sent": email_report_sent
            }
        )
        
        transaction.set_data("health_status", status)
        transaction.set_data("test_suite_executed", test_suite_executed)
        
        return HealthResponse(
            status=status,
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
    # Create Sentry transaction for workflow monitoring
    with create_transaction(
        name="bid_reminder_workflow",
        operation=SentryOperations.BID_REMINDER,
        component=SentryComponents.API,
        description="Main bid reminder workflow execution"
    ) as transaction:
        
        add_breadcrumb(
            message="Bid reminder workflow started",
            category="workflow",
            level="info",
            data={"endpoint": "/run-bid-reminder"}
        )
        
        try:
            # Run the bid reminder workflow
            result = await run_bid_reminder()
        
            # Extract project count
            upcoming_projects = result.get("upcoming_projects", [])
            projects_found = len(upcoming_projects) if upcoming_projects else 0
            
            # Set transaction data
            transaction.set_data("projects_found", projects_found)
            transaction.set_data("workflow_successful", result.get('workflow_successful', False))
            transaction.set_data("email_sent", result.get('reminder_email_sent', False))
            
            add_breadcrumb(
                message="Bid reminder workflow completed",
                category="workflow",
                level="info",
                data={
                    "projects_found": projects_found,
                    "workflow_successful": result.get('workflow_successful', False)
                }
            )
            
            return BidReminderResponse(
                workflow_successful=result.get('workflow_successful', False),
                result_message=result.get('result_message'),
                error_message=result.get('error_message'),
                projects_found=projects_found,
                email_sent=result.get('reminder_email_sent', False)
            )
        
        except Exception as e:
            # Capture workflow failure
            capture_exception_with_context(
                e,
                operation=SentryOperations.BID_REMINDER,
                component=SentryComponents.API,
                severity=SentrySeverity.CRITICAL,
                extra_context={"endpoint": "/run-bid-reminder", "stage": "workflow_execution"}
            )
            
            transaction.set_tag("error", True)
            transaction.set_data("error_message", str(e))
            
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