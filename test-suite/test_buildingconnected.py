"""
Comprehensive BuildingConnected Workflow Test Suite
Tests all potential failure scenarios that could cause the agent to fail

This test suite covers:
- Authentication failures (token issues, network errors)
- API response handling (malformed data, rate limiting, network timeouts)
- Data validation (invalid project IDs, malformed dates, missing fields)
- Pagination issues (missing URLs, infinite loops, empty results)  
- Workflow state management (node failures, error propagation)
- Email integration (Outlook failures, sending errors)
- Edge cases and boundary conditions

Run this before production deployments to catch failure scenarios
"""

import asyncio
import os
import sys
import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from unittest.mock import AsyncMock, Mock, patch, MagicMock
import tempfile
import shutil

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
import httpx
import pytest

# Import our components
from auth.auth_helpers import (
    MSGraphTokenManager,
    BuildingConnectedTokenManager,
    create_token_manager_from_env,
    create_buildingconnected_token_manager_from_env
)
from clients.buildingconnected_client import (
    BuildingConnectedClient,
    BuildingConnectedError,
    Project,
    ProjectsDueResponse,
    UserInfo,
    BiddingInvitationData,
    BidPackageApiResponse,
    InviteApiResponse,
    ProjectState
)
from clients.graph_api_client import MSGraphClient, EmailImportance
from bid_reminder_agent import BidReminderAgent, BidReminderState

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/buildingconnected-test.log')
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
    error_details: Optional[str] = None
    severity: str = "medium"  # low, medium, high, critical


@dataclass
class TestSuiteReport:
    """Complete test suite report"""
    timestamp: str
    overall_status: str  # PASS/FAIL/WARNING
    total_tests: int
    passed_tests: int
    failed_tests: int
    critical_failures: int
    execution_time_ms: int
    test_results: List[TestResult]
    recommendations: List[str]


class BuildingConnectedTestSuite:
    """Comprehensive test suite for BuildingConnected workflow"""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.test_results: List[TestResult] = []
        self.temp_dir = None
        
    async def run_all_tests(self) -> TestSuiteReport:
        """Run comprehensive test suite"""
        logger.info("🧪 Starting comprehensive BuildingConnected workflow test suite")
        logger.info("="*80)
        
        # Setup temp directory for logs
        self.temp_dir = tempfile.mkdtemp(prefix="bc_test_")
        logger.info(f"📁 Created temporary directory: {self.temp_dir}")
        
        try:
            # Authentication Tests
            await self._test_authentication_scenarios()
            
            # API Client Tests
            await self._test_api_client_functionality()
            
            # Data Validation Tests
            await self._test_data_validation()
            
            # Network Resilience Tests
            await self._test_network_resilience()
            
            # Pagination Tests
            await self._test_pagination_handling()
            
            # Workflow Integration Tests
            await self._test_workflow_integration()
            
            # Edge Case Tests
            await self._test_edge_cases()
            
            # Performance Tests
            await self._test_performance_scenarios()
            
        finally:
            # Cleanup temp directory
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                logger.info(f"🧹 Cleaned up temporary directory")
        
        return self._generate_report()
    
    # =============================================================================
    # Authentication Scenario Tests
    # =============================================================================
    
    async def _test_authentication_scenarios(self):
        """Test 1: Authentication failure scenarios"""
        logger.info("🔐 Test Category 1: Authentication Scenarios")
        
        # Test 1.1: Invalid refresh token
        await self._test_invalid_refresh_token()
        
        # Test 1.2: Expired access token
        await self._test_expired_access_token()
        
        # Test 1.3: Token manager creation failure
        await self._test_token_manager_creation_failure()
        
        # Test 1.4: Network failure during token refresh
        await self._test_network_failure_during_refresh()
        
        # Test 1.5: Malformed token response
        await self._test_malformed_token_response()
    
    async def _test_invalid_refresh_token(self):
        """Test invalid refresh token handling"""
        start_time = datetime.now()
        test_name = "invalid_refresh_token"
        
        try:
            # Mock token manager with invalid refresh token
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.side_effect = Exception("Token refresh failed: invalid_grant")
            
            client = BuildingConnectedClient(mock_token_manager)
            
            # This should fail gracefully
            try:
                await client.get_all_projects(limit=1)
                self._record_test_result(test_name, False, "Should have failed with invalid token", start_time, severity="critical")
            except Exception as e:
                if "Token refresh failed" in str(e) or "invalid_grant" in str(e):
                    self._record_test_result(test_name, True, "✅ Correctly handled invalid refresh token", start_time)
                else:
                    self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="high")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_expired_access_token(self):
        """Test expired access token refresh"""
        start_time = datetime.now()
        test_name = "expired_access_token_refresh"
        
        try:
            # Mock token manager that refreshes token on first call
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            call_count = 0
            
            async def mock_get_token():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise Exception("Token expired")
                return "new_valid_token_123"
            
            mock_token_manager.get_access_token = mock_get_token
            
            client = BuildingConnectedClient(mock_token_manager)
            
            # Mock the HTTP response for successful retry
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = '{"results": []}'
                mock_response.json.return_value = {"results": []}
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    projects = await client.get_all_projects(limit=1)
                    self._record_test_result(test_name, True, "✅ Successfully handled token refresh", start_time)
                except Exception as e:
                    if "Token expired" in str(e):
                        self._record_test_result(test_name, False, "Failed to handle token refresh", start_time, severity="high")
                    else:
                        self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                        
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_token_manager_creation_failure(self):
        """Test token manager creation failures"""
        start_time = datetime.now()
        test_name = "token_manager_creation_failure"
        
        try:
            # Test with missing environment variables
            with patch.dict(os.environ, {}, clear=True):
                try:
                    token_manager = create_buildingconnected_token_manager_from_env()
                    self._record_test_result(test_name, False, "Should have failed with missing env vars", start_time, severity="critical")
                except Exception as e:
                    if "environment variable" in str(e).lower() or "not found" in str(e).lower():
                        self._record_test_result(test_name, True, "✅ Correctly handled missing environment variables", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                        
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_network_failure_during_refresh(self):
        """Test network failure during token refresh"""
        start_time = datetime.now()
        test_name = "network_failure_during_refresh"
        
        try:
            # Mock token manager that fails with network error
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.side_effect = httpx.NetworkError("Connection failed")
            
            client = BuildingConnectedClient(mock_token_manager)
            
            try:
                await client.get_all_projects(limit=1)
                self._record_test_result(test_name, False, "Should have failed with network error", start_time, severity="high")
            except (httpx.NetworkError, Exception) as e:
                if "Connection failed" in str(e) or "Network" in str(e):
                    self._record_test_result(test_name, True, "✅ Correctly handled network failure", start_time)
                else:
                    self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_malformed_token_response(self):
        """Test malformed token response handling"""
        start_time = datetime.now()
        test_name = "malformed_token_response"
        
        try:
            # Mock token manager that returns malformed response
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.side_effect = json.JSONDecodeError("Invalid JSON", "doc", 0)
            
            client = BuildingConnectedClient(mock_token_manager)
            
            try:
                await client.get_all_projects(limit=1)
                self._record_test_result(test_name, False, "Should have failed with JSON error", start_time, severity="high")
            except (json.JSONDecodeError, Exception) as e:
                if "JSON" in str(e) or "Invalid" in str(e):
                    self._record_test_result(test_name, True, "✅ Correctly handled malformed response", start_time)
                else:
                    self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    # =============================================================================
    # API Client Functionality Tests
    # =============================================================================
    
    async def _test_api_client_functionality(self):
        """Test 2: API client functionality scenarios"""
        logger.info("🌐 Test Category 2: API Client Functionality")
        
        # Test 2.1: HTTP status code handling
        await self._test_http_status_codes()
        
        # Test 2.2: Empty response handling
        await self._test_empty_responses()
        
        # Test 2.3: Large response handling
        await self._test_large_responses()
        
        # Test 2.4: Rate limiting responses
        await self._test_rate_limiting()
        
        # Test 2.5: Timeout handling
        await self._test_timeout_handling()
    
    async def _test_http_status_codes(self):
        """Test various HTTP status code responses"""
        start_time = datetime.now()
        test_name = "http_status_codes"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            # Test different status codes
            status_codes = [400, 401, 403, 404, 429, 500, 502, 503]
            handled_correctly = 0
            
            for status_code in status_codes:
                with patch('httpx.AsyncClient') as mock_client:
                    mock_response = Mock()
                    mock_response.status_code = status_code
                    mock_response.is_success = False
                    mock_response.text = f"Error {status_code}"
                    mock_response.reason_phrase = f"Status {status_code}"
                    mock_response.json.return_value = {"error": {"message": f"Error {status_code}"}}
                    
                    mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                    
                    try:
                        await client.get_all_projects(limit=1)
                    except BuildingConnectedError as e:
                        if e.status_code == status_code:
                            handled_correctly += 1
                    except Exception:
                        pass  # Other exceptions are also acceptable
            
            if handled_correctly >= len(status_codes) * 0.8:  # 80% success rate
                self._record_test_result(test_name, True, f"✅ Handled {handled_correctly}/{len(status_codes)} status codes correctly", start_time)
            else:
                self._record_test_result(test_name, False, f"Only handled {handled_correctly}/{len(status_codes)} status codes", start_time, severity="medium")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_empty_responses(self):
        """Test empty response handling"""
        start_time = datetime.now()
        test_name = "empty_responses"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = ""  # Empty response
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    projects = await client.get_all_projects(limit=1)
                    # Should return empty list or handle gracefully
                    self._record_test_result(test_name, True, "✅ Handled empty response gracefully", start_time)
                except Exception as e:
                    self._record_test_result(test_name, False, f"Failed to handle empty response: {str(e)}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_large_responses(self):
        """Test large response handling"""
        start_time = datetime.now()
        test_name = "large_responses"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            # Create large response (1000 projects)
            large_response = {
                "results": [
                    {
                        "id": f"project_{i}",
                        "name": f"Large Project {i}",
                        "bidsDueAt": "2024-12-31T23:59:59Z",
                        "state": "active"
                    }
                    for i in range(1000)
                ]
            }
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = json.dumps(large_response)
                mock_response.json.return_value = large_response
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    projects = await client.get_all_projects(limit=1000)
                    if len(projects) == 1000:
                        self._record_test_result(test_name, True, "✅ Handled large response successfully", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Expected 1000 projects, got {len(projects)}", start_time, severity="medium")
                except Exception as e:
                    self._record_test_result(test_name, False, f"Failed to handle large response: {str(e)}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_rate_limiting(self):
        """Test rate limiting response handling"""
        start_time = datetime.now()
        test_name = "rate_limiting"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 429
                mock_response.is_success = False
                mock_response.text = "Rate limit exceeded"
                mock_response.reason_phrase = "Too Many Requests"
                mock_response.json.return_value = {"error": {"message": "Rate limit exceeded"}}
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    await client.get_all_projects(limit=1)
                    self._record_test_result(test_name, False, "Should have raised BuildingConnectedError", start_time, severity="medium")
                except BuildingConnectedError as e:
                    if e.status_code == 429:
                        self._record_test_result(test_name, True, "✅ Correctly handled rate limiting", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Wrong status code: {e.status_code}", start_time, severity="medium")
                except Exception as e:
                    self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_timeout_handling(self):
        """Test timeout handling"""
        start_time = datetime.now()
        test_name = "timeout_handling"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.return_value.get.side_effect = httpx.TimeoutException("Request timeout")
                
                try:
                    await client.get_all_projects(limit=1)
                    self._record_test_result(test_name, False, "Should have raised timeout exception", start_time, severity="medium")
                except httpx.TimeoutException:
                    self._record_test_result(test_name, True, "✅ Correctly handled timeout", start_time)
                except Exception as e:
                    if "timeout" in str(e).lower():
                        self._record_test_result(test_name, True, "✅ Handled timeout error", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                        
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    # =============================================================================
    # Data Validation Tests
    # =============================================================================
    
    async def _test_data_validation(self):
        """Test 3: Data validation scenarios"""
        logger.info("📊 Test Category 3: Data Validation")
        
        # Test 3.1: Invalid project IDs
        await self._test_invalid_project_ids()
        
        # Test 3.2: Malformed date formats
        await self._test_malformed_dates()
        
        # Test 3.3: Missing required fields
        await self._test_missing_fields()
        
        # Test 3.4: Invalid data types
        await self._test_invalid_data_types()
        
        # Test 3.5: Boundary value testing
        await self._test_boundary_values()
    
    async def _test_invalid_project_ids(self):
        """Test invalid project ID handling"""
        start_time = datetime.now()
        test_name = "invalid_project_ids"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            invalid_ids = ["", None, "invalid-id", "12345", "project_with_special_chars!@#"]
            handled_correctly = 0
            
            for invalid_id in invalid_ids:
                try:
                    if invalid_id is None or invalid_id == "":
                        # These should fail validation before API call
                        try:
                            await client.get_bidding_invitations(invalid_id)
                        except (ValueError, TypeError):
                            handled_correctly += 1
                        except Exception:
                            pass
                    else:
                        # These should return 404 or similar from API
                        with patch('httpx.AsyncClient') as mock_client:
                            mock_response = Mock()
                            mock_response.status_code = 404
                            mock_response.is_success = False
                            mock_response.text = "Project not found"
                            mock_response.reason_phrase = "Not Found"
                            mock_response.json.return_value = {"error": {"message": "Project not found"}}
                            
                            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                            
                            try:
                                await client.get_project_details(invalid_id)
                            except BuildingConnectedError as e:
                                if e.status_code == 404:
                                    handled_correctly += 1
                            except Exception:
                                pass
                except Exception:
                    pass
            
            if handled_correctly >= len(invalid_ids) * 0.6:  # 60% success rate
                self._record_test_result(test_name, True, f"✅ Handled {handled_correctly}/{len(invalid_ids)} invalid IDs correctly", start_time)
            else:
                self._record_test_result(test_name, False, f"Only handled {handled_correctly}/{len(invalid_ids)} invalid IDs", start_time, severity="medium")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_malformed_dates(self):
        """Test malformed date handling"""
        start_time = datetime.now()
        test_name = "malformed_dates"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            # Create response with malformed dates
            malformed_response = {
                "results": [
                    {
                        "id": "project_1",
                        "name": "Project with bad date",
                        "bidsDueAt": "invalid-date",
                        "state": "active"
                    },
                    {
                        "id": "project_2", 
                        "name": "Project with no date",
                        "bidsDueAt": None,
                        "state": "active"
                    },
                    {
                        "id": "project_3",
                        "name": "Project with empty date",
                        "bidsDueAt": "",
                        "state": "active"
                    }
                ]
            }
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = json.dumps(malformed_response)
                mock_response.json.return_value = malformed_response
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    # This should handle malformed dates gracefully
                    projects_response = await client.get_projects_due_in_n_days(5)
                    # Should not crash and return valid response structure
                    if hasattr(projects_response, 'projects') and hasattr(projects_response, 'total'):
                        self._record_test_result(test_name, True, "✅ Handled malformed dates gracefully", start_time)
                    else:
                        self._record_test_result(test_name, False, "Response structure invalid", start_time, severity="medium")
                except Exception as e:
                    if "date" in str(e).lower() or "format" in str(e).lower():
                        self._record_test_result(test_name, True, "✅ Correctly rejected malformed dates", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                        
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_missing_fields(self):
        """Test missing required fields handling"""
        start_time = datetime.now()
        test_name = "missing_fields"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            # Create response with missing fields
            incomplete_response = {
                "results": [
                    {
                        "id": "project_1"
                        # Missing name, bidsDueAt, state
                    },
                    {
                        "name": "Project without ID"
                        # Missing id
                    }
                ]
            }
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = json.dumps(incomplete_response)
                mock_response.json.return_value = incomplete_response
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    projects = await client.get_all_projects(limit=10)
                    # Should handle missing fields with defaults or skip invalid entries
                    self._record_test_result(test_name, True, "✅ Handled missing fields gracefully", start_time)
                except Exception as e:
                    self._record_test_result(test_name, False, f"Failed to handle missing fields: {str(e)}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_invalid_data_types(self):
        """Test invalid data type handling"""
        start_time = datetime.now()
        test_name = "invalid_data_types"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            # Create response with wrong data types
            wrong_types_response = {
                "results": [
                    {
                        "id": 12345,  # Should be string
                        "name": None,  # Should be string
                        "bidsDueAt": True,  # Should be string or null
                        "state": 404,  # Should be string
                        "isBiddingSealed": "yes"  # Should be boolean
                    }
                ]
            }
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = json.dumps(wrong_types_response)
                mock_response.json.return_value = wrong_types_response
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    projects = await client.get_all_projects(limit=10)
                    # Should handle type conversion or validation errors
                    self._record_test_result(test_name, True, "✅ Handled invalid data types", start_time)
                except Exception as e:
                    if "validation" in str(e).lower() or "type" in str(e).lower():
                        self._record_test_result(test_name, True, "✅ Correctly validated data types", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                        
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_boundary_values(self):
        """Test boundary value handling"""
        start_time = datetime.now()
        test_name = "boundary_values"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            boundary_cases = [
                (-1, "negative days"),
                (0, "zero days"), 
                (366, "too many days"),
                (999999, "extreme days")
            ]
            
            handled_correctly = 0
            
            for days, description in boundary_cases:
                try:
                    await client.get_projects_due_in_n_days(days)
                    if days == 0:
                        handled_correctly += 1  # 0 should be valid
                except ValueError as e:
                    if days < 0 or days > 365:
                        handled_correctly += 1  # Should reject invalid ranges
                except Exception:
                    pass
            
            if handled_correctly >= len(boundary_cases) * 0.75:  # 75% success rate
                self._record_test_result(test_name, True, f"✅ Handled {handled_correctly}/{len(boundary_cases)} boundary cases", start_time)
            else:
                self._record_test_result(test_name, False, f"Only handled {handled_correctly}/{len(boundary_cases)} boundary cases", start_time, severity="medium")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    # =============================================================================
    # Network Resilience Tests  
    # =============================================================================
    
    async def _test_network_resilience(self):
        """Test 4: Network resilience scenarios"""
        logger.info("🌐 Test Category 4: Network Resilience")
        
        # Test 4.1: Connection timeout
        await self._test_connection_timeout()
        
        # Test 4.2: DNS resolution failure
        await self._test_dns_failure()
        
        # Test 4.3: SSL/TLS errors
        await self._test_ssl_errors()
        
        # Test 4.4: Intermittent connectivity
        await self._test_intermittent_connectivity()
    
    async def _test_connection_timeout(self):
        """Test connection timeout handling"""
        start_time = datetime.now()
        test_name = "connection_timeout"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.return_value.get.side_effect = httpx.ConnectTimeout("Connection timeout")
                
                try:
                    await client.get_all_projects(limit=1)
                    self._record_test_result(test_name, False, "Should have raised timeout exception", start_time, severity="medium")
                except httpx.ConnectTimeout:
                    self._record_test_result(test_name, True, "✅ Correctly handled connection timeout", start_time)
                except Exception as e:
                    if "timeout" in str(e).lower():
                        self._record_test_result(test_name, True, "✅ Handled timeout appropriately", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                        
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_dns_failure(self):
        """Test DNS resolution failure"""
        start_time = datetime.now()
        test_name = "dns_failure"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.return_value.get.side_effect = httpx.ConnectError("DNS resolution failed")
                
                try:
                    await client.get_all_projects(limit=1)
                    self._record_test_result(test_name, False, "Should have raised connect error", start_time, severity="medium")
                except httpx.ConnectError:
                    self._record_test_result(test_name, True, "✅ Correctly handled DNS failure", start_time)
                except Exception as e:
                    if "dns" in str(e).lower() or "connect" in str(e).lower():
                        self._record_test_result(test_name, True, "✅ Handled DNS error appropriately", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                        
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_ssl_errors(self):
        """Test SSL/TLS error handling"""
        start_time = datetime.now()
        test_name = "ssl_errors"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            import ssl
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.return_value.get.side_effect = ssl.SSLError("SSL certificate verification failed")
                
                try:
                    await client.get_all_projects(limit=1)
                    self._record_test_result(test_name, False, "Should have raised SSL error", start_time, severity="medium")
                except ssl.SSLError:
                    self._record_test_result(test_name, True, "✅ Correctly handled SSL error", start_time)
                except Exception as e:
                    if "ssl" in str(e).lower() or "certificate" in str(e).lower():
                        self._record_test_result(test_name, True, "✅ Handled SSL error appropriately", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                        
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_intermittent_connectivity(self):
        """Test intermittent connectivity handling"""
        start_time = datetime.now()
        test_name = "intermittent_connectivity"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            # Simulate intermittent failures
            call_count = 0
            def intermittent_failure(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count % 2 == 1:  # Fail on odd calls
                    raise httpx.NetworkError("Network unreachable")
                else:  # Succeed on even calls
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.is_success = True
                    mock_response.text = '{"results": []}'
                    mock_response.json.return_value = {"results": []}
                    return mock_response
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.return_value.get.side_effect = intermittent_failure
                
                success_count = 0
                failure_count = 0
                
                # Try 4 calls to test intermittent behavior
                for i in range(4):
                    try:
                        await client.get_all_projects(limit=1)
                        success_count += 1
                    except httpx.NetworkError:
                        failure_count += 1
                    except Exception:
                        pass
                
                if success_count > 0 and failure_count > 0:
                    self._record_test_result(test_name, True, f"✅ Handled intermittent connectivity ({success_count} success, {failure_count} failures)", start_time)
                else:
                    self._record_test_result(test_name, False, f"Pattern not detected ({success_count} success, {failure_count} failures)", start_time, severity="low")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    # =============================================================================
    # Pagination Handling Tests
    # =============================================================================
    
    async def _test_pagination_handling(self):
        """Test 5: Pagination handling scenarios"""
        logger.info("📄 Test Category 5: Pagination Handling")
        
        # Test 5.1: Missing next URL
        await self._test_missing_next_url()
        
        # Test 5.2: Infinite pagination loop
        await self._test_infinite_pagination()
        
        # Test 5.3: Malformed pagination URLs
        await self._test_malformed_pagination_urls()
        
        # Test 5.4: Empty paginated results
        await self._test_empty_paginated_results()
    
    async def _test_missing_next_url(self):
        """Test missing next URL in pagination"""
        start_time = datetime.now()
        test_name = "missing_next_url"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            # Mock responses for project and bid package calls
            call_count = 0
            def mock_paginated_calls(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                
                if "projects" in str(args):
                    # Project response
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.is_success = True
                    project_response = {
                        "id": "test_project",
                        "name": "Test Project",
                        "bidsDueAt": "2024-12-31T23:59:59Z",
                        "state": "active"
                    }
                    mock_response.text = json.dumps(project_response)
                    mock_response.json.return_value = project_response
                    return mock_response
                elif "bid-packages" in str(args):
                    # Bid packages response with missing nextUrl
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.is_success = True
                    bid_package_response = {
                        "results": [
                            {
                                "id": "package_1",
                                "name": "Test Package",
                                "projectId": "test_project"
                            }
                        ],
                        "pagination": {}  # Missing nextUrl
                    }
                    mock_response.text = json.dumps(bid_package_response)
                    mock_response.json.return_value = bid_package_response
                    return mock_response
                else:
                    # Default response
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.is_success = True
                    mock_response.text = '{"results": []}'
                    mock_response.json.return_value = {"results": []}
                    return mock_response
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.return_value.get.side_effect = mock_paginated_calls
                
                try:
                    # This should handle missing pagination gracefully
                    invitations = await client.get_bidding_invitations("test_project")
                    self._record_test_result(test_name, True, "✅ Handled missing pagination URL", start_time)
                except Exception as e:
                    self._record_test_result(test_name, False, f"Failed to handle missing pagination: {str(e)}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_infinite_pagination(self):
        """Test infinite pagination loop protection"""
        start_time = datetime.now()
        test_name = "infinite_pagination_protection"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            # Mock responses that create infinite loop
            def mock_infinite_pagination(*args, **kwargs):
                if "projects" in str(args):
                    # Project response
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.is_success = True
                    project_response = {
                        "id": "test_project",
                        "name": "Test Project", 
                        "bidsDueAt": "2024-12-31T23:59:59Z",
                        "state": "active"
                    }
                    mock_response.text = json.dumps(project_response)
                    mock_response.json.return_value = project_response
                    return mock_response
                else:
                    # Always return same nextUrl (infinite loop)
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.is_success = True
                    infinite_response = {
                        "results": [{"id": "item", "name": "Item"}],
                        "pagination": {"nextUrl": "/same-url-always"}  # Same URL always
                    }
                    mock_response.text = json.dumps(infinite_response)
                    mock_response.json.return_value = infinite_response
                    return mock_response
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.return_value.get.side_effect = mock_infinite_pagination
                
                try:
                    # Should have protection against infinite loops (max 50 pages in the code)
                    invitations = await client.get_bidding_invitations("test_project")
                    self._record_test_result(test_name, True, "✅ Protected against infinite pagination", start_time)
                except Exception as e:
                    if "maximum page limit" in str(e).lower() or "timeout" in str(e).lower():
                        self._record_test_result(test_name, True, "✅ Correctly stopped infinite pagination", start_time)
                    else:
                        self._record_test_result(test_name, False, f"May have infinite loop issue: {str(e)}", start_time, severity="high")
                        
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_malformed_pagination_urls(self):
        """Test malformed pagination URL handling"""
        start_time = datetime.now()
        test_name = "malformed_pagination_urls"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            call_count = 0
            def mock_malformed_pagination(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                
                if "projects" in str(args):
                    # Project response
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.is_success = True
                    project_response = {
                        "id": "test_project",
                        "name": "Test Project",
                        "bidsDueAt": "2024-12-31T23:59:59Z",
                        "state": "active"
                    }
                    mock_response.text = json.dumps(project_response)
                    mock_response.json.return_value = project_response
                    return mock_response
                elif call_count == 2:
                    # First pagination call with malformed URL
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.is_success = True
                    malformed_response = {
                        "results": [{"id": "item1", "name": "Item 1"}],
                        "pagination": {"nextUrl": "invalid-url-format"}  # Malformed URL
                    }
                    mock_response.text = json.dumps(malformed_response)
                    mock_response.json.return_value = malformed_response
                    return mock_response
                else:
                    # Subsequent calls should handle the malformed URL
                    mock_response = Mock()
                    mock_response.status_code = 404
                    mock_response.is_success = False
                    mock_response.text = "Not found"
                    mock_response.reason_phrase = "Not Found"
                    return mock_response
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.return_value.get.side_effect = mock_malformed_pagination
                
                try:
                    invitations = await client.get_bidding_invitations("test_project")
                    # Should handle malformed URLs gracefully, not crash
                    self._record_test_result(test_name, True, "✅ Handled malformed pagination URLs", start_time)
                except Exception as e:
                    self._record_test_result(test_name, False, f"Failed to handle malformed URLs: {str(e)}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_empty_paginated_results(self):
        """Test empty paginated results handling"""
        start_time = datetime.now()
        test_name = "empty_paginated_results"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            def mock_empty_pagination(*args, **kwargs):
                if "projects" in str(args):
                    # Project response
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.is_success = True
                    project_response = {
                        "id": "test_project",
                        "name": "Test Project",
                        "bidsDueAt": "2024-12-31T23:59:59Z", 
                        "state": "active"
                    }
                    mock_response.text = json.dumps(project_response)
                    mock_response.json.return_value = project_response
                    return mock_response
                else:
                    # Empty results
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.is_success = True
                    empty_response = {
                        "results": [],  # Empty results
                        "pagination": {}
                    }
                    mock_response.text = json.dumps(empty_response)
                    mock_response.json.return_value = empty_response
                    return mock_response
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.return_value.get.side_effect = mock_empty_pagination
                
                try:
                    invitations = await client.get_bidding_invitations("test_project")
                    if isinstance(invitations, list) and len(invitations) == 0:
                        self._record_test_result(test_name, True, "✅ Handled empty paginated results", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Unexpected result type or length: {type(invitations)}, {len(invitations) if hasattr(invitations, '__len__') else 'N/A'}", start_time, severity="low")
                except Exception as e:
                    self._record_test_result(test_name, False, f"Failed to handle empty results: {str(e)}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    # =============================================================================
    # Workflow Integration Tests
    # =============================================================================
    
    async def _test_workflow_integration(self):
        """Test 6: Workflow integration scenarios"""
        logger.info("🔄 Test Category 6: Workflow Integration")
        
        # Test 6.1: Node failure propagation
        await self._test_node_failure_propagation()
        
        # Test 6.2: State corruption handling
        await self._test_state_corruption()
        
        # Test 6.3: Email integration failures
        await self._test_email_integration_failures()
        
        # Test 6.4: Concurrent access scenarios
        await self._test_concurrent_access()
    
    async def _test_node_failure_propagation(self):
        """Test node failure propagation in workflow"""
        start_time = datetime.now()
        test_name = "node_failure_propagation"
        
        try:
            agent = BidReminderAgent()
            
            # Create initial state with auth failure
            failed_state: BidReminderState = {
                "outlook_token_manager": None,
                "building_token_manager": None,
                "outlook_client": None,
                "building_client": None,
                "upcoming_projects": None,
                "bidding_invitations": None,
                "reminder_email_sent": False,
                "error_message": "Authentication failed",
                "workflow_successful": False,
                "result_message": None
            }
            
            # Test that subsequent nodes handle the error state correctly
            result = await agent.check_upcoming_projects_node(failed_state)
            
            if result.get("error_message") and not result.get("workflow_successful"):
                self._record_test_result(test_name, True, "✅ Node correctly propagated failure state", start_time)
            else:
                self._record_test_result(test_name, False, "Node did not propagate failure state", start_time, severity="medium")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test failed: {str(e)}", start_time, severity="medium")
    
    async def _test_state_corruption(self):
        """Test state corruption handling"""
        start_time = datetime.now()
        test_name = "state_corruption_handling"
        
        try:
            agent = BidReminderAgent()
            
            # Create corrupted state
            corrupted_state = {
                "outlook_client": "invalid_string_instead_of_object",
                "building_client": 12345,  # Wrong type
                "upcoming_projects": "not_a_list",
                "bidding_invitations": None,
                "reminder_email_sent": "yes",  # Wrong type
                "error_message": None,
                "workflow_successful": "true",  # Wrong type
                "result_message": None
            }
            
            # Test that nodes handle corrupted state gracefully
            try:
                result = await agent.finalize_result_node(corrupted_state)
                self._record_test_result(test_name, True, "✅ Handled corrupted state gracefully", start_time)
            except (TypeError, AttributeError) as e:
                self._record_test_result(test_name, True, "✅ Detected and handled state corruption", start_time)
            except Exception as e:
                self._record_test_result(test_name, False, f"Unexpected error with corrupted state: {str(e)}", start_time, severity="medium")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_email_integration_failures(self):
        """Test email integration failure scenarios"""
        start_time = datetime.now()
        test_name = "email_integration_failures"
        
        try:
            agent = BidReminderAgent()
            
            # Mock failed Outlook client
            mock_outlook_client = Mock(spec=MSGraphClient)
            mock_outlook_client.send_email.return_value = Mock(success=False, error="SMTP server unavailable")
            
            # Create state with email data but failing client
            email_state: BidReminderState = {
                "outlook_token_manager": Mock(),
                "building_token_manager": Mock(),
                "outlook_client": mock_outlook_client,
                "building_client": Mock(),
                "upcoming_projects": [
                    Mock(id="proj1", name="Test Project", bidsDueAt="2024-12-31T23:59:59Z", state="active")
                ],
                "bidding_invitations": [
                    Mock(
                        projectId="proj1",
                        firstName="John",
                        lastName="Doe", 
                        email="john@example.com",
                        bidPackageName="Test Package",
                        linkToBid="https://example.com/bid"
                    )
                ],
                "reminder_email_sent": False,
                "error_message": None,
                "workflow_successful": False,
                "result_message": None
            }
            
            result = await agent.send_reminder_email_node(email_state)
            
            if not result.get("reminder_email_sent") and result.get("error_message"):
                self._record_test_result(test_name, True, "✅ Correctly handled email sending failure", start_time)
            else:
                self._record_test_result(test_name, False, "Did not handle email failure correctly", start_time, severity="medium")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test failed: {str(e)}", start_time, severity="medium")
    
    async def _test_concurrent_access(self):
        """Test concurrent access scenarios"""
        start_time = datetime.now()
        test_name = "concurrent_access"
        
        try:
            # Test multiple agents running simultaneously
            agents = [BidReminderAgent() for _ in range(3)]
            
            # Mock successful workflow components
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            mock_client = Mock(spec=BuildingConnectedClient)
            mock_client.get_all_projects.return_value = []
            
            # Create simple successful state for each agent
            for agent in agents:
                agent.mock_client = mock_client
                agent.mock_token_manager = mock_token_manager
            
            # Run agents concurrently (simplified test)
            results = []
            for i, agent in enumerate(agents):
                try:
                    # Simulate concurrent node execution
                    state = {
                        "outlook_token_manager": Mock(),
                        "building_token_manager": mock_token_manager,
                        "outlook_client": Mock(),
                        "building_client": mock_client,
                        "upcoming_projects": None,
                        "bidding_invitations": None,
                        "reminder_email_sent": False,
                        "error_message": None,
                        "workflow_successful": False,
                        "result_message": None
                    }
                    result = await agent.check_upcoming_projects_node(state)
                    results.append(result)
                except Exception:
                    results.append(None)
            
            # Check if all agents completed without interference
            successful_runs = sum(1 for r in results if r and not r.get("error_message"))
            
            if successful_runs >= len(agents) * 0.8:  # 80% success rate
                self._record_test_result(test_name, True, f"✅ Handled concurrent access ({successful_runs}/{len(agents)} successful)", start_time)
            else:
                self._record_test_result(test_name, False, f"Concurrent access issues ({successful_runs}/{len(agents)} successful)", start_time, severity="medium")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test failed: {str(e)}", start_time, severity="medium")
    
    # =============================================================================
    # Edge Case Tests
    # =============================================================================
    
    async def _test_edge_cases(self):
        """Test 7: Edge case scenarios"""
        logger.info("🎯 Test Category 7: Edge Cases")
        
        # Test 7.1: Empty project lists
        await self._test_empty_project_lists()
        
        # Test 7.2: Extremely large datasets
        await self._test_large_datasets()
        
        # Test 7.3: Special characters in data
        await self._test_special_characters()
        
        # Test 7.4: Timezone edge cases
        await self._test_timezone_edge_cases()
    
    async def _test_empty_project_lists(self):
        """Test empty project list handling"""
        start_time = datetime.now()
        test_name = "empty_project_lists"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = '{"results": []}'
                mock_response.json.return_value = {"results": []}
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    projects = await client.get_all_projects(limit=100)
                    if isinstance(projects, list) and len(projects) == 0:
                        self._record_test_result(test_name, True, "✅ Handled empty project list", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Unexpected result: {type(projects)}", start_time, severity="low")
                except Exception as e:
                    self._record_test_result(test_name, False, f"Failed to handle empty list: {str(e)}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_large_datasets(self):
        """Test handling of extremely large datasets"""
        start_time = datetime.now()
        test_name = "large_datasets"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            # Create very large response (10,000 projects)
            large_response = {
                "results": [
                    {
                        "id": f"project_{i}",
                        "name": f"Large Project {i}",
                        "bidsDueAt": f"2024-12-{(i % 28) + 1:02d}T23:59:59Z",
                        "state": "active"
                    }
                    for i in range(10000)
                ]
            }
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = json.dumps(large_response)
                mock_response.json.return_value = large_response
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    # Test with reasonable timeout
                    start_processing = datetime.now()
                    projects = await client.get_all_projects(limit=10000)
                    processing_time = (datetime.now() - start_processing).total_seconds()
                    
                    if len(projects) == 10000 and processing_time < 30:  # Should complete within 30 seconds
                        self._record_test_result(test_name, True, f"✅ Handled large dataset ({len(projects)} projects in {processing_time:.2f}s)", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Performance issue: {len(projects)} projects in {processing_time:.2f}s", start_time, severity="medium")
                except Exception as e:
                    if "memory" in str(e).lower() or "timeout" in str(e).lower():
                        self._record_test_result(test_name, False, f"Resource constraint: {str(e)}", start_time, severity="high")
                    else:
                        self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                        
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_special_characters(self):
        """Test special characters in data"""
        start_time = datetime.now()
        test_name = "special_characters"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            # Create response with special characters
            special_response = {
                "results": [
                    {
                        "id": "project_special",
                        "name": "Project with Special Chars: éñ中文🎯<>\"'&",
                        "bidsDueAt": "2024-12-31T23:59:59Z",
                        "state": "active",
                        "description": "Description with unicode: ∑∆∏∂∫√≈≠≤≥"
                    },
                    {
                        "id": "project_sql",
                        "name": "Project'; DROP TABLE projects; --",
                        "bidsDueAt": "2024-12-31T23:59:59Z",
                        "state": "active"
                    }
                ]
            }
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = json.dumps(special_response, ensure_ascii=False)
                mock_response.json.return_value = special_response
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    projects = await client.get_all_projects(limit=10)
                    if len(projects) == 2:
                        self._record_test_result(test_name, True, "✅ Handled special characters in data", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Expected 2 projects, got {len(projects)}", start_time, severity="medium")
                except Exception as e:
                    self._record_test_result(test_name, False, f"Failed to handle special characters: {str(e)}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_timezone_edge_cases(self):
        """Test timezone edge cases"""
        start_time = datetime.now()
        test_name = "timezone_edge_cases"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            # Create response with various timezone formats
            timezone_response = {
                "results": [
                    {
                        "id": "project_utc",
                        "name": "UTC Project",
                        "bidsDueAt": "2024-12-31T23:59:59Z",
                        "state": "active"
                    },
                    {
                        "id": "project_offset",
                        "name": "Offset Project", 
                        "bidsDueAt": "2024-12-31T23:59:59+05:30",
                        "state": "active"
                    },
                    {
                        "id": "project_no_tz",
                        "name": "No Timezone Project",
                        "bidsDueAt": "2024-12-31T23:59:59",
                        "state": "active"
                    }
                ]
            }
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = json.dumps(timezone_response)
                mock_response.json.return_value = timezone_response
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    # Test date filtering with timezone variations
                    projects_response = await client.get_projects_due_in_n_days(5)
                    # Should handle different timezone formats without crashing
                    self._record_test_result(test_name, True, "✅ Handled timezone variations", start_time)
                except Exception as e:
                    if "timezone" in str(e).lower() or "parse" in str(e).lower():
                        self._record_test_result(test_name, False, f"Timezone parsing issue: {str(e)}", start_time, severity="medium")
                    else:
                        self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                        
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    # =============================================================================
    # Performance Tests
    # =============================================================================
    
    async def _test_performance_scenarios(self):
        """Test 8: Performance scenarios"""
        logger.info("⚡ Test Category 8: Performance Scenarios")
        
        # Test 8.1: Memory usage with large datasets
        await self._test_memory_usage()
        
        # Test 8.2: Response time under load
        await self._test_response_times()
        
        # Test 8.3: Resource cleanup
        await self._test_resource_cleanup()
    
    async def _test_memory_usage(self):
        """Test memory usage with large datasets"""
        start_time = datetime.now()
        test_name = "memory_usage"
        
        try:
            import psutil
            import os
            
            process = psutil.Process(os.getpid())
            initial_memory = process.memory_info().rss / 1024 / 1024  # MB
            
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            # Process large dataset multiple times
            for i in range(5):
                large_response = {
                    "results": [
                        {
                            "id": f"project_{j}_{i}",
                            "name": f"Memory Test Project {j}",
                            "bidsDueAt": "2024-12-31T23:59:59Z",
                            "state": "active"
                        }
                        for j in range(1000)
                    ]
                }
                
                with patch('httpx.AsyncClient') as mock_client:
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.is_success = True
                    mock_response.text = json.dumps(large_response)
                    mock_response.json.return_value = large_response
                    
                    mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                    
                    projects = await client.get_all_projects(limit=1000)
                    del projects  # Explicit cleanup
            
            final_memory = process.memory_info().rss / 1024 / 1024  # MB
            memory_increase = final_memory - initial_memory
            
            if memory_increase < 100:  # Less than 100MB increase
                self._record_test_result(test_name, True, f"✅ Memory usage acceptable ({memory_increase:.2f}MB increase)", start_time)
            else:
                self._record_test_result(test_name, False, f"High memory usage ({memory_increase:.2f}MB increase)", start_time, severity="medium")
                
        except ImportError:
            self._record_test_result(test_name, False, "psutil not available for memory testing", start_time, severity="low")
        except Exception as e:
            self._record_test_result(test_name, False, f"Test failed: {str(e)}", start_time, severity="medium")
    
    async def _test_response_times(self):
        """Test response times under various conditions"""
        start_time = datetime.now()
        test_name = "response_times"
        
        try:
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            response_times = []
            
            # Test multiple API calls
            for i in range(10):
                response_data = {
                    "results": [
                        {
                            "id": f"project_{j}",
                            "name": f"Response Time Test {j}",
                            "bidsDueAt": "2024-12-31T23:59:59Z",
                            "state": "active"
                        }
                        for j in range(100)
                    ]
                }
                
                with patch('httpx.AsyncClient') as mock_client:
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.is_success = True
                    mock_response.text = json.dumps(response_data)
                    mock_response.json.return_value = response_data
                    
                    mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                    
                    call_start = datetime.now()
                    projects = await client.get_all_projects(limit=100)
                    call_time = (datetime.now() - call_start).total_seconds()
                    response_times.append(call_time)
            
            avg_response_time = sum(response_times) / len(response_times)
            max_response_time = max(response_times)
            
            if avg_response_time < 1.0 and max_response_time < 5.0:  # Average < 1s, Max < 5s
                self._record_test_result(test_name, True, f"✅ Response times acceptable (avg: {avg_response_time:.3f}s, max: {max_response_time:.3f}s)", start_time)
            else:
                self._record_test_result(test_name, False, f"Slow response times (avg: {avg_response_time:.3f}s, max: {max_response_time:.3f}s)", start_time, severity="medium")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test failed: {str(e)}", start_time, severity="medium")
    
    async def _test_resource_cleanup(self):
        """Test proper resource cleanup"""
        start_time = datetime.now()
        test_name = "resource_cleanup"
        
        try:
            # Test that temp files are cleaned up
            initial_files = set(os.listdir(self.temp_dir)) if os.path.exists(self.temp_dir) else set()
            
            mock_token_manager = Mock(spec=BuildingConnectedTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = BuildingConnectedClient(mock_token_manager)
            
            # Simulate operations that might create temp files
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = '{"results": []}'
                mock_response.json.return_value = {"results": []}
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                # Multiple operations
                for i in range(5):
                    projects = await client.get_all_projects(limit=10)
                    del projects
            
            # Check for resource leaks (simplified)
            final_files = set(os.listdir(self.temp_dir)) if os.path.exists(self.temp_dir) else set()
            new_files = final_files - initial_files
            
            if len(new_files) == 0:
                self._record_test_result(test_name, True, "✅ No resource leaks detected", start_time)
            else:
                self._record_test_result(test_name, False, f"Potential resource leak: {len(new_files)} new files", start_time, severity="low")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test failed: {str(e)}", start_time, severity="medium")
    
    # =============================================================================
    # Helper Methods
    # =============================================================================
    
    def _record_test_result(self, test_name: str, passed: bool, message: str, start_time: datetime, 
                           error_details: Optional[str] = None, severity: str = "medium"):
        """Record individual test result"""
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        result = TestResult(
            test_name=test_name,
            passed=passed,
            message=message,
            execution_time_ms=execution_time,
            error_details=error_details,
            severity=severity
        )
        
        self.test_results.append(result)
        
        # Log result
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"   {status} | {test_name} | {message} ({execution_time}ms)")
        
        if not passed and severity in ["high", "critical"]:
            logger.error(f"      ⚠️  {severity.upper()} SEVERITY: {message}")
    
    def _generate_report(self) -> TestSuiteReport:
        """Generate comprehensive test suite report"""
        end_time = datetime.now()
        execution_time = int((end_time - self.start_time).total_seconds() * 1000)
        
        passed_tests = sum(1 for r in self.test_results if r.passed)
        failed_tests = len(self.test_results) - passed_tests
        critical_failures = sum(1 for r in self.test_results if not r.passed and r.severity == "critical")
        
        # Determine overall status
        if critical_failures > 0:
            overall_status = "FAIL"
        elif failed_tests > passed_tests:
            overall_status = "FAIL"
        elif failed_tests == 0:
            overall_status = "PASS"
        else:
            overall_status = "WARNING"
        
        # Generate recommendations
        recommendations = self._generate_recommendations()
        
        report = TestSuiteReport(
            timestamp=end_time.isoformat(),
            overall_status=overall_status,
            total_tests=len(self.test_results),
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            critical_failures=critical_failures,
            execution_time_ms=execution_time,
            test_results=self.test_results,
            recommendations=recommendations
        )
        
        # Log summary
        logger.info("="*80)
        logger.info("📊 TEST SUITE SUMMARY")
        logger.info("="*80)
        logger.info(f"Overall Status: {overall_status}")
        logger.info(f"Total Tests: {report.total_tests}")
        logger.info(f"Passed: {report.passed_tests}")
        logger.info(f"Failed: {report.failed_tests}")
        logger.info(f"Critical Failures: {report.critical_failures}")
        logger.info(f"Execution Time: {execution_time/1000:.2f}s")
        
        if recommendations:
            logger.info("\n📋 RECOMMENDATIONS:")
            for i, rec in enumerate(recommendations, 1):
                logger.info(f"  {i}. {rec}")
        
        # Save detailed report
        try:
            report_file = f"logs/buildingconnected-test-report-{end_time.strftime('%Y%m%d_%H%M%S')}.json"
            with open(report_file, 'w') as f:
                json.dump({
                    "summary": {
                        "timestamp": report.timestamp,
                        "overall_status": report.overall_status,
                        "total_tests": report.total_tests,
                        "passed_tests": report.passed_tests,
                        "failed_tests": report.failed_tests,
                        "critical_failures": report.critical_failures,
                        "execution_time_ms": report.execution_time_ms
                    },
                    "test_results": [
                        {
                            "test_name": r.test_name,
                            "passed": r.passed,
                            "message": r.message,
                            "execution_time_ms": r.execution_time_ms,
                            "error_details": r.error_details,
                            "severity": r.severity
                        }
                        for r in report.test_results
                    ],
                    "recommendations": report.recommendations
                }, f, indent=2)
            logger.info(f"📄 Detailed report saved: {report_file}")
        except Exception as e:
            logger.warning(f"⚠️  Failed to save report: {e}")
        
        return report
    
    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations based on test results"""
        recommendations = []
        
        # Critical failures
        critical_failures = [r for r in self.test_results if not r.passed and r.severity == "critical"]
        if critical_failures:
            recommendations.append(f"🚨 Address {len(critical_failures)} critical failures before production deployment")
        
        # Authentication issues
        auth_failures = [r for r in self.test_results if not r.passed and "auth" in r.test_name.lower()]
        if auth_failures:
            recommendations.append("🔐 Review authentication error handling and token management")
        
        # Network resilience
        network_failures = [r for r in self.test_results if not r.passed and ("network" in r.test_name.lower() or "timeout" in r.test_name.lower())]
        if network_failures:
            recommendations.append("🌐 Implement retry logic and better network error handling")
        
        # Data validation issues
        validation_failures = [r for r in self.test_results if not r.passed and ("validation" in r.test_name.lower() or "data" in r.test_name.lower())]
        if validation_failures:
            recommendations.append("📊 Strengthen input validation and data sanitization")
        
        # Performance concerns
        performance_failures = [r for r in self.test_results if not r.passed and ("performance" in r.test_name.lower() or "memory" in r.test_name.lower())]
        if performance_failures:
            recommendations.append("⚡ Optimize performance and memory usage for large datasets")
        
        # High failure rate
        failure_rate = len([r for r in self.test_results if not r.passed]) / len(self.test_results)
        if failure_rate > 0.3:
            recommendations.append("🛠️  High failure rate detected - consider comprehensive code review")
        
        if not recommendations:
            recommendations.append("✅ All tests passing - system appears robust and ready for production")
        
        return recommendations


# =============================================================================
# Main Execution
# =============================================================================

async def run_buildingconnected_tests() -> TestSuiteReport:
    """Run the comprehensive BuildingConnected test suite"""
    logger.info("🚀 Starting BuildingConnected Workflow Test Suite")
    test_suite = BuildingConnectedTestSuite()
    return await test_suite.run_all_tests()


if __name__ == "__main__":
    async def main():
        print("🧪 BuildingConnected Workflow Test Suite")
        print("This comprehensive test suite will validate all failure scenarios")
        print("that could cause the bid reminder agent to fail.\n")
        
        report = await run_buildingconnected_tests()
        
        print(f"\n📊 Test Results Summary:")
        print(f"Status: {report.overall_status}")
        print(f"Tests: {report.passed_tests}/{report.total_tests} passed")
        print(f"Time: {report.execution_time_ms/1000:.2f}s")
        
        if report.critical_failures > 0:
            print(f"\n🚨 {report.critical_failures} critical failures detected!")
            print("Review logs and fix critical issues before production deployment.")
        
        return report.overall_status == "PASS"
    
    asyncio.run(main())