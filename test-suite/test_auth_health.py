"""
Comprehensive Authentication Health Check Suite
Tests all potential authentication edge cases identified in ISSUES.md

Run this daily at 8am before the main workflow to ensure auth is working
"""

import asyncio
import os
import sys
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import json

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
import httpx

# Import our auth components
from auth.auth_helpers import (
    create_token_manager_from_env,
    create_buildingconnected_token_manager_from_env,
    MSGraphTokenManager,
    BuildingConnectedTokenManager
)
from clients.graph_api_client import MSGraphClient
from clients.buildingconnected_client import BuildingConnectedClient

load_dotenv()

# Ensure logs directory exists
os.makedirs('logs', exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/auth-health-check.log')
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Individual test result"""
    test_name: str
    passed: bool
    message: str
    execution_time_ms: int
    details: Optional[Dict] = None


@dataclass
class HealthCheckReport:
    """Complete health check report"""
    timestamp: str
    overall_status: str  # PASS/FAIL/WARNING
    total_tests: int
    passed_tests: int
    failed_tests: int
    execution_time_ms: int
    test_results: List[TestResult]
    critical_failures: List[str]
    warnings: List[str]


class AuthHealthChecker:
    """Comprehensive authentication health checker"""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.test_results: List[TestResult] = []
        self.critical_failures: List[str] = []
        self.warnings: List[str] = []
        
        # Create persistent token managers to handle refresh token rotation properly
        self.ms_token_manager = None
        self.bc_token_manager = None
        
    async def run_all_tests(self) -> HealthCheckReport:
        """Run all authentication health checks"""
        logger.info("🏥 Starting comprehensive authentication health check")
        logger.info("="*60)
        
        # Environment variable tests
        await self._test_environment_variables()
        
        # Token manager creation tests
        await self._test_token_manager_creation()
        
        # Token decryption tests
        await self._test_token_decryption()
        
        # Token refresh tests
        await self._test_token_refresh()
        
        # API client creation tests
        await self._test_api_client_creation()
        
        # Authentication endpoint tests
        await self._test_authentication_endpoints()
        
        # Token expiration tests
        await self._test_token_expiration_scenarios()
        
        # Rate limiting tests
        await self._test_rate_limiting_resilience()
        
        # Network resilience tests
        await self._test_network_resilience()
        
        # Generate final report
        return self._generate_report()
    
    async def _test_environment_variables(self):
        """Test 1: Environment Variable Validation"""
        logger.info("🔍 Test 1: Environment Variable Validation")
        
        # Microsoft Graph variables
        ms_vars = ['MS_CLIENT_ID', 'MS_CLIENT_SECRET', 'MS_ENCRYPTED_REFRESH_TOKEN', 'MS_ENCRYPTION_KEY']
        # BuildingConnected variables
        bc_vars = ['AUTODESK_CLIENT_ID', 'AUTODESK_CLIENT_SECRET', 'AUTODESK_ENCRYPTED_REFRESH_TOKEN', 'AUTODESK_ENCRYPTION_KEY']
        
        start_time = datetime.now()
        
        missing_ms = [var for var in ms_vars if not os.getenv(var)]
        missing_bc = [var for var in bc_vars if not os.getenv(var)]
        
        all_present = len(missing_ms) == 0 and len(missing_bc) == 0
        
        details = {
            "microsoft_variables": {var: "✅ Present" if os.getenv(var) else "❌ Missing" for var in ms_vars},
            "buildingconnected_variables": {var: "✅ Present" if os.getenv(var) else "❌ Missing" for var in bc_vars},
            "missing_microsoft": missing_ms,
            "missing_buildingconnected": missing_bc
        }
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        if all_present:
            message = "✅ All required environment variables are present"
            self.test_results.append(TestResult("env_variables", True, message, execution_time, details))
        else:
            message = f"❌ Missing environment variables: MS={missing_ms}, BC={missing_bc}"
            self.critical_failures.append(message)
            self.test_results.append(TestResult("env_variables", False, message, execution_time, details))
        
        logger.info(f"   {message}")
    
    async def _test_token_manager_creation(self):
        """Test 2: Token Manager Creation"""
        logger.info("🔍 Test 2: Token Manager Creation")
        
        start_time = datetime.now()
        
        # Test Microsoft Graph token manager (or use existing)
        ms_success = False
        ms_error = None
        try:
            if not self.ms_token_manager:
                self.ms_token_manager = create_token_manager_from_env()
            ms_success = True
            logger.info("   ✅ Microsoft Graph token manager created successfully")
        except Exception as e:
            ms_error = str(e)
            self.critical_failures.append(f"Failed to create MS Graph token manager: {ms_error}")
            logger.error(f"   ❌ Microsoft Graph token manager creation failed: {ms_error}")
        
        # Test BuildingConnected token manager (or use existing)
        bc_success = False
        bc_error = None
        try:
            if not self.bc_token_manager:
                self.bc_token_manager = create_buildingconnected_token_manager_from_env()
            bc_success = True
            logger.info("   ✅ BuildingConnected token manager created successfully")
        except Exception as e:
            bc_error = str(e)
            self.critical_failures.append(f"Failed to create BuildingConnected token manager: {bc_error}")
            logger.error(f"   ❌ BuildingConnected token manager creation failed: {bc_error}")
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        overall_success = ms_success and bc_success
        
        details = {
            "microsoft_success": ms_success,
            "microsoft_error": ms_error,
            "buildingconnected_success": bc_success,
            "buildingconnected_error": bc_error
        }
        
        message = "✅ Both token managers created successfully" if overall_success else "❌ Token manager creation failed"
        self.test_results.append(TestResult("token_manager_creation", overall_success, message, execution_time, details))
    
    async def _test_token_decryption(self):
        """Test 3: Token Decryption"""
        logger.info("🔍 Test 3: Token Decryption")
        
        start_time = datetime.now()
        
        # Test Microsoft Graph token decryption
        ms_decrypt_success = False
        ms_decrypt_error = None
        try:
            ms_token_manager = self.ms_token_manager or create_token_manager_from_env()
            decrypted_ms_token = await ms_token_manager.decrypt_refresh_token()
            if decrypted_ms_token and len(decrypted_ms_token) > 10:  # Basic validation
                ms_decrypt_success = True
                logger.info("   ✅ Microsoft Graph refresh token decrypted successfully")
            else:
                ms_decrypt_error = "Decrypted token is empty or too short"
                logger.error(f"   ❌ Microsoft Graph token decryption issue: {ms_decrypt_error}")
        except Exception as e:
            ms_decrypt_error = str(e)
            self.critical_failures.append(f"MS Graph token decryption failed: {ms_decrypt_error}")
            logger.error(f"   ❌ Microsoft Graph token decryption failed: {ms_decrypt_error}")
        
        # Test BuildingConnected token decryption
        bc_decrypt_success = False
        bc_decrypt_error = None
        try:
            # Use persistent token manager if available, otherwise create new one
            bc_token_manager = self.bc_token_manager or create_buildingconnected_token_manager_from_env()
            decrypted_bc_token = await bc_token_manager.decrypt_refresh_token()
            if decrypted_bc_token and len(decrypted_bc_token) > 10:  # Basic validation
                bc_decrypt_success = True
                logger.info("   ✅ BuildingConnected refresh token decrypted successfully")
            else:
                bc_decrypt_error = "Decrypted token is empty or too short"
                logger.error(f"   ❌ BuildingConnected token decryption issue: {bc_decrypt_error}")
        except Exception as e:
            bc_decrypt_error = str(e)
            self.critical_failures.append(f"BuildingConnected token decryption failed: {bc_decrypt_error}")
            logger.error(f"   ❌ BuildingConnected token decryption failed: {bc_decrypt_error}")
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        overall_success = ms_decrypt_success and bc_decrypt_success
        
        details = {
            "microsoft_decrypt_success": ms_decrypt_success,
            "microsoft_decrypt_error": ms_decrypt_error,
            "buildingconnected_decrypt_success": bc_decrypt_success,
            "buildingconnected_decrypt_error": bc_decrypt_error
        }
        
        message = "✅ Both refresh tokens decrypted successfully" if overall_success else "❌ Token decryption failed"
        self.test_results.append(TestResult("token_decryption", overall_success, message, execution_time, details))
    
    async def _test_token_refresh(self):
        """Test 4: Token Refresh"""
        logger.info("🔍 Test 4: Token Refresh")
        
        start_time = datetime.now()
        
        # Test Microsoft Graph token refresh
        ms_refresh_success = False
        ms_refresh_error = None
        ms_token_info = {}
        try:
            # Use persistent token manager if available, otherwise create new one
            ms_token_manager = self.ms_token_manager or create_token_manager_from_env()
            access_token = await ms_token_manager.get_access_token()
            if access_token and len(access_token) > 50:  # Basic validation
                ms_refresh_success = True
                ms_token_info = {
                    "token_length": len(access_token),
                    "token_prefix": access_token[:20] + "...",
                    "expires_at": ms_token_manager._cached_token.expires_at if ms_token_manager._cached_token else None
                }
                logger.info("   ✅ Microsoft Graph access token refreshed successfully")
            else:
                ms_refresh_error = "Access token is empty or too short"
                logger.error(f"   ❌ Microsoft Graph token refresh issue: {ms_refresh_error}")
        except Exception as e:
            ms_refresh_error = str(e)
            self.critical_failures.append(f"MS Graph token refresh failed: {ms_refresh_error}")
            logger.error(f"   ❌ Microsoft Graph token refresh failed: {ms_refresh_error}")
        
        # Test BuildingConnected token refresh
        bc_refresh_success = False
        bc_refresh_error = None
        bc_token_info = {}
        try:
            # Use persistent token manager if available, otherwise create new one
            bc_token_manager = self.bc_token_manager or create_buildingconnected_token_manager_from_env()
            access_token = await bc_token_manager.get_access_token()
            if access_token and len(access_token) > 50:  # Basic validation
                bc_refresh_success = True
                bc_token_info = {
                    "token_length": len(access_token),
                    "token_prefix": access_token[:20] + "...",
                    "expires_at": bc_token_manager._cached_token.expires_at if bc_token_manager._cached_token else None
                }
                logger.info("   ✅ BuildingConnected access token refreshed successfully")
            else:
                bc_refresh_error = "Access token is empty or too short"
                logger.error(f"   ❌ BuildingConnected token refresh issue: {bc_refresh_error}")
        except Exception as e:
            bc_refresh_error = str(e)
            self.critical_failures.append(f"BuildingConnected token refresh failed: {bc_refresh_error}")
            logger.error(f"   ❌ BuildingConnected token refresh failed: {bc_refresh_error}")
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        overall_success = ms_refresh_success and bc_refresh_success
        
        details = {
            "microsoft_refresh_success": ms_refresh_success,
            "microsoft_refresh_error": ms_refresh_error,
            "microsoft_token_info": ms_token_info,
            "buildingconnected_refresh_success": bc_refresh_success,
            "buildingconnected_refresh_error": bc_refresh_error,
            "buildingconnected_token_info": bc_token_info
        }
        
        message = "✅ Both access tokens refreshed successfully" if overall_success else "❌ Token refresh failed"
        self.test_results.append(TestResult("token_refresh", overall_success, message, execution_time, details))
    
    async def _test_api_client_creation(self):
        """Test 5: API Client Creation"""
        logger.info("🔍 Test 5: API Client Creation")
        
        start_time = datetime.now()
        
        # Test Microsoft Graph client creation
        ms_client_success = False
        ms_client_error = None
        try:
            ms_token_manager = self.ms_token_manager or create_token_manager_from_env()
            ms_client = MSGraphClient(ms_token_manager)
            if ms_client and ms_client.base_url:
                ms_client_success = True
                logger.info("   ✅ Microsoft Graph client created successfully")
            else:
                ms_client_error = "Client creation returned invalid object"
                logger.error(f"   ❌ Microsoft Graph client creation issue: {ms_client_error}")
        except Exception as e:
            ms_client_error = str(e)
            self.critical_failures.append(f"MS Graph client creation failed: {ms_client_error}")
            logger.error(f"   ❌ Microsoft Graph client creation failed: {ms_client_error}")
        
        # Test BuildingConnected client creation
        bc_client_success = False
        bc_client_error = None
        try:
            bc_token_manager = self.bc_token_manager or create_buildingconnected_token_manager_from_env()
            bc_client = BuildingConnectedClient(bc_token_manager)
            if bc_client and bc_client.base_url:
                bc_client_success = True
                logger.info("   ✅ BuildingConnected client created successfully")
            else:
                bc_client_error = "Client creation returned invalid object"
                logger.error(f"   ❌ BuildingConnected client creation issue: {bc_client_error}")
        except Exception as e:
            bc_client_error = str(e)
            self.critical_failures.append(f"BuildingConnected client creation failed: {bc_client_error}")
            logger.error(f"   ❌ BuildingConnected client creation failed: {bc_client_error}")
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        overall_success = ms_client_success and bc_client_success
        
        details = {
            "microsoft_client_success": ms_client_success,
            "microsoft_client_error": ms_client_error,
            "buildingconnected_client_success": bc_client_success,
            "buildingconnected_client_error": bc_client_error
        }
        
        message = "✅ Both API clients created successfully" if overall_success else "❌ API client creation failed"
        self.test_results.append(TestResult("api_client_creation", overall_success, message, execution_time, details))
    
    async def _test_authentication_endpoints(self):
        """Test 6: Authentication Endpoint Validation"""
        logger.info("🔍 Test 6: Authentication Endpoint Validation")
        
        start_time = datetime.now()
        
        # Test Microsoft Graph API call
        ms_api_success = False
        ms_api_error = None
        ms_api_details = {}
        try:
            # Use persistent token manager if available, otherwise create new one
            ms_token_manager = self.ms_token_manager or create_token_manager_from_env()
            ms_client = MSGraphClient(ms_token_manager)
            
            # Try a simple API call (list recent emails with limit 1)
            result = await ms_client.list_emails(count=1)
            if result and isinstance(result, dict):
                ms_api_success = True
                ms_api_details = {
                    "response_keys": list(result.keys()),
                    "has_value": len(result.get('value', [])) >= 0  # Could be 0 emails, that's ok
                }
                logger.info("   ✅ Microsoft Graph API call successful")
            else:
                ms_api_error = "API call returned invalid response"
                logger.error(f"   ❌ Microsoft Graph API issue: {ms_api_error}")
        except Exception as e:
            ms_api_error = str(e)
            if "401" in ms_api_error or "unauthorized" in ms_api_error.lower():
                self.critical_failures.append(f"MS Graph authentication invalid: {ms_api_error}")
            else:
                self.warnings.append(f"MS Graph API call failed (may be transient): {ms_api_error}")
            logger.error(f"   ❌ Microsoft Graph API call failed: {ms_api_error}")
        
        # Test BuildingConnected API call
        bc_api_success = False
        bc_api_error = None
        bc_api_details = {}
        try:
            # Use persistent token manager if available, otherwise create new one
            bc_token_manager = self.bc_token_manager or create_buildingconnected_token_manager_from_env()
            bc_client = BuildingConnectedClient(bc_token_manager)
            
            # Try a simple API call (get projects - more reliable than user info)
            projects = await bc_client.get_all_projects(limit=1)
            if projects is not None:  # Even 0 projects is a successful API call
                bc_api_success = True
                bc_api_details = {
                    "projects_found": len(projects),
                    "api_responsive": True,
                    "sample_project": projects[0].name if projects else "No projects available"
                }
                logger.info(f"   ✅ BuildingConnected API call successful ({len(projects)} projects found)")
            else:
                bc_api_error = "API call returned None"
                logger.error(f"   ❌ BuildingConnected API issue: {bc_api_error}")
        except Exception as e:
            bc_api_error = str(e)
            if "401" in bc_api_error or "unauthorized" in bc_api_error.lower():
                self.critical_failures.append(f"BuildingConnected authentication invalid: {bc_api_error}")
            else:
                self.warnings.append(f"BuildingConnected API call failed (may be transient): {bc_api_error}")
            logger.error(f"   ❌ BuildingConnected API call failed: {bc_api_error}")
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        overall_success = ms_api_success and bc_api_success
        
        details = {
            "microsoft_api_success": ms_api_success,
            "microsoft_api_error": ms_api_error,
            "microsoft_api_details": ms_api_details,
            "buildingconnected_api_success": bc_api_success,
            "buildingconnected_api_error": bc_api_error,
            "buildingconnected_api_details": bc_api_details
        }
        
        message = "✅ Both API endpoints responding correctly" if overall_success else "❌ API endpoint validation failed"
        self.test_results.append(TestResult("authentication_endpoints", overall_success, message, execution_time, details))
    
    async def _test_token_expiration_scenarios(self):
        """Test 7: Token Expiration Scenarios"""
        logger.info("🔍 Test 7: Token Expiration Scenarios")
        
        start_time = datetime.now()
        
        # Check token expiration times
        ms_expiry_ok = False
        bc_expiry_ok = False
        expiry_details = {}
        
        try:
            # Check Microsoft Graph token expiry
            ms_token_manager = self.ms_token_manager or create_token_manager_from_env()
            await ms_token_manager.get_access_token()  # Ensure token is cached
            
            if ms_token_manager._cached_token:
                expires_at_ms = ms_token_manager._cached_token.expires_at
                current_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                time_until_expiry_minutes = (expires_at_ms - current_time_ms) / (1000 * 60)
                
                if time_until_expiry_minutes > 30:  # At least 30 minutes remaining
                    ms_expiry_ok = True
                    logger.info(f"   ✅ Microsoft Graph token expires in {time_until_expiry_minutes:.1f} minutes")
                else:
                    self.warnings.append(f"MS Graph token expires soon ({time_until_expiry_minutes:.1f} minutes)")
                    logger.warning(f"   ⚠️  Microsoft Graph token expires in {time_until_expiry_minutes:.1f} minutes")
                
                expiry_details["microsoft"] = {
                    "expires_at": expires_at_ms,
                    "minutes_until_expiry": time_until_expiry_minutes,
                    "expires_at_readable": datetime.fromtimestamp(expires_at_ms/1000, timezone.utc).isoformat()
                }
            else:
                self.warnings.append("MS Graph token not cached")
                logger.warning("   ⚠️  Microsoft Graph token not cached")
            
            # Check BuildingConnected token expiry
            bc_token_manager = self.bc_token_manager or create_buildingconnected_token_manager_from_env()
            await bc_token_manager.get_access_token()  # Ensure token is cached
            
            if bc_token_manager._cached_token:
                expires_at_ms = bc_token_manager._cached_token.expires_at
                current_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                time_until_expiry_minutes = (expires_at_ms - current_time_ms) / (1000 * 60)
                
                if time_until_expiry_minutes > 30:  # At least 30 minutes remaining
                    bc_expiry_ok = True
                    logger.info(f"   ✅ BuildingConnected token expires in {time_until_expiry_minutes:.1f} minutes")
                else:
                    self.warnings.append(f"BuildingConnected token expires soon ({time_until_expiry_minutes:.1f} minutes)")
                    logger.warning(f"   ⚠️  BuildingConnected token expires in {time_until_expiry_minutes:.1f} minutes")
                
                expiry_details["buildingconnected"] = {
                    "expires_at": expires_at_ms,
                    "minutes_until_expiry": time_until_expiry_minutes,
                    "expires_at_readable": datetime.fromtimestamp(expires_at_ms/1000, timezone.utc).isoformat()
                }
            else:
                self.warnings.append("BuildingConnected token not cached")
                logger.warning("   ⚠️  BuildingConnected token not cached")
                
        except Exception as e:
            error_msg = f"Token expiration check failed: {str(e)}"
            self.warnings.append(error_msg)
            logger.error(f"   ❌ {error_msg}")
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        overall_success = ms_expiry_ok and bc_expiry_ok
        
        message = "✅ Token expiration times are healthy" if overall_success else "⚠️ Token expiration concerns detected"
        self.test_results.append(TestResult("token_expiration", overall_success, message, execution_time, expiry_details))
    
    async def _test_rate_limiting_resilience(self):
        """Test 8: Rate Limiting Resilience"""
        logger.info("🔍 Test 8: Rate Limiting Resilience")
        
        start_time = datetime.now()
        
        # Test rapid API calls to check for rate limiting handling
        rate_limit_ok = True
        rate_limit_details = {}
        
        try:
            # Test Microsoft Graph rate limiting (make 3 quick calls)
            ms_token_manager = self.ms_token_manager or create_token_manager_from_env()
            ms_client = MSGraphClient(ms_token_manager)
            
            ms_call_times = []
            for i in range(3):
                call_start = datetime.now()
                try:
                    await ms_client.list_emails(count=1)
                    call_time = (datetime.now() - call_start).total_seconds() * 1000
                    ms_call_times.append(call_time)
                except Exception as e:
                    if "429" in str(e) or "rate" in str(e).lower():
                        self.warnings.append(f"MS Graph rate limiting detected: {str(e)}")
                        logger.warning(f"   ⚠️  Microsoft Graph rate limiting: {str(e)}")
                    else:
                        raise e
            
            rate_limit_details["microsoft"] = {
                "call_times_ms": ms_call_times,
                "avg_call_time_ms": sum(ms_call_times) / len(ms_call_times) if ms_call_times else 0
            }
            
            # Test BuildingConnected rate limiting (make 2 quick calls)
            bc_token_manager = self.bc_token_manager or create_buildingconnected_token_manager_from_env()
            bc_client = BuildingConnectedClient(bc_token_manager)
            
            bc_call_times = []
            for i in range(2):
                call_start = datetime.now()
                try:
                    await bc_client.get_all_projects(limit=1)
                    call_time = (datetime.now() - call_start).total_seconds() * 1000
                    bc_call_times.append(call_time)
                except Exception as e:
                    if "429" in str(e) or "rate" in str(e).lower():
                        self.warnings.append(f"BuildingConnected rate limiting detected: {str(e)}")
                        logger.warning(f"   ⚠️  BuildingConnected rate limiting: {str(e)}")
                    else:
                        raise e
            
            rate_limit_details["buildingconnected"] = {
                "call_times_ms": bc_call_times,
                "avg_call_time_ms": sum(bc_call_times) / len(bc_call_times) if bc_call_times else 0
            }
            
            logger.info("   ✅ Rate limiting tests completed successfully")
            
        except Exception as e:
            rate_limit_ok = False
            error_msg = f"Rate limiting test failed: {str(e)}"
            self.warnings.append(error_msg)
            logger.error(f"   ❌ {error_msg}")
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        message = "✅ Rate limiting resilience verified" if rate_limit_ok else "⚠️ Rate limiting issues detected"
        self.test_results.append(TestResult("rate_limiting", rate_limit_ok, message, execution_time, rate_limit_details))
    
    async def _test_network_resilience(self):
        """Test 9: Network Resilience"""
        logger.info("🔍 Test 9: Network Resilience")
        
        start_time = datetime.now()
        
        network_ok = True
        network_details = {}
        
        try:
            # Test basic connectivity to authentication endpoints
            endpoints_to_test = [
                ("Microsoft Token Endpoint", "https://login.microsoftonline.com/common/oauth2/v2.0/token"),
                ("Microsoft Graph API", "https://graph.microsoft.com/v1.0/"),
                ("Autodesk Token Endpoint", "https://developer.api.autodesk.com/authentication/v2/token"),
                ("BuildingConnected API", "https://developer.api.autodesk.com/construction/buildingconnected/v2/")
            ]
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                for endpoint_name, url in endpoints_to_test:
                    try:
                        response = await client.get(url)
                        network_details[endpoint_name] = {
                            "status_code": response.status_code,
                            "response_time_ms": response.elapsed.total_seconds() * 1000 if response.elapsed else 0,
                            "reachable": True
                        }
                        logger.info(f"   ✅ {endpoint_name}: {response.status_code} ({response.elapsed.total_seconds()*1000:.0f}ms)")
                    except Exception as e:
                        network_ok = False
                        network_details[endpoint_name] = {
                            "reachable": False,
                            "error": str(e)
                        }
                        self.critical_failures.append(f"Cannot reach {endpoint_name}: {str(e)}")
                        logger.error(f"   ❌ {endpoint_name}: {str(e)}")
            
        except Exception as e:
            network_ok = False
            error_msg = f"Network resilience test failed: {str(e)}"
            self.critical_failures.append(error_msg)
            logger.error(f"   ❌ {error_msg}")
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        message = "✅ Network connectivity verified" if network_ok else "❌ Network connectivity issues detected"
        self.test_results.append(TestResult("network_resilience", network_ok, message, execution_time, network_details))
    
    def _generate_report(self) -> HealthCheckReport:
        """Generate final health check report"""
        end_time = datetime.now()
        total_execution_time = int((end_time - self.start_time).total_seconds() * 1000)
        
        passed_tests = sum(1 for result in self.test_results if result.passed)
        failed_tests = len(self.test_results) - passed_tests
        
        # Determine overall status
        if len(self.critical_failures) > 0:
            overall_status = "FAIL"
        elif len(self.warnings) > 0:
            overall_status = "WARNING"
        else:
            overall_status = "PASS"
        
        return HealthCheckReport(
            timestamp=self.start_time.isoformat(),
            overall_status=overall_status,
            total_tests=len(self.test_results),
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            execution_time_ms=total_execution_time,
            test_results=self.test_results,
            critical_failures=self.critical_failures,
            warnings=self.warnings
        )


async def run_auth_health_check() -> HealthCheckReport:
    """Main function to run authentication health check"""
    checker = AuthHealthChecker()
    return await checker.run_all_tests()


def print_health_report(report: HealthCheckReport):
    """Print formatted health check report"""
    print("\n" + "="*80)
    print("🏥 AUTHENTICATION HEALTH CHECK REPORT")
    print("="*80)
    print(f"Timestamp: {report.timestamp}")
    print(f"Overall Status: {report.overall_status}")
    print(f"Execution Time: {report.execution_time_ms}ms")
    print(f"Tests: {report.passed_tests}/{report.total_tests} passed")
    
    if report.critical_failures:
        print(f"\n🚨 CRITICAL FAILURES ({len(report.critical_failures)}):")
        for failure in report.critical_failures:
            print(f"  - {failure}")
    
    if report.warnings:
        print(f"\n⚠️  WARNINGS ({len(report.warnings)}):")
        for warning in report.warnings:
            print(f"  - {warning}")
    
    print(f"\n📋 TEST RESULTS:")
    for result in report.test_results:
        status = "✅ PASS" if result.passed else "❌ FAIL"
        print(f"  {status} | {result.test_name:<25} | {result.execution_time_ms:>4}ms | {result.message}")
    
    print("="*80)
    
    # Save detailed report to JSON
    try:
        report_dict = {
            "timestamp": report.timestamp,
            "overall_status": report.overall_status,
            "total_tests": report.total_tests,
            "passed_tests": report.passed_tests,
            "failed_tests": report.failed_tests,
            "execution_time_ms": report.execution_time_ms,
            "critical_failures": report.critical_failures,
            "warnings": report.warnings,
            "test_results": [
                {
                    "test_name": r.test_name,
                    "passed": r.passed,
                    "message": r.message,
                    "execution_time_ms": r.execution_time_ms,
                    "details": r.details
                }
                for r in report.test_results
            ]
        }
        
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"logs/auth-health-report-{timestamp_str}.json"
        
        os.makedirs("logs", exist_ok=True)
        with open(report_file, 'w') as f:
            json.dump(report_dict, f, indent=2)
        
        print(f"📄 Detailed report saved to: {report_file}")
        
    except Exception as e:
        logger.error(f"Failed to save detailed report: {str(e)}")


if __name__ == "__main__":
    async def main():
        print("🚀 Starting Authentication Health Check Suite...")
        print("This comprehensive test suite validates all authentication components")
        print("Run this daily at 8am before the main bid reminder workflow\n")
        
        try:
            report = await run_auth_health_check()
            print_health_report(report)
            
            # Exit with appropriate code
            if report.overall_status == "FAIL":
                print("\n🚨 CRITICAL: Authentication health check FAILED!")
                print("   DO NOT run the main workflow until these issues are resolved.")
                exit(1)
            elif report.overall_status == "WARNING":
                print("\n⚠️  WARNING: Authentication health check completed with warnings.")
                print("   Main workflow can proceed, but monitor for issues.")
                exit(2)
            else:
                print("\n✅ SUCCESS: Authentication health check PASSED!")
                print("   All systems are healthy. Main workflow can proceed safely.")
                exit(0)
                
        except Exception as e:
            logger.error(f"Health check suite failed with exception: {str(e)}")
            print(f"\n💥 EXCEPTION: Health check suite crashed: {str(e)}")
            exit(3)
    
    asyncio.run(main())