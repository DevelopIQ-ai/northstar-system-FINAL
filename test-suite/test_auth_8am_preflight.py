"""
8AM Pre-Flight Authentication Check Suite
Complete end-to-end authentication validation for daily workflow readiness

This combines:
- Core authentication health checks (from auth-health-check.py)  
- Enhanced authentication gap testing (from auth-gaps-tests.py)
- Additional workflow-specific validations

Run this every morning at 8am before executing the main bid reminder workflow.
Exit codes:
- 0: All systems ready for workflow execution
- 1: Critical failures - DO NOT run workflow
- 2: Warnings - Monitor during workflow execution  
- 3: Test suite crashed
"""

import asyncio
import os
import sys
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Import our test suites
import importlib.util

# Import auth health test module
spec1 = importlib.util.spec_from_file_location("test_auth_health", "test-suite/test_auth_health.py")
test_auth_health = importlib.util.module_from_spec(spec1)
spec1.loader.exec_module(test_auth_health)

# Import auth gaps test module  
spec2 = importlib.util.spec_from_file_location("test_auth_gaps", "test-suite/test_auth_gaps.py")
test_auth_gaps = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(test_auth_gaps)

# Import workflow components for end-to-end testing
from auth.auth_helpers import (
    create_token_manager_from_env,
    create_buildingconnected_token_manager_from_env
)
from clients.graph_api_client import MSGraphClient
from clients.buildingconnected_client import BuildingConnectedClient

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/auth-8am-preflight.log')
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class WorkflowReadinessTest:
    """Individual workflow readiness test result"""
    test_name: str
    passed: bool
    message: str
    execution_time_ms: int
    critical: bool
    details: Optional[Dict] = None


@dataclass
class PreFlightReport:
    """Complete 8am pre-flight report"""
    timestamp: str
    workflow_ready: bool
    overall_status: str  # READY, WARNING, CRITICAL
    total_execution_time_ms: int
    
    # Sub-report summaries
    health_check_status: str
    gaps_check_status: str
    workflow_tests_status: str
    
    # Aggregated issues
    critical_blockers: List[str]
    warnings: List[str] 
    recommendations: List[str]
    
    # Test results
    workflow_tests: List[WorkflowReadinessTest]
    
    # Sub-reports (for detailed analysis)
    health_report: Optional[Any] = None
    gaps_report: Optional[Any] = None


class PreFlightChecker:
    """8AM Pre-flight authentication checker"""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.critical_blockers: List[str] = []
        self.warnings: List[str] = []
        self.recommendations: List[str] = []
        self.workflow_tests: List[WorkflowReadinessTest] = []
        
        # Persistent token managers to handle Autodesk token rotation
        self.ms_token_manager = None
        self.bc_token_manager = None
        
    async def initialize_token_managers(self):
        """Initialize persistent token managers for testing"""
        try:
            self.ms_token_manager = create_token_manager_from_env()
            self.bc_token_manager = create_buildingconnected_token_manager_from_env()
            logger.info("✅ Initialized persistent token managers for pre-flight testing")
        except Exception as e:
            logger.error(f"❌ Failed to initialize token managers: {str(e)}")
            self.critical_blockers.append(f"Token manager initialization failed: {str(e)}")
            raise
        
    async def run_8am_preflight_check(self) -> PreFlightReport:
        """Run complete 8AM pre-flight authentication check"""
        logger.info("🌅 Starting 8AM Pre-Flight Authentication Check")
        logger.info("="*80)
        logger.info(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*80)
        
        # Initialize persistent token managers first
        await self.initialize_token_managers()
        
        # Step 1: Run comprehensive health check (using shared token managers)
        logger.info("📋 Step 1: Running Comprehensive Authentication Health Check...")
        health_checker = test_auth_health.AuthHealthChecker()
        # Share our token managers to avoid token rotation issues
        health_checker.ms_token_manager = self.ms_token_manager
        health_checker.bc_token_manager = self.bc_token_manager
        health_report = await health_checker.run_all_tests()
        logger.info(f"   Health Check Result: {health_report.overall_status}")
        
        # Step 2: Run authentication gaps testing (using shared token managers)
        logger.info("🔍 Step 2: Running Authentication Gaps Testing...")
        gaps_tester = test_auth_gaps.AuthGapsTester()
        # Share our token managers to avoid token rotation issues
        gaps_tester.ms_token_manager = self.ms_token_manager
        gaps_tester.bc_token_manager = self.bc_token_manager
        gaps_report = await gaps_tester.run_all_gap_tests()
        logger.info(f"   Gaps Check Result: {gaps_report.overall_status}")
        
        # Step 3: Run workflow-specific readiness tests
        logger.info("🚀 Step 3: Running Workflow Readiness Tests...")
        await self._test_workflow_readiness()
        workflow_tests_passed = sum(1 for t in self.workflow_tests if t.passed)
        workflow_tests_total = len(self.workflow_tests)
        workflow_critical_failed = sum(1 for t in self.workflow_tests if not t.passed and t.critical)
        workflow_tests_status = "FAIL" if workflow_critical_failed > 0 else ("PASS" if workflow_tests_passed == workflow_tests_total else "WARNING")
        logger.info(f"   Workflow Tests Result: {workflow_tests_status} ({workflow_tests_passed}/{workflow_tests_total})")
        
        # Aggregate results
        overall_status, workflow_ready = self._determine_overall_status(
            health_report, gaps_report, workflow_tests_status
        )
        
        # Aggregate issues
        self._aggregate_issues(health_report, gaps_report)
        
        total_execution_time = int((datetime.now() - self.start_time).total_seconds() * 1000)
        
        return PreFlightReport(
            timestamp=self.start_time.isoformat(),
            workflow_ready=workflow_ready,
            overall_status=overall_status,
            total_execution_time_ms=total_execution_time,
            health_check_status=health_report.overall_status,
            gaps_check_status=gaps_report.overall_status,
            workflow_tests_status=workflow_tests_status,
            critical_blockers=self.critical_blockers,
            warnings=self.warnings,
            recommendations=self.recommendations,
            workflow_tests=self.workflow_tests,
            health_report=health_report,
            gaps_report=gaps_report
        )
    
    async def _test_workflow_readiness(self):
        """Test specific workflow readiness scenarios"""
        
        # Test 1: Email recipient validation
        await self._test_email_recipient_validation()
        
        # Test 2: Project data availability
        await self._test_project_data_availability()
        
        # Test 3: End-to-end email sending capability
        await self._test_email_sending_capability()
        
        # Test 4: Token expiration buffer check
        await self._test_token_expiration_buffer()
        
        # Test 5: Workflow timing validation
        await self._test_workflow_timing()
        
        # Test 6: Environment completeness for workflow
        await self._test_workflow_environment()
    
    async def _test_email_recipient_validation(self):
        """Test 1: Email Recipient Validation"""
        start_time = datetime.now()
        
        try:
            default_recipient = os.getenv('DEFAULT_EMAIL_RECIPIENT')
            
            if not default_recipient:
                self.critical_blockers.append("DEFAULT_EMAIL_RECIPIENT environment variable not set")
                self.workflow_tests.append(WorkflowReadinessTest(
                    "email_recipient_validation", False, 
                    "❌ No default email recipient configured", 
                    0, True, {"recipient": None}
                ))
                return
            
            # Validate email format
            import re
            email_pattern = r'^[a-zA-Z0-9.!#$%&\'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$'
            
            if not re.match(email_pattern, default_recipient):
                self.critical_blockers.append(f"Invalid email format: {default_recipient}")
                self.workflow_tests.append(WorkflowReadinessTest(
                    "email_recipient_validation", False,
                    f"❌ Invalid email format: {default_recipient}",
                    0, True, {"recipient": default_recipient, "valid": False}
                ))
                return
            
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            self.workflow_tests.append(WorkflowReadinessTest(
                "email_recipient_validation", True,
                f"✅ Email recipient validated: {default_recipient}",
                execution_time, False, {"recipient": default_recipient, "valid": True}
            ))
            
        except Exception as e:
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            self.critical_blockers.append(f"Email recipient validation failed: {str(e)}")
            self.workflow_tests.append(WorkflowReadinessTest(
                "email_recipient_validation", False,
                f"❌ Email recipient validation error: {str(e)}",
                execution_time, True, {"error": str(e)}
            ))
    
    async def _test_project_data_availability(self):
        """Test 2: Project Data Availability for Workflow"""
        start_time = datetime.now()
        
        try:
            # Try to connect and get projects data
            bc_token_manager = self.bc_token_manager  # Use persistent token manager
            bc_client = BuildingConnectedClient(bc_token_manager)
            
            # Get projects due in 5-10 days (workflow range)
            projects_5_days = await bc_client.get_projects_due_in_n_days(5)
            projects_6_days = await bc_client.get_projects_due_in_n_days(6)
            projects_7_days = await bc_client.get_projects_due_in_n_days(7)
            projects_8_days = await bc_client.get_projects_due_in_n_days(8)
            projects_9_days = await bc_client.get_projects_due_in_n_days(9)
            projects_10_days = await bc_client.get_projects_due_in_n_days(10)
            
            total_upcoming_projects = (
                projects_5_days.total + projects_6_days.total + projects_7_days.total +
                projects_8_days.total + projects_9_days.total + projects_10_days.total
            )
            
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            
            details = {
                "projects_5_days": projects_5_days.total,
                "projects_6_days": projects_6_days.total,
                "projects_7_days": projects_7_days.total,
                "projects_8_days": projects_8_days.total,
                "projects_9_days": projects_9_days.total,
                "projects_10_days": projects_10_days.total,
                "total_upcoming": total_upcoming_projects
            }
            
            if total_upcoming_projects == 0:
                self.warnings.append("No projects found due in 5-10 days - workflow may have nothing to process")
                self.workflow_tests.append(WorkflowReadinessTest(
                    "project_data_availability", True,
                    f"⚠️ No projects due in 5-10 days (workflow will run but process nothing)",
                    execution_time, False, details
                ))
            else:
                self.workflow_tests.append(WorkflowReadinessTest(
                    "project_data_availability", True,
                    f"✅ {total_upcoming_projects} projects due in 5-10 days",
                    execution_time, False, details
                ))
            
        except Exception as e:
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            self.critical_blockers.append(f"Cannot access project data: {str(e)}")
            self.workflow_tests.append(WorkflowReadinessTest(
                "project_data_availability", False,
                f"❌ Project data access failed: {str(e)}",
                execution_time, True, {"error": str(e)}
            ))
    
    async def _test_email_sending_capability(self):
        """Test 3: End-to-End Email Sending Capability (Dry Run)"""
        start_time = datetime.now()
        
        try:
            ms_token_manager = self.ms_token_manager  # Use persistent token manager
            ms_client = MSGraphClient(ms_token_manager)
            
            # Try a dry run email send test (we'll catch before actually sending)
            default_recipient = os.getenv('DEFAULT_EMAIL_RECIPIENT')
            if not default_recipient:
                raise ValueError("No DEFAULT_EMAIL_RECIPIENT configured")
            
            # Test email composition and API readiness
            test_subject = "[TEST] 8AM Pre-flight Check - Do Not Process"
            test_body = """<html><body>
<h2>8AM Authentication Pre-flight Test</h2>
<p>This is a test email from the authentication pre-flight checker.</p>
<p>If you receive this email, email sending capability is working.</p>
<p><strong>Time:</strong> {}</p>
</body></html>""".format(datetime.now().isoformat())
            
            # We'll actually send this test email to verify capability
            result = await ms_client.send_email(
                to=default_recipient,
                subject=test_subject,
                body=test_body,
                importance="normal"
            )
            
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            
            if result.success:
                self.workflow_tests.append(WorkflowReadinessTest(
                    "email_sending_capability", True,
                    f"✅ Email sending capability verified (test email sent)",
                    execution_time, False, {"test_email_sent": True, "recipient": default_recipient}
                ))
            else:
                self.critical_blockers.append(f"Email sending failed: {result.error}")
                self.workflow_tests.append(WorkflowReadinessTest(
                    "email_sending_capability", False,
                    f"❌ Email sending failed: {result.error}",
                    execution_time, True, {"test_email_sent": False, "error": result.error}
                ))
            
        except Exception as e:
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            self.critical_blockers.append(f"Email sending test failed: {str(e)}")
            self.workflow_tests.append(WorkflowReadinessTest(
                "email_sending_capability", False,
                f"❌ Email sending test error: {str(e)}",
                execution_time, True, {"error": str(e)}
            ))
    
    async def _test_token_expiration_buffer(self):
        """Test 4: Token Expiration Buffer Check"""
        start_time = datetime.now()
        
        try:
            # Check both tokens have sufficient time remaining
            ms_token_manager = self.ms_token_manager  # Use persistent token manager
            bc_token_manager = self.bc_token_manager  # Use persistent token manager
            
            # Get tokens to populate cache
            await ms_token_manager.get_access_token()
            await bc_token_manager.get_access_token()
            
            current_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            
            # Check Microsoft Graph token
            ms_buffer_ok = True
            ms_minutes_remaining = 0
            if ms_token_manager._cached_token:
                ms_expires_at = ms_token_manager._cached_token.expires_at
                ms_minutes_remaining = (ms_expires_at - current_time_ms) / (1000 * 60)
                ms_buffer_ok = ms_minutes_remaining > 30  # Need at least 30 minutes
            
            # Check BuildingConnected token
            bc_buffer_ok = True
            bc_minutes_remaining = 0
            if bc_token_manager._cached_token:
                bc_expires_at = bc_token_manager._cached_token.expires_at
                bc_minutes_remaining = (bc_expires_at - current_time_ms) / (1000 * 60)
                bc_buffer_ok = bc_minutes_remaining > 30  # Need at least 30 minutes
            
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            overall_buffer_ok = ms_buffer_ok and bc_buffer_ok
            
            details = {
                "ms_minutes_remaining": ms_minutes_remaining,
                "bc_minutes_remaining": bc_minutes_remaining,
                "ms_buffer_ok": ms_buffer_ok,
                "bc_buffer_ok": bc_buffer_ok,
                "required_buffer_minutes": 30
            }
            
            if overall_buffer_ok:
                self.workflow_tests.append(WorkflowReadinessTest(
                    "token_expiration_buffer", True,
                    f"✅ Token expiration buffer sufficient (MS: {ms_minutes_remaining:.1f}m, BC: {bc_minutes_remaining:.1f}m)",
                    execution_time, False, details
                ))
            else:
                self.warnings.append(f"Token expiration buffer low - MS: {ms_minutes_remaining:.1f}m, BC: {bc_minutes_remaining:.1f}m")
                self.workflow_tests.append(WorkflowReadinessTest(
                    "token_expiration_buffer", False,
                    f"⚠️ Token expiration buffer low (MS: {ms_minutes_remaining:.1f}m, BC: {bc_minutes_remaining:.1f}m)",
                    execution_time, False, details
                ))
            
        except Exception as e:
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            self.warnings.append(f"Token expiration buffer check failed: {str(e)}")
            self.workflow_tests.append(WorkflowReadinessTest(
                "token_expiration_buffer", False,
                f"⚠️ Token expiration check error: {str(e)}",
                execution_time, False, {"error": str(e)}
            ))
    
    async def _test_workflow_timing(self):
        """Test 5: Workflow Timing Validation"""
        start_time = datetime.now()
        
        try:
            current_time = datetime.now()
            current_hour = current_time.hour
            
            # Optimal workflow time is 8am - 10am
            timing_optimal = 8 <= current_hour <= 10
            
            # Acceptable workflow time is 6am - 12pm
            timing_acceptable = 6 <= current_hour <= 12
            
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            
            details = {
                "current_time": current_time.isoformat(),
                "current_hour": current_hour,
                "optimal_time": timing_optimal,
                "acceptable_time": timing_acceptable
            }
            
            if timing_optimal:
                self.workflow_tests.append(WorkflowReadinessTest(
                    "workflow_timing", True,
                    f"✅ Optimal workflow execution time ({current_hour}:00)",
                    execution_time, False, details
                ))
            elif timing_acceptable:
                self.warnings.append(f"Workflow running outside optimal hours (current: {current_hour}:00)")
                self.workflow_tests.append(WorkflowReadinessTest(
                    "workflow_timing", True,
                    f"⚠️ Acceptable workflow time ({current_hour}:00) - optimal is 8am-10am",
                    execution_time, False, details
                ))
            else:
                self.warnings.append(f"Workflow running outside recommended hours (current: {current_hour}:00)")
                self.workflow_tests.append(WorkflowReadinessTest(
                    "workflow_timing", False,
                    f"⚠️ Non-optimal workflow time ({current_hour}:00) - recommend 6am-12pm",
                    execution_time, False, details
                ))
            
        except Exception as e:
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            self.workflow_tests.append(WorkflowReadinessTest(
                "workflow_timing", True,
                f"ℹ️ Workflow timing check error: {str(e)}",
                execution_time, False, {"error": str(e)}
            ))
    
    async def _test_workflow_environment(self):
        """Test 6: Workflow Environment Completeness"""
        start_time = datetime.now()
        
        try:
            required_vars = [
                'MS_CLIENT_ID', 'MS_CLIENT_SECRET', 'ENCRYPTED_REFRESH_TOKEN', 'ENCRYPTION_KEY',
                'AUTODESK_CLIENT_ID', 'AUTODESK_CLIENT_SECRET', 'AUTODESK_ENCRYPTED_REFRESH_TOKEN', 'AUTODESK_ENCRYPTION_KEY',
                'DEFAULT_EMAIL_RECIPIENT'
            ]
            
            optional_vars = [
                'LANGSMITH_TRACING', 'LANGSMITH_API_KEY', 'ENVIRONMENT'
            ]
            
            missing_required = [var for var in required_vars if not os.getenv(var)]
            missing_optional = [var for var in optional_vars if not os.getenv(var)]
            present_required = [var for var in required_vars if os.getenv(var)]
            present_optional = [var for var in optional_vars if os.getenv(var)]
            
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            
            details = {
                "required_vars_present": len(present_required),
                "required_vars_total": len(required_vars),
                "optional_vars_present": len(present_optional),
                "optional_vars_total": len(optional_vars),
                "missing_required": missing_required,
                "missing_optional": missing_optional
            }
            
            if not missing_required:
                message = f"✅ All required environment variables present ({len(present_required)}/{len(required_vars)})"
                if missing_optional:
                    message += f", {len(missing_optional)} optional vars missing"
                
                self.workflow_tests.append(WorkflowReadinessTest(
                    "workflow_environment", True, message, execution_time, False, details
                ))
            else:
                self.critical_blockers.append(f"Missing required environment variables: {missing_required}")
                self.workflow_tests.append(WorkflowReadinessTest(
                    "workflow_environment", False,
                    f"❌ Missing required environment variables: {missing_required}",
                    execution_time, True, details
                ))
            
        except Exception as e:
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            self.critical_blockers.append(f"Environment check failed: {str(e)}")
            self.workflow_tests.append(WorkflowReadinessTest(
                "workflow_environment", False,
                f"❌ Environment check error: {str(e)}",
                execution_time, True, {"error": str(e)}
            ))
    
    def _determine_overall_status(self, health_report, gaps_report, workflow_status):
        """Determine overall status and workflow readiness"""
        
        # Check for critical blockers
        if (health_report.overall_status == "FAIL" or 
            gaps_report.overall_status == "CRITICAL" or
            workflow_status == "FAIL" or
            len(self.critical_blockers) > 0):
            return "CRITICAL", False
        
        # Check for warnings
        if (health_report.overall_status == "WARNING" or
            gaps_report.overall_status == "WARNING" or
            workflow_status == "WARNING" or
            len(self.warnings) > 0):
            return "WARNING", True
        
        # All good
        return "READY", True
    
    def _aggregate_issues(self, health_report, gaps_report):
        """Aggregate issues from all test suites"""
        
        # Add critical failures from health report
        if health_report.critical_failures:
            self.critical_blockers.extend(health_report.critical_failures)
        
        # Add warnings from health report
        if health_report.warnings:
            self.warnings.extend(health_report.warnings)
        
        # Add critical issues from gaps report
        if gaps_report.critical_issues:
            self.critical_blockers.extend(gaps_report.critical_issues)
        
        # Add warnings from gaps report
        if gaps_report.warnings:
            self.warnings.extend(gaps_report.warnings)
        
        # Add recommendations from gaps report
        if gaps_report.recommendations:
            self.recommendations.extend(gaps_report.recommendations)
        
        # Add workflow-specific recommendations
        if len(self.critical_blockers) > 0:
            self.recommendations.append("Run 'python auth/setup_bid_reminder.py' to reconfigure authentication")
        
        if len(self.warnings) > 0:
            self.recommendations.append("Monitor workflow execution closely for authentication issues")


async def run_8am_preflight() -> PreFlightReport:
    """Main function to run 8AM pre-flight check"""
    checker = PreFlightChecker()
    return await checker.run_8am_preflight_check()


def print_preflight_report(report: PreFlightReport):
    """Print formatted 8AM pre-flight report"""
    print("\n" + "="*90)
    print("🌅 8AM PRE-FLIGHT AUTHENTICATION CHECK REPORT")
    print("="*90)
    print(f"Timestamp: {report.timestamp}")
    print(f"Workflow Ready: {'✅ YES' if report.workflow_ready else '❌ NO'}")
    print(f"Overall Status: {report.overall_status}")
    print(f"Total Execution Time: {report.total_execution_time_ms}ms")
    print()
    print(f"📊 Sub-System Status:")
    print(f"  🏥 Health Check:     {report.health_check_status}")
    print(f"  🔍 Gaps Check:       {report.gaps_check_status}")
    print(f"  🚀 Workflow Tests:   {report.workflow_tests_status}")
    
    if report.critical_blockers:
        print(f"\n🚨 CRITICAL BLOCKERS ({len(report.critical_blockers)}):")
        for blocker in report.critical_blockers:
            print(f"  ❌ {blocker}")
    
    if report.warnings:
        print(f"\n⚠️  WARNINGS ({len(report.warnings)}):")
        for warning in report.warnings:
            print(f"  ⚠️  {warning}")
    
    if report.recommendations:
        print(f"\n💡 RECOMMENDATIONS ({len(report.recommendations)}):")
        for rec in report.recommendations:
            print(f"  💡 {rec}")
    
    print(f"\n🧪 WORKFLOW READINESS TESTS:")
    for test in report.workflow_tests:
        icon = "🚨" if test.critical and not test.passed else "⚠️" if not test.passed else "✅"
        print(f"  {icon} {test.test_name:<30} | {test.execution_time_ms:>5}ms | {test.message}")
    
    # Decision recommendation
    print("\n" + "="*90)
    if report.workflow_ready:
        if report.overall_status == "READY":
            print("🟢 DECISION: PROCEED with bid reminder workflow execution")
            print("   All systems are healthy and ready for normal operation.")
        else:
            print("🟡 DECISION: PROCEED with bid reminder workflow execution (with monitoring)")
            print("   Workflow can run but monitor for issues during execution.")
    else:
        print("🔴 DECISION: DO NOT RUN bid reminder workflow")
        print("   Critical authentication issues must be resolved first.")
        print("   Run: python auth/setup_bid_reminder.py")
    print("="*90)
    
    # Save detailed report
    try:
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"logs/auth-8am-preflight-{timestamp_str}.json"
        
        # Convert dataclasses to dicts for JSON serialization
        report_dict = {
            "timestamp": report.timestamp,
            "workflow_ready": report.workflow_ready,
            "overall_status": report.overall_status,
            "total_execution_time_ms": report.total_execution_time_ms,
            "health_check_status": report.health_check_status,
            "gaps_check_status": report.gaps_check_status,
            "workflow_tests_status": report.workflow_tests_status,
            "critical_blockers": report.critical_blockers,
            "warnings": report.warnings,
            "recommendations": report.recommendations,
            "workflow_tests": [
                {
                    "test_name": t.test_name,
                    "passed": t.passed,
                    "message": t.message,
                    "execution_time_ms": t.execution_time_ms,
                    "critical": t.critical,
                    "details": t.details
                }
                for t in report.workflow_tests
            ]
        }
        
        os.makedirs("test-suite", exist_ok=True)
        with open(report_file, 'w') as f:
            json.dump(report_dict, f, indent=2)
        
        print(f"📄 Detailed pre-flight report saved to: {report_file}")
        
    except Exception as e:
        logger.error(f"Failed to save pre-flight report: {str(e)}")


if __name__ == "__main__":
    async def main():
        print("🌅 Starting 8AM Pre-Flight Authentication Check...")
        print("This comprehensive check validates all authentication components")
        print("before executing the daily bid reminder workflow.\n")
        
        try:
            report = await run_8am_preflight()
            print_preflight_report(report)
            
            # Exit with appropriate code for automation
            if not report.workflow_ready:
                print(f"\n🚨 CRITICAL: Workflow is NOT ready for execution!")
                print("   Resolve critical issues before attempting to run workflow.")
                exit(1)
            elif report.overall_status == "WARNING":
                print(f"\n⚠️  WARNING: Workflow ready with warnings.")
                print("   Monitor workflow execution for potential issues.")
                exit(2)
            else:
                print(f"\n✅ SUCCESS: Workflow is ready for execution!")
                print("   All authentication systems are healthy.")
                exit(0)
                
        except Exception as e:
            logger.error(f"8AM pre-flight check failed with exception: {str(e)}")
            print(f"\n💥 EXCEPTION: 8AM pre-flight check crashed: {str(e)}")
            print("   Cannot determine workflow readiness - do not run workflow.")
            exit(3)
    
    asyncio.run(main())