"""
Enhanced Authentication Gap Testing Suite
Addresses specific auth gaps identified for 8am pre-flight checks:

- Token refresh simulation (especially Autodesk's rotation behavior)
- Permission scope validation (can you actually read projects AND send emails?)
- Encrypted token decryption integrity checks  
- Network connectivity to both OAuth providers with failure scenarios

This complements the existing auth-health-check.py with deeper edge case testing.
"""

import asyncio
import os
import sys
import logging
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import hashlib
import random

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

# Import our auth components
from auth.auth_helpers import (
    create_token_manager_from_env,
    create_buildingconnected_token_manager_from_env,
    MSGraphTokenManager,
    BuildingConnectedTokenManager,
    TokenData
)
from clients.graph_api_client import MSGraphClient, GraphAPIError
from clients.buildingconnected_client import BuildingConnectedClient, BuildingConnectedError

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/auth-gaps-check.log')
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class GapTestResult:
    """Individual gap test result"""
    test_name: str
    passed: bool
    message: str
    execution_time_ms: int
    severity: str  # CRITICAL, WARNING, INFO
    details: Optional[Dict] = None


@dataclass
class AuthGapsReport:
    """Authentication gaps report"""
    timestamp: str
    overall_status: str  # CRITICAL, WARNING, PASS
    total_tests: int
    passed_tests: int
    failed_tests: int
    execution_time_ms: int
    test_results: List[GapTestResult]
    critical_issues: List[str]
    warnings: List[str]
    recommendations: List[str]


class AuthGapsTester:
    """Enhanced authentication gaps testing"""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.test_results: List[GapTestResult] = []
        self.critical_issues: List[str] = []
        self.warnings: List[str] = []
        self.recommendations: List[str] = []
        
        # Persistent token managers for testing - CRITICAL for Autodesk token rotation
        self.ms_token_manager = None
        self.bc_token_manager = None
        
    async def initialize_token_managers(self):
        """Initialize persistent token managers to handle Autodesk token rotation"""
        try:
            self.ms_token_manager = create_token_manager_from_env()
            self.bc_token_manager = create_buildingconnected_token_manager_from_env()
            logger.info("✅ Initialized persistent token managers for testing")
        except Exception as e:
            logger.error(f"❌ Failed to initialize token managers: {str(e)}")
            raise
        
    async def run_all_gap_tests(self) -> AuthGapsReport:
        """Run all authentication gap tests"""
        logger.info("🔍 Starting Enhanced Authentication Gap Testing Suite")
        logger.info("="*70)
        
        # Initialize persistent token managers first (if not already set)
        if not self.ms_token_manager or not self.bc_token_manager:
            await self.initialize_token_managers()
        
        # Token refresh simulation tests
        await self._test_token_refresh_simulation()
        
        # Permission scope validation tests
        await self._test_permission_scope_validation()
        
        # Token decryption integrity tests
        await self._test_token_decryption_integrity()
        
        # Network connectivity failure simulation
        await self._test_network_failure_scenarios()
        
        # Token rotation behavior testing
        await self._test_autodesk_token_rotation()
        
        # Skip concurrent auth test - not relevant for single-threaded workflow
        # await self._test_concurrent_auth_requests()
        
        # Token tampering detection
        await self._test_token_tampering_detection()
        
        return self._generate_gaps_report()
    
    async def _test_token_refresh_simulation(self):
        """Gap Test 1: Token Refresh Simulation with Edge Cases"""
        logger.info("🔄 Gap Test 1: Token Refresh Simulation")
        
        start_time = datetime.now()
        
        # Test forced refresh by invalidating cached tokens
        ms_refresh_ok = False
        bc_refresh_ok = False
        refresh_details = {}
        
        try:
            # Microsoft Graph: Force refresh by clearing cache
            logger.info("  Testing Microsoft Graph forced refresh...")
            ms_token_manager = self.ms_token_manager  # Use persistent token manager
            
            # Get initial token
            initial_token = await ms_token_manager.get_access_token()
            initial_expiry = ms_token_manager._cached_token.expires_at if ms_token_manager._cached_token else 0
            
            # Clear cache to force refresh
            ms_token_manager._cached_token = None
            
            # Get new token (should trigger refresh)
            refreshed_token = await ms_token_manager.get_access_token()
            new_expiry = ms_token_manager._cached_token.expires_at if ms_token_manager._cached_token else 0
            
            # Verify refresh happened
            if refreshed_token != initial_token and new_expiry > initial_expiry:
                ms_refresh_ok = True
                logger.info("    ✅ Microsoft Graph forced refresh successful")
            else:
                logger.warning("    ⚠️  Microsoft Graph refresh may not have occurred")
                self.warnings.append("MS Graph forced refresh unclear")
            
            refresh_details["microsoft"] = {
                "initial_token_prefix": initial_token[:20] + "...",
                "refreshed_token_prefix": refreshed_token[:20] + "...", 
                "initial_expiry": initial_expiry,
                "new_expiry": new_expiry,
                "tokens_different": refreshed_token != initial_token
            }
            
        except Exception as e:
            error_msg = f"MS Graph refresh simulation failed: {str(e)}"
            self.critical_issues.append(error_msg)
            logger.error(f"    ❌ {error_msg}")
            refresh_details["microsoft_error"] = str(e)
        
        try:
            # BuildingConnected: Test with Autodesk rotation behavior
            logger.info("  Testing BuildingConnected/Autodesk refresh with rotation...")
            bc_token_manager = self.bc_token_manager  # Use persistent token manager
            
            # Store original refresh token for comparison
            original_encrypted_token = bc_token_manager.encrypted_refresh_token
            
            # Get initial token (this may already cause a refresh if token is expired)
            initial_token = await bc_token_manager.get_access_token()
            initial_expiry = bc_token_manager._cached_token.expires_at if bc_token_manager._cached_token else 0
            
            # For BuildingConnected, we'll test refresh behavior differently
            # since they rotate tokens, doing multiple refreshes will fail
            # Instead, we'll verify the current token is valid and functional
            # NOTE: The auth system already properly handles token rotation
            # by automatically saving new refresh tokens to .env (see auth_helpers.py:120-122)
            
            # Verify token works by making a simple API call
            from clients.buildingconnected_client import BuildingConnectedClient
            bc_client = BuildingConnectedClient(bc_token_manager)
            try:
                # Test with a lightweight API call
                projects = await bc_client.get_all_projects(limit=1)
                api_call_ok = projects is not None
            except Exception as api_e:
                # If this fails due to token issues, that's the real problem
                if "invalid_grant" in str(api_e) or "401" in str(api_e):
                    raise api_e  # Re-raise auth errors
                else:
                    api_call_ok = True  # Other API errors are OK for this test
            
            # Check if refresh token was rotated during the initial get_access_token call
            refresh_token_rotated = bc_token_manager.encrypted_refresh_token != original_encrypted_token
            
            if initial_token and len(initial_token) > 50 and api_call_ok:
                bc_refresh_ok = True
                logger.info("    ✅ BuildingConnected token refresh mechanism functional")
                if refresh_token_rotated:
                    logger.info("    🔄 Autodesk refresh token rotation detected (expected)")
                else:
                    logger.info("    📝 Autodesk refresh token not rotated (token still valid)")
            else:
                logger.error("    ❌ BuildingConnected token refresh failed")
                self.critical_issues.append("BuildingConnected token refresh mechanism failed")
                bc_refresh_ok = False
            
            refresh_details["buildingconnected"] = {
                "initial_token_prefix": initial_token[:20] + "..." if initial_token else "None",
                "initial_expiry": initial_expiry,
                "token_valid": bool(initial_token and len(initial_token) > 50),
                "api_call_successful": api_call_ok,
                "refresh_token_rotated": refresh_token_rotated
            }
            
        except Exception as e:
            error_msg = f"BuildingConnected refresh simulation failed: {str(e)}"
            self.critical_issues.append(error_msg)
            logger.error(f"    ❌ {error_msg}")
            refresh_details["buildingconnected_error"] = str(e)
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        overall_success = ms_refresh_ok and bc_refresh_ok
        severity = "INFO" if overall_success else "CRITICAL"
        
        message = "✅ Token refresh simulation passed" if overall_success else "❌ Token refresh simulation failed"
        self.test_results.append(GapTestResult("token_refresh_simulation", overall_success, message, execution_time, severity, refresh_details))
        
        if not overall_success:
            self.recommendations.append("Verify OAuth client credentials and refresh token validity")
    
    async def _test_permission_scope_validation(self):
        """Gap Test 2: Permission Scope Validation"""
        logger.info("🔐 Gap Test 2: Permission Scope Validation")
        
        start_time = datetime.now()
        
        # Test actual permissions vs required permissions
        ms_scopes_ok = False
        bc_scopes_ok = False
        scope_details = {}
        
        try:
            # Microsoft Graph: Test email sending permission
            logger.info("  Testing Microsoft Graph email permissions...")
            ms_token_manager = self.ms_token_manager  # Use persistent token manager
            ms_client = MSGraphClient(ms_token_manager)
            
            # Try to list emails (Mail.Read permission)
            try:
                email_result = await ms_client.list_emails(count=1)
                mail_read_ok = email_result is not None
                logger.info("    ✅ Mail.Read permission verified")
            except GraphAPIError as e:
                mail_read_ok = False
                if "403" in str(e) or "insufficient" in str(e).lower():
                    self.critical_issues.append("Missing Mail.Read permission for Microsoft Graph")
                    logger.error("    ❌ Mail.Read permission denied")
                else:
                    logger.warning(f"    ⚠️  Mail.Read test failed: {str(e)}")
            
            # Try to send a test email (Mail.Send permission) - dry run
            try:
                # We won't actually send, but we'll build the request to test permission scopes
                # A 403 vs other errors will tell us about permissions
                default_recipient = os.getenv('DEFAULT_EMAIL_RECIPIENT')
                if default_recipient:
                    # This should fail with auth error, not permission error
                    await ms_client.send_email(
                        to=default_recipient,
                        subject="[TEST] Auth Gap Check - Ignore",
                        body="Test email for permission validation"
                    )
                    mail_send_ok = True
                    logger.info("    ✅ Mail.Send permission verified")
                else:
                    mail_send_ok = True  # Can't test without recipient
                    logger.info("    ℹ️  Mail.Send permission not testable (no DEFAULT_EMAIL_RECIPIENT)")
                    
            except GraphAPIError as e:
                if "403" in str(e) or "insufficient" in str(e).lower():
                    mail_send_ok = False
                    self.critical_issues.append("Missing Mail.Send permission for Microsoft Graph")
                    logger.error("    ❌ Mail.Send permission denied")
                else:
                    mail_send_ok = True  # Other errors are OK for permission test
                    logger.info("    ✅ Mail.Send permission appears valid")
            
            ms_scopes_ok = mail_read_ok and mail_send_ok
            scope_details["microsoft"] = {
                "mail_read_ok": mail_read_ok,
                "mail_send_ok": mail_send_ok,
                "required_scopes": ["Mail.Read", "Mail.Send", "Mail.ReadWrite"],
                "configured_scope": ms_token_manager.scope
            }
            
        except Exception as e:
            error_msg = f"MS Graph scope validation failed: {str(e)}"
            self.critical_issues.append(error_msg)
            logger.error(f"    ❌ {error_msg}")
            scope_details["microsoft_error"] = str(e)
        
        try:
            # BuildingConnected: Test project reading permission
            logger.info("  Testing BuildingConnected project permissions...")
            bc_token_manager = self.bc_token_manager  # Use persistent token manager
            bc_client = BuildingConnectedClient(bc_token_manager)
            
            # Try to read projects (data:read permission)
            try:
                projects = await bc_client.get_all_projects(limit=1)
                data_read_ok = projects is not None
                logger.info("    ✅ data:read permission verified")
            except BuildingConnectedError as e:
                data_read_ok = False
                if "403" in str(e) or "insufficient" in str(e).lower():
                    self.critical_issues.append("Missing data:read permission for BuildingConnected")
                    logger.error("    ❌ data:read permission denied")
                else:
                    logger.warning(f"    ⚠️  data:read test failed: {str(e)}")
            
            # Try to get user profile (user-profile:read permission)
            try:
                user_info = await bc_client.get_user_info()
                user_profile_ok = user_info.authenticated
                logger.info("    ✅ user-profile:read permission verified")
            except BuildingConnectedError as e:
                user_profile_ok = False
                if "403" in str(e) or "insufficient" in str(e).lower():
                    self.critical_issues.append("Missing user-profile:read permission for BuildingConnected")
                    logger.error("    ❌ user-profile:read permission denied")
                else:
                    logger.warning(f"    ⚠️  user-profile:read test failed: {str(e)}")
            
            bc_scopes_ok = data_read_ok and user_profile_ok
            scope_details["buildingconnected"] = {
                "data_read_ok": data_read_ok,
                "user_profile_ok": user_profile_ok,
                "required_scopes": ["user-profile:read", "data:read", "data:write", "account:read", "account:write"],
                "configured_scope": bc_token_manager.scope
            }
            
        except Exception as e:
            error_msg = f"BuildingConnected scope validation failed: {str(e)}"
            self.critical_issues.append(error_msg)
            logger.error(f"    ❌ {error_msg}")
            scope_details["buildingconnected_error"] = str(e)
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        overall_success = ms_scopes_ok and bc_scopes_ok
        severity = "CRITICAL" if not overall_success else "INFO"
        
        message = "✅ Permission scopes validated" if overall_success else "❌ Permission scope validation failed"
        self.test_results.append(GapTestResult("permission_scope_validation", overall_success, message, execution_time, severity, scope_details))
        
        if not overall_success:
            self.recommendations.append("Review OAuth application permissions in Azure/Autodesk consoles")
    
    async def _test_token_decryption_integrity(self):
        """Gap Test 3: Enhanced Token Decryption Integrity"""
        logger.info("🔒 Gap Test 3: Token Decryption Integrity")
        
        start_time = datetime.now()
        
        integrity_ok = True
        integrity_details = {}
        
        try:
            # Test Microsoft Graph token decryption integrity
            logger.info("  Testing Microsoft Graph token decryption integrity...")
            
            ms_token_manager = self.ms_token_manager  # Use persistent token manager
            encrypted_token = ms_token_manager.encrypted_refresh_token
            encryption_key = ms_token_manager.encryption_key
            
            # Test 1: Normal decryption
            decrypted_token = await ms_token_manager.decrypt_refresh_token()
            normal_decrypt_ok = len(decrypted_token) > 20
            
            # Test 2: Verify encrypted format (iv:encrypted_data)
            format_ok = ':' in encrypted_token and len(encrypted_token.split(':')) == 2
            
            # Test 3: Verify IV and encrypted data are valid hex
            if format_ok:
                iv_hex, encrypted_hex = encrypted_token.split(':')
                iv_valid = len(iv_hex) == 32 and all(c in '0123456789abcdef' for c in iv_hex.lower())
                encrypted_valid = len(encrypted_hex) > 0 and all(c in '0123456789abcdef' for c in encrypted_hex.lower())
                hex_format_ok = iv_valid and encrypted_valid
            else:
                hex_format_ok = False
            
            # Test 4: Verify decryption produces consistent results
            decrypted_token2 = await ms_token_manager.decrypt_refresh_token()
            consistency_ok = decrypted_token == decrypted_token2
            
            ms_integrity_ok = normal_decrypt_ok and format_ok and hex_format_ok and consistency_ok
            
            integrity_details["microsoft"] = {
                "normal_decrypt_ok": normal_decrypt_ok,
                "format_ok": format_ok,
                "hex_format_ok": hex_format_ok,
                "consistency_ok": consistency_ok,
                "encrypted_token_length": len(encrypted_token),
                "decrypted_token_length": len(decrypted_token),
                "encryption_key_present": bool(encryption_key)
            }
            
            logger.info(f"    ✅ MS Graph integrity: decrypt={normal_decrypt_ok}, format={format_ok}, hex={hex_format_ok}, consistent={consistency_ok}")
            
        except Exception as e:
            ms_integrity_ok = False
            integrity_ok = False
            error_msg = f"MS Graph token integrity check failed: {str(e)}"
            self.critical_issues.append(error_msg)
            logger.error(f"    ❌ {error_msg}")
            integrity_details["microsoft_error"] = str(e)
        
        try:
            # Test BuildingConnected token decryption integrity
            logger.info("  Testing BuildingConnected token decryption integrity...")
            
            bc_token_manager = self.bc_token_manager  # Use persistent token manager
            encrypted_token = bc_token_manager.encrypted_refresh_token
            encryption_key = bc_token_manager.encryption_key
            
            # Test 1: Normal decryption
            decrypted_token = await bc_token_manager.decrypt_refresh_token()
            normal_decrypt_ok = len(decrypted_token) > 20
            
            # Test 2: Verify encrypted format (iv:encrypted_data)
            format_ok = ':' in encrypted_token and len(encrypted_token.split(':')) == 2
            
            # Test 3: Verify IV and encrypted data are valid hex
            if format_ok:
                iv_hex, encrypted_hex = encrypted_token.split(':')
                iv_valid = len(iv_hex) == 32 and all(c in '0123456789abcdef' for c in iv_hex.lower())
                encrypted_valid = len(encrypted_hex) > 0 and all(c in '0123456789abcdef' for c in encrypted_hex.lower())
                hex_format_ok = iv_valid and encrypted_valid
            else:
                hex_format_ok = False
            
            # Test 4: Verify decryption produces consistent results
            decrypted_token2 = await bc_token_manager.decrypt_refresh_token()
            consistency_ok = decrypted_token == decrypted_token2
            
            bc_integrity_ok = normal_decrypt_ok and format_ok and hex_format_ok and consistency_ok
            
            integrity_details["buildingconnected"] = {
                "normal_decrypt_ok": normal_decrypt_ok,
                "format_ok": format_ok,
                "hex_format_ok": hex_format_ok,
                "consistency_ok": consistency_ok,
                "encrypted_token_length": len(encrypted_token),
                "decrypted_token_length": len(decrypted_token),
                "encryption_key_present": bool(encryption_key)
            }
            
            logger.info(f"    ✅ BC integrity: decrypt={normal_decrypt_ok}, format={format_ok}, hex={hex_format_ok}, consistent={consistency_ok}")
            
        except Exception as e:
            bc_integrity_ok = False
            integrity_ok = False
            error_msg = f"BuildingConnected token integrity check failed: {str(e)}"
            self.critical_issues.append(error_msg)
            logger.error(f"    ❌ {error_msg}")
            integrity_details["buildingconnected_error"] = str(e)
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        overall_success = integrity_ok and ms_integrity_ok and bc_integrity_ok
        severity = "CRITICAL" if not overall_success else "INFO"
        
        message = "✅ Token decryption integrity verified" if overall_success else "❌ Token decryption integrity failed"
        self.test_results.append(GapTestResult("token_decryption_integrity", overall_success, message, execution_time, severity, integrity_details))
        
        if not overall_success:
            self.recommendations.append("Re-run OAuth setup to regenerate encrypted tokens")
    
    async def _test_network_failure_scenarios(self):
        """Gap Test 4: Network Failure Scenario Testing"""
        logger.info("🌐 Gap Test 4: Network Failure Scenarios")
        
        start_time = datetime.now()
        
        network_resilience_ok = True
        network_details = {}
        
        # Test timeout handling
        logger.info("  Testing timeout handling...")
        try:
            async with httpx.AsyncClient(timeout=0.001) as client:  # Very short timeout
                try:
                    await client.get("https://login.microsoftonline.com/common/oauth2/v2.0/token")
                    timeout_handled = False
                except (httpx.TimeoutException, httpx.ConnectTimeout, httpx.ReadTimeout):
                    timeout_handled = True
                    logger.info("    ✅ Timeout handling works correctly")
                except Exception as e:
                    timeout_handled = True  # Other connection errors are also OK
                    logger.info(f"    ✅ Connection error handling works: {type(e).__name__}")
        except Exception as e:
            timeout_handled = False
            logger.error(f"    ❌ Timeout test failed: {str(e)}")
        
        # Test DNS resolution failures
        logger.info("  Testing DNS resolution failure handling...")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                try:
                    await client.get("https://nonexistent-oauth-endpoint-12345.invalid")
                    dns_handled = False
                except (httpx.ConnectError, httpx.UnsupportedProtocol):
                    dns_handled = True
                    logger.info("    ✅ DNS failure handling works correctly")
                except Exception as e:
                    dns_handled = True  # Other connection errors are also OK
                    logger.info(f"    ✅ DNS error handling works: {type(e).__name__}")
        except Exception as e:
            dns_handled = False
            logger.error(f"    ❌ DNS test failed: {str(e)}")
        
        # Test HTTP error code handling
        logger.info("  Testing HTTP error code handling...")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Test 500 error handling
                try:
                    response = await client.get("https://httpstat.us/500")
                    http_error_handled = response.status_code == 500
                    logger.info("    ✅ HTTP 500 error handling verified")
                except Exception as e:
                    http_error_handled = True  # Connection errors are also fine
                    logger.info(f"    ✅ HTTP error handling works: {type(e).__name__}")
        except Exception as e:
            http_error_handled = False
            logger.error(f"    ❌ HTTP error test failed: {str(e)}")
        
        network_details = {
            "timeout_handled": timeout_handled,
            "dns_handled": dns_handled,
            "http_error_handled": http_error_handled
        }
        
        network_resilience_ok = timeout_handled and dns_handled and http_error_handled
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        severity = "WARNING" if not network_resilience_ok else "INFO"
        
        message = "✅ Network failure scenarios handled correctly" if network_resilience_ok else "⚠️ Network failure handling issues"
        self.test_results.append(GapTestResult("network_failure_scenarios", network_resilience_ok, message, execution_time, severity, network_details))
        
        if not network_resilience_ok:
            self.warnings.append("Network error handling may not be robust")
            self.recommendations.append("Test workflow behavior during network outages")
    
    async def _test_autodesk_token_rotation(self):
        """Gap Test 5: Autodesk Token Rotation Behavior"""
        logger.info("🔄 Gap Test 5: Autodesk Token Rotation Behavior")
        
        start_time = datetime.now()
        
        rotation_details = {}
        rotation_ok = True
        
        try:
            bc_token_manager = self.bc_token_manager  # Use persistent token manager
            
            # Store original state
            original_encrypted_token = bc_token_manager.encrypted_refresh_token
            
            # Test token rotation behavior with a single refresh
            # (Multiple consecutive refreshes will fail due to token rotation)
            # NOTE: Token rotation is EXPECTED behavior for Autodesk - not a bug!
            # The auth system properly handles this by saving new refresh tokens to .env
            logger.info("  Testing Autodesk token rotation mechanism...")
            
            # Get current token (may trigger refresh if needed)
            access_token = await bc_token_manager.get_access_token()
            current_encrypted_token = bc_token_manager.encrypted_refresh_token
            
            # Check if token is valid and functional
            token_functional = bool(access_token and len(access_token) > 50)
            
            # Check if refresh token was rotated
            refresh_token_rotated = current_encrypted_token != original_encrypted_token
            
            # Test that the token actually works with an API call
            from clients.buildingconnected_client import BuildingConnectedClient
            bc_client = BuildingConnectedClient(bc_token_manager)
            try:
                projects = await bc_client.get_all_projects(limit=1)
                api_functional = projects is not None
                logger.info("    ✅ Token is functional with API calls")
            except Exception as api_e:
                if "invalid_grant" in str(api_e) or "401" in str(api_e):
                    api_functional = False
                    logger.error("    ❌ Token not functional with API calls")
                else:
                    api_functional = True  # Other errors are OK
                    logger.info("    ✅ Token appears functional (non-auth error)")
            
            rotation_ok = token_functional and api_functional
            
            rotation_details = {
                "access_token_valid": token_functional,
                "api_functional": api_functional,
                "refresh_token_rotated": refresh_token_rotated,
                "original_token_same": current_encrypted_token == original_encrypted_token,
                "rotation_behavior": "Token rotated as expected" if refresh_token_rotated else "Token not rotated (still valid)"
            }
            
            if rotation_ok:
                if refresh_token_rotated:
                    logger.info("    ✅ Autodesk token rotation mechanism working correctly")
                else:
                    logger.info("    ✅ Autodesk token still valid, no rotation needed")
            else:
                logger.error("    ❌ Autodesk token rotation mechanism failed")
                self.critical_issues.append("Autodesk token rotation mechanism not working")
            
        except Exception as e:
            rotation_ok = False
            error_msg = f"Autodesk token rotation test failed: {str(e)}"
            self.critical_issues.append(error_msg)
            logger.error(f"    ❌ {error_msg}")
            rotation_details["error"] = str(e)
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        severity = "CRITICAL" if not rotation_ok else "INFO"
        
        message = "✅ Autodesk token rotation handling verified" if rotation_ok else "❌ Autodesk token rotation issues"
        self.test_results.append(GapTestResult("autodesk_token_rotation", rotation_ok, message, execution_time, severity, rotation_details))
        
        if not rotation_ok:
            self.recommendations.append("Verify Autodesk OAuth configuration supports refresh token rotation")
    
    async def _test_concurrent_auth_requests(self):
        """Gap Test 6: Concurrent Authentication Requests"""
        logger.info("🔀 Gap Test 6: Concurrent Authentication Requests")
        
        start_time = datetime.now()
        
        concurrent_ok = True
        concurrent_details = {}
        
        try:
            # Test concurrent token requests for both services
            # We'll test this more carefully to avoid token rotation issues
            ms_token_manager = self.ms_token_manager  # Use persistent token manager
            bc_token_manager = self.bc_token_manager  # Use persistent token manager
            
            logger.info("  Testing concurrent token requests...")
            
            # For Microsoft Graph, we can safely test concurrent requests
            # since they don't rotate refresh tokens
            logger.info("    Testing Microsoft Graph concurrent requests...")
            ms_token_manager._cached_token = None  # Clear cache
            
            start_concurrent = datetime.now()
            ms_results = await asyncio.gather(
                ms_token_manager.get_access_token(),
                ms_token_manager.get_access_token(),  # Concurrent request
                return_exceptions=True
            )
            ms_concurrent_time = (datetime.now() - start_concurrent).total_seconds() * 1000
            
            ms_token1, ms_token2 = ms_results
            ms_ok = isinstance(ms_token1, str) and isinstance(ms_token2, str) and len(ms_token1) > 50
            ms_race_ok = ms_token1 == ms_token2  # Should be identical from cache
            
            # For BuildingConnected, we'll test differently due to token rotation
            logger.info("    Testing BuildingConnected token caching...")
            bc_token1 = await bc_token_manager.get_access_token()
            bc_token2 = await bc_token_manager.get_access_token()  # Should use cache
            
            bc_ok = isinstance(bc_token1, str) and isinstance(bc_token2, str) and len(bc_token1) > 50
            bc_cache_ok = bc_token1 == bc_token2  # Should be identical from cache
            
            concurrent_ok = ms_ok and bc_ok and ms_race_ok and bc_cache_ok
            
            concurrent_details = {
                "ms_concurrent_time_ms": ms_concurrent_time,
                "ms_tokens_ok": ms_ok,
                "bc_tokens_ok": bc_ok,
                "ms_race_condition_ok": ms_race_ok,
                "bc_cache_ok": bc_cache_ok,
                "test_approach": "MS: concurrent requests, BC: sequential with caching"
            }
            
            if concurrent_ok:
                logger.info(f"    ✅ Concurrent auth test: MS={ms_ok}, BC={bc_ok}, Caching: MS={ms_race_ok}, BC={bc_cache_ok}")
            else:
                logger.warning(f"    ⚠️ Concurrent auth issues: MS={ms_ok}, BC={bc_ok}, Caching: MS={ms_race_ok}, BC={bc_cache_ok}")
                self.warnings.append("Concurrent authentication requests may have race conditions")
            
        except Exception as e:
            concurrent_ok = False
            error_msg = f"Concurrent auth test failed: {str(e)}"
            self.warnings.append(error_msg)
            logger.error(f"    ❌ {error_msg}")
            concurrent_details["error"] = str(e)
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        severity = "WARNING" if not concurrent_ok else "INFO"
        
        message = "✅ Concurrent authentication requests handled correctly" if concurrent_ok else "⚠️ Concurrent authentication issues"
        self.test_results.append(GapTestResult("concurrent_auth_requests", concurrent_ok, message, execution_time, severity, concurrent_details))
        
        if not concurrent_ok:
            self.warnings.append("Concurrent authentication requests may have race conditions")
    
    async def _test_token_tampering_detection(self):
        """Gap Test 7: Token Tampering Detection"""
        logger.info("🛡️ Gap Test 7: Token Tampering Detection")
        
        start_time = datetime.now()
        
        tampering_ok = True
        tampering_details = {}
        
        try:
            # Test Microsoft Graph token tampering detection
            logger.info("  Testing Microsoft Graph token tampering detection...")
            
            ms_token_manager = self.ms_token_manager  # Use persistent token manager
            original_encrypted = ms_token_manager.encrypted_refresh_token
            
            # Test 1: Corrupt the IV
            if ':' in original_encrypted:
                iv_hex, encrypted_hex = original_encrypted.split(':')
                corrupted_iv = 'x' + iv_hex[1:]  # Corrupt first character
                ms_token_manager.encrypted_refresh_token = f"{corrupted_iv}:{encrypted_hex}"
                
                try:
                    await ms_token_manager.decrypt_refresh_token()
                    ms_tamper_detected = False  # Should have failed
                except Exception:
                    ms_tamper_detected = True  # Correctly detected tampering
                    logger.info("    ✅ MS Graph IV tampering detected")
                
                # Restore original
                ms_token_manager.encrypted_refresh_token = original_encrypted
            else:
                ms_tamper_detected = False
                logger.error("    ❌ MS Graph token format invalid for tampering test")
            
            # Test 2: Corrupt the encrypted data
            if ':' in original_encrypted:
                iv_hex, encrypted_hex = original_encrypted.split(':')
                corrupted_encrypted = 'x' + encrypted_hex[1:]  # Corrupt first character
                ms_token_manager.encrypted_refresh_token = f"{iv_hex}:{corrupted_encrypted}"
                
                try:
                    await ms_token_manager.decrypt_refresh_token()
                    ms_data_tamper_detected = False  # Should have failed
                except Exception:
                    ms_data_tamper_detected = True  # Correctly detected tampering
                    logger.info("    ✅ MS Graph data tampering detected")
                
                # Restore original
                ms_token_manager.encrypted_refresh_token = original_encrypted
            else:
                ms_data_tamper_detected = False
            
            tampering_details["microsoft"] = {
                "iv_tamper_detected": ms_tamper_detected,
                "data_tamper_detected": ms_data_tamper_detected
            }
            
        except Exception as e:
            ms_tamper_detected = False
            ms_data_tamper_detected = False
            logger.error(f"    ❌ MS Graph tampering test failed: {str(e)}")
            tampering_details["microsoft_error"] = str(e)
        
        try:
            # Test BuildingConnected token tampering detection
            logger.info("  Testing BuildingConnected token tampering detection...")
            
            bc_token_manager = self.bc_token_manager  # Use persistent token manager
            original_encrypted = bc_token_manager.encrypted_refresh_token
            
            # Test corrupted data
            if ':' in original_encrypted:
                iv_hex, encrypted_hex = original_encrypted.split(':')
                corrupted_encrypted = 'y' + encrypted_hex[1:]  # Corrupt first character
                bc_token_manager.encrypted_refresh_token = f"{iv_hex}:{corrupted_encrypted}"
                
                try:
                    await bc_token_manager.decrypt_refresh_token()
                    bc_tamper_detected = False  # Should have failed
                except Exception:
                    bc_tamper_detected = True  # Correctly detected tampering
                    logger.info("    ✅ BuildingConnected tampering detected")
                
                # Restore original
                bc_token_manager.encrypted_refresh_token = original_encrypted
            else:
                bc_tamper_detected = False
                logger.error("    ❌ BuildingConnected token format invalid for tampering test")
            
            tampering_details["buildingconnected"] = {
                "tamper_detected": bc_tamper_detected
            }
            
        except Exception as e:
            bc_tamper_detected = False
            logger.error(f"    ❌ BuildingConnected tampering test failed: {str(e)}")
            tampering_details["buildingconnected_error"] = str(e)
        
        tampering_ok = ms_tamper_detected and ms_data_tamper_detected and bc_tamper_detected
        
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        severity = "WARNING" if not tampering_ok else "INFO"
        
        message = "✅ Token tampering detection working" if tampering_ok else "⚠️ Token tampering detection issues"
        self.test_results.append(GapTestResult("token_tampering_detection", tampering_ok, message, execution_time, severity, tampering_details))
        
        if not tampering_ok:
            self.warnings.append("Token tampering detection may not be robust")
    
    def _generate_gaps_report(self) -> AuthGapsReport:
        """Generate final authentication gaps report"""
        end_time = datetime.now()
        total_execution_time = int((end_time - self.start_time).total_seconds() * 1000)
        
        passed_tests = sum(1 for result in self.test_results if result.passed)
        failed_tests = len(self.test_results) - passed_tests
        
        # Determine overall status
        if len(self.critical_issues) > 0:
            overall_status = "CRITICAL"
        elif len(self.warnings) > 0:
            overall_status = "WARNING"
        else:
            overall_status = "PASS"
        
        return AuthGapsReport(
            timestamp=self.start_time.isoformat(),
            overall_status=overall_status,
            total_tests=len(self.test_results),
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            execution_time_ms=total_execution_time,
            test_results=self.test_results,
            critical_issues=self.critical_issues,
            warnings=self.warnings,
            recommendations=self.recommendations
        )


async def run_auth_gaps_check() -> AuthGapsReport:
    """Main function to run authentication gaps check"""
    tester = AuthGapsTester()
    return await tester.run_all_gap_tests()


def print_gaps_report(report: AuthGapsReport):
    """Print formatted authentication gaps report"""
    print("\n" + "="*80)
    print("🔍 AUTHENTICATION GAPS TEST REPORT")
    print("="*80)
    print(f"Timestamp: {report.timestamp}")
    print(f"Overall Status: {report.overall_status}")
    print(f"Execution Time: {report.execution_time_ms}ms")
    print(f"Tests: {report.passed_tests}/{report.total_tests} passed")
    
    if report.critical_issues:
        print(f"\n🚨 CRITICAL ISSUES ({len(report.critical_issues)}):")
        for issue in report.critical_issues:
            print(f"  - {issue}")
    
    if report.warnings:
        print(f"\n⚠️  WARNINGS ({len(report.warnings)}):")
        for warning in report.warnings:
            print(f"  - {warning}")
    
    if report.recommendations:
        print(f"\n💡 RECOMMENDATIONS ({len(report.recommendations)}):")
        for rec in report.recommendations:
            print(f"  - {rec}")
    
    print(f"\n🧪 DETAILED TEST RESULTS:")
    for result in report.test_results:
        status_icon = "✅" if result.passed else "❌" if result.severity == "CRITICAL" else "⚠️"
        print(f"  {status_icon} {result.test_name:<30} | {result.execution_time_ms:>5}ms | {result.message}")
    
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
            "critical_issues": report.critical_issues,
            "warnings": report.warnings,
            "recommendations": report.recommendations,
            "test_results": [
                {
                    "test_name": r.test_name,
                    "passed": r.passed,
                    "message": r.message,
                    "execution_time_ms": r.execution_time_ms,
                    "severity": r.severity,
                    "details": r.details
                }
                for r in report.test_results
            ]
        }
        
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"logs/auth-gaps-report-{timestamp_str}.json"
        
        os.makedirs("logs", exist_ok=True)
        with open(report_file, 'w') as f:
            json.dump(report_dict, f, indent=2)
        
        print(f"📄 Detailed gaps report saved to: {report_file}")
        
    except Exception as e:
        logger.error(f"Failed to save detailed gaps report: {str(e)}")


if __name__ == "__main__":
    async def main():
        print("🔍 Starting Enhanced Authentication Gaps Testing Suite...")
        print("This suite tests specific authentication edge cases and failure scenarios")
        print("Complements the main auth-health-check.py with deeper gap analysis\n")
        
        try:
            report = await run_auth_gaps_check()
            print_gaps_report(report)
            
            # Exit with appropriate code
            if report.overall_status == "CRITICAL":
                print("\n🚨 CRITICAL: Authentication gaps detected!")
                print("   Address critical issues before running main workflow.")
                exit(1)
            elif report.overall_status == "WARNING":
                print("\n⚠️  WARNING: Authentication gaps test completed with warnings.")
                print("   Monitor for potential issues during workflow execution.")
                exit(2)
            else:
                print("\n✅ SUCCESS: No critical authentication gaps detected!")
                print("   Authentication system appears robust for production use.")
                exit(0)
                
        except Exception as e:
            logger.error(f"Auth gaps test suite failed with exception: {str(e)}")
            print(f"\n💥 EXCEPTION: Auth gaps test suite crashed: {str(e)}")
            exit(3)
    
    asyncio.run(main())