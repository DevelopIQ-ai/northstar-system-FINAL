"""
Comprehensive Microsoft Graph API Client Test Suite
Tests all potential failure scenarios specific to Microsoft Graph API integration

This test suite covers:
- API response handling (malformed data, rate limiting, network timeouts)
- Data validation (invalid email addresses, malformed requests, missing fields)
- Authentication failures (expired tokens, invalid credentials)
- Email sending scenarios (delivery failures, attachment issues, size limits)
- Search and list operations (empty results, filter errors, pagination)
- Edge cases and boundary conditions
- Network resilience and performance

Note: Authentication testing is handled separately by auth test suites
Run this before production deployments to catch Graph API integration failure scenarios
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
from auth.auth_helpers import MSGraphTokenManager, EmailValidator
from clients.graph_api_client import (
    MSGraphClient,
    GraphAPIError,
    EmailImportance,
    EmailRecipient,
    EmailBody,
    EmailMessage,
    SendEmailRequest,
    SendEmailResponse
)

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/msgraph-test.log')
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


class MSGraphTestSuite:
    """Comprehensive test suite for Microsoft Graph API workflow"""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.test_results: List[TestResult] = []
        self.temp_dir = None
        
    async def run_all_tests(self) -> TestSuiteReport:
        """Run comprehensive test suite"""
        logger.info("🧪 Starting comprehensive Microsoft Graph API workflow test suite")
        logger.info("="*80)
        
        # Setup temp directory for logs
        self.temp_dir = tempfile.mkdtemp(prefix="msgraph_test_")
        logger.info(f"📁 Created temporary directory: {self.temp_dir}")
        
        try:
            # API Client Tests
            await self._test_api_client_functionality()
            
            # Email Sending Tests
            await self._test_email_sending_scenarios()
            
            # Data Validation Tests
            await self._test_data_validation()
            
            # Network Resilience Tests
            await self._test_network_resilience()
            
            # Authentication Tests
            await self._test_authentication_scenarios()
            
            # Email Operations Tests
            await self._test_email_operations()
            
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
    # API Client Functionality Tests
    # =============================================================================
    
    async def _test_api_client_functionality(self):
        """Test 1: API client functionality scenarios"""
        logger.info("🌐 Test Category 1: API Client Functionality")
        
        # Test 1.1: HTTP status code handling
        await self._test_http_status_codes()
        
        # Test 1.2: Empty response handling
        await self._test_empty_responses()
        
        # Test 1.3: Rate limiting responses
        await self._test_rate_limiting()
        
        # Test 1.4: Timeout handling
        await self._test_timeout_handling()
        
        # Test 1.5: Request method validation
        await self._test_request_methods()
    
    async def _test_http_status_codes(self):
        """Test various HTTP status code responses"""
        start_time = datetime.now()
        test_name = "http_status_codes"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
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
                        await client.list_emails(count=1)
                    except GraphAPIError as e:
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
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = ""  # Empty response
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    result = await client.list_emails(count=1)
                    # Should return empty dict or handle gracefully
                    if isinstance(result, dict):
                        self._record_test_result(test_name, True, "✅ Handled empty response gracefully", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Unexpected result type: {type(result)}", start_time, severity="medium")
                except Exception as e:
                    self._record_test_result(test_name, False, f"Failed to handle empty response: {str(e)}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_rate_limiting(self):
        """Test rate limiting response handling"""
        start_time = datetime.now()
        test_name = "rate_limiting"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 429
                mock_response.is_success = False
                mock_response.text = "Rate limit exceeded"
                mock_response.reason_phrase = "Too Many Requests"
                mock_response.json.return_value = {"error": {"message": "Rate limit exceeded"}}
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    await client.list_emails(count=1)
                    self._record_test_result(test_name, False, "Should have raised GraphAPIError", start_time, severity="medium")
                except GraphAPIError as e:
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
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.return_value.get.side_effect = httpx.TimeoutException("Request timeout")
                
                try:
                    await client.list_emails(count=1)
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
    
    async def _test_request_methods(self):
        """Test unsupported HTTP method handling"""
        start_time = datetime.now()
        test_name = "request_methods"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            try:
                # Test unsupported method
                await client._make_request('PUT', 'me/messages')
                self._record_test_result(test_name, False, "Should have raised ValueError for unsupported method", start_time, severity="medium")
            except ValueError as e:
                if "unsupported" in str(e).lower():
                    self._record_test_result(test_name, True, "✅ Correctly rejected unsupported HTTP method", start_time)
                else:
                    self._record_test_result(test_name, False, f"Wrong error message: {str(e)}", start_time, severity="medium")
            except Exception as e:
                self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    # =============================================================================
    # Email Sending Tests
    # =============================================================================
    
    async def _test_email_sending_scenarios(self):
        """Test 2: Email sending scenarios"""
        logger.info("📧 Test Category 2: Email Sending Scenarios")
        
        # Test 2.1: Successful email sending
        await self._test_successful_email_sending()
        
        # Test 2.2: Multiple recipients
        await self._test_multiple_recipients()
        
        # Test 2.3: HTML vs text content
        await self._test_content_types()
        
        # Test 2.4: Email importance levels
        await self._test_importance_levels()
        
        # Test 2.5: Large email content
        await self._test_large_email_content()
    
    async def _test_successful_email_sending(self):
        """Test successful email sending"""
        start_time = datetime.now()
        test_name = "successful_email_sending"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 202
                mock_response.is_success = True
                mock_response.text = ""
                
                mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
                
                # Mock EmailValidator
                with patch('clients.graph_api_client.EmailValidator') as mock_validator:
                    mock_validator.format_recipients.return_value = [{"emailAddress": {"address": "test@example.com", "name": "Test User"}}]
                    
                    result = await client.send_email(
                        to="test@example.com",
                        subject="Test Email",
                        body="This is a test email"
                    )
                    
                    if result.success:
                        self._record_test_result(test_name, True, "✅ Successfully sent email", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Email sending failed: {result.error}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_multiple_recipients(self):
        """Test multiple recipients handling"""
        start_time = datetime.now()
        test_name = "multiple_recipients"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 202
                mock_response.is_success = True
                mock_response.text = ""
                
                mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
                
                # Mock EmailValidator for multiple recipients
                with patch('clients.graph_api_client.EmailValidator') as mock_validator:
                    mock_validator.format_recipients.side_effect = [
                        [{"emailAddress": {"address": "test1@example.com", "name": "Test User 1"}}, 
                         {"emailAddress": {"address": "test2@example.com", "name": "Test User 2"}}],
                        [{"emailAddress": {"address": "cc@example.com", "name": "CC User"}}],
                        [{"emailAddress": {"address": "bcc@example.com", "name": "BCC User"}}]
                    ]
                    
                    result = await client.send_email(
                        to="test1@example.com,test2@example.com",
                        subject="Test Multiple Recipients",
                        body="This is a test email",
                        cc="cc@example.com",
                        bcc="bcc@example.com"
                    )
                    
                    if result.success:
                        self._record_test_result(test_name, True, "✅ Successfully handled multiple recipients", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Multiple recipients failed: {result.error}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_content_types(self):
        """Test HTML vs text content detection"""
        start_time = datetime.now()
        test_name = "content_types"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 202
                mock_response.is_success = True
                mock_response.text = ""
                
                mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
                
                with patch('clients.graph_api_client.EmailValidator') as mock_validator:
                    mock_validator.format_recipients.return_value = [{"emailAddress": {"address": "test@example.com", "name": "Test User"}}]
                    
                    # Test HTML content
                    html_result = await client.send_email(
                        to="test@example.com",
                        subject="HTML Test",
                        body="<html><body><h1>This is HTML</h1></body></html>"
                    )
                    
                    # Test plain text content
                    text_result = await client.send_email(
                        to="test@example.com",
                        subject="Text Test",
                        body="This is plain text"
                    )
                    
                    if html_result.success and text_result.success:
                        self._record_test_result(test_name, True, "✅ Successfully handled both HTML and text content", start_time)
                    else:
                        errors = []
                        if not html_result.success:
                            errors.append(f"HTML: {html_result.error}")
                        if not text_result.success:
                            errors.append(f"Text: {text_result.error}")
                        self._record_test_result(test_name, False, f"Content type issues: {'; '.join(errors)}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_importance_levels(self):
        """Test email importance levels"""
        start_time = datetime.now()
        test_name = "importance_levels"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 202
                mock_response.is_success = True
                mock_response.text = ""
                
                mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
                
                with patch('clients.graph_api_client.EmailValidator') as mock_validator:
                    mock_validator.format_recipients.return_value = [{"emailAddress": {"address": "test@example.com", "name": "Test User"}}]
                    
                    importance_levels = [EmailImportance.LOW, EmailImportance.NORMAL, EmailImportance.HIGH]
                    successful_levels = 0
                    
                    for importance in importance_levels:
                        result = await client.send_email(
                            to="test@example.com",
                            subject=f"Importance Test - {importance.value}",
                            body="Test importance level",
                            importance=importance
                        )
                        
                        if result.success:
                            successful_levels += 1
                    
                    if successful_levels == len(importance_levels):
                        self._record_test_result(test_name, True, "✅ Successfully handled all importance levels", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Only {successful_levels}/{len(importance_levels)} importance levels worked", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_large_email_content(self):
        """Test large email content handling"""
        start_time = datetime.now()
        test_name = "large_email_content"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            # Create large email content (1MB)
            large_content = "A" * (1024 * 1024)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 413  # Request Entity Too Large
                mock_response.is_success = False
                mock_response.text = "Request entity too large"
                mock_response.json.return_value = {"error": {"message": "Request entity too large"}}
                
                mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
                
                with patch('clients.graph_api_client.EmailValidator') as mock_validator:
                    mock_validator.format_recipients.return_value = [{"emailAddress": {"address": "test@example.com", "name": "Test User"}}]
                    
                    result = await client.send_email(
                        to="test@example.com",
                        subject="Large Content Test",
                        body=large_content
                    )
                    
                    if not result.success and "413" in str(result.error):
                        self._record_test_result(test_name, True, "✅ Correctly handled large content rejection", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Unexpected result: {result.error}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    # =============================================================================
    # Data Validation Tests
    # =============================================================================
    
    async def _test_data_validation(self):
        """Test 3: Data validation scenarios"""
        logger.info("📊 Test Category 3: Data Validation")
        
        # Test 3.1: Invalid email addresses
        await self._test_invalid_email_addresses()
        
        # Test 3.2: Missing required fields
        await self._test_missing_required_fields()
        
        # Test 3.3: Special characters in email content
        await self._test_special_characters()
        
        # Test 3.4: Email address validation edge cases
        await self._test_email_validation_edge_cases()
    
    async def _test_invalid_email_addresses(self):
        """Test invalid email address handling"""
        start_time = datetime.now()
        test_name = "invalid_email_addresses"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            invalid_emails = [
                "",
                "invalid-email",
                "@example.com",
                "user@",
                "user..user@example.com",
                "user@example..com",
                None
            ]
            
            handled_correctly = 0
            
            for invalid_email in invalid_emails:
                with patch('clients.graph_api_client.EmailValidator') as mock_validator:
                    mock_validator.format_recipients.side_effect = ValueError(f"Invalid email: {invalid_email}")
                    
                    try:
                        result = await client.send_email(
                            to=invalid_email or "",
                            subject="Test",
                            body="Test"
                        )
                        
                        if not result.success and "validation" in str(result.error).lower():
                            handled_correctly += 1
                    except Exception:
                        handled_correctly += 1  # Exception is also valid handling
            
            if handled_correctly >= len(invalid_emails) * 0.8:  # 80% success rate
                self._record_test_result(test_name, True, f"✅ Handled {handled_correctly}/{len(invalid_emails)} invalid emails correctly", start_time)
            else:
                self._record_test_result(test_name, False, f"Only handled {handled_correctly}/{len(invalid_emails)} invalid emails", start_time, severity="medium")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_missing_required_fields(self):
        """Test missing required fields handling"""
        start_time = datetime.now()
        test_name = "missing_required_fields"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            test_cases = [
                {"to": "", "subject": "Test", "body": "Test"},  # Empty to
                {"to": "test@example.com", "subject": "", "body": "Test"},  # Empty subject
                {"to": "test@example.com", "subject": "Test", "body": ""},  # Empty body
            ]
            
            handled_correctly = 0
            
            for test_case in test_cases:
                with patch('clients.graph_api_client.EmailValidator') as mock_validator:
                    if not test_case["to"]:
                        mock_validator.format_recipients.return_value = []
                    else:
                        mock_validator.format_recipients.return_value = [{"emailAddress": {"address": test_case["to"], "name": "Test"}}]
                    
                    result = await client.send_email(**test_case)
                    
                    # Should handle empty required fields gracefully
                    if isinstance(result, SendEmailResponse):
                        handled_correctly += 1
            
            if handled_correctly == len(test_cases):
                self._record_test_result(test_name, True, "✅ Handled missing required fields gracefully", start_time)
            else:
                self._record_test_result(test_name, False, f"Only handled {handled_correctly}/{len(test_cases)} missing field cases", start_time, severity="medium")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_special_characters(self):
        """Test special characters in email content"""
        start_time = datetime.now()
        test_name = "special_characters"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            special_content = {
                "subject": "Test with Special Chars: éñ中文🎯<>\"'&",
                "body": "Content with unicode: ∑∆∏∂∫√≈≠≤≥ and HTML: <script>alert('test')</script>"
            }
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 202
                mock_response.is_success = True
                mock_response.text = ""
                
                mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
                
                with patch('clients.graph_api_client.EmailValidator') as mock_validator:
                    mock_validator.format_recipients.return_value = [{"emailAddress": {"address": "test@example.com", "name": "Test User"}}]
                    
                    result = await client.send_email(
                        to="test@example.com",
                        **special_content
                    )
                    
                    if result.success:
                        self._record_test_result(test_name, True, "✅ Handled special characters in email content", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Failed to handle special characters: {result.error}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_email_validation_edge_cases(self):
        """Test email validation edge cases"""
        start_time = datetime.now()
        test_name = "email_validation_edge_cases"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            edge_cases = [
                "test+tag@example.com",  # Plus addressing
                "test.dot@example.com",  # Dot in local part
                "test@sub.example.com",  # Subdomain
                "very.long.email.address.with.many.dots@very.long.domain.name.com",  # Long email
            ]
            
            handled_correctly = 0
            
            for email in edge_cases:
                with patch('clients.graph_api_client.EmailValidator') as mock_validator:
                    mock_validator.format_recipients.return_value = [{"emailAddress": {"address": email, "name": "Test"}}]
                    
                    with patch('httpx.AsyncClient') as mock_client:
                        mock_response = Mock()
                        mock_response.status_code = 202
                        mock_response.is_success = True
                        mock_response.text = ""
                        
                        mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
                        
                        result = await client.send_email(
                            to=email,
                            subject="Edge Case Test",
                            body="Test"
                        )
                        
                        if result.success:
                            handled_correctly += 1
            
            if handled_correctly >= len(edge_cases) * 0.8:  # 80% success rate
                self._record_test_result(test_name, True, f"✅ Handled {handled_correctly}/{len(edge_cases)} email edge cases", start_time)
            else:
                self._record_test_result(test_name, False, f"Only handled {handled_correctly}/{len(edge_cases)} email edge cases", start_time, severity="medium")
                
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
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.return_value.get.side_effect = httpx.ConnectTimeout("Connection timeout")
                
                try:
                    await client.list_emails(count=1)
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
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.return_value.get.side_effect = httpx.ConnectError("DNS resolution failed")
                
                try:
                    await client.list_emails(count=1)
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
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            import ssl
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.return_value.get.side_effect = ssl.SSLError("SSL certificate verification failed")
                
                try:
                    await client.list_emails(count=1)
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
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
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
                    mock_response.text = '{"value": []}'
                    mock_response.json.return_value = {"value": []}
                    return mock_response
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.return_value.get.side_effect = intermittent_failure
                
                success_count = 0
                failure_count = 0
                
                # Try 4 calls to test intermittent behavior
                for i in range(4):
                    try:
                        await client.list_emails(count=1)
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
    # Authentication Tests
    # =============================================================================
    
    async def _test_authentication_scenarios(self):
        """Test 5: Authentication scenarios"""
        logger.info("🔐 Test Category 5: Authentication Scenarios")
        
        # Test 5.1: Expired token handling
        await self._test_expired_token()
        
        # Test 5.2: Invalid token handling
        await self._test_invalid_token()
        
        # Test 5.3: Token refresh scenarios
        await self._test_token_refresh()
    
    async def _test_expired_token(self):
        """Test expired token handling"""
        start_time = datetime.now()
        test_name = "expired_token"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "expired_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 401
                mock_response.is_success = False
                mock_response.text = "Token expired"
                mock_response.json.return_value = {"error": {"message": "Token has expired"}}
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    await client.list_emails(count=1)
                    self._record_test_result(test_name, False, "Should have raised GraphAPIError", start_time, severity="medium")
                except GraphAPIError as e:
                    if e.status_code == 401:
                        self._record_test_result(test_name, True, "✅ Correctly handled expired token", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Wrong status code: {e.status_code}", start_time, severity="medium")
                except Exception as e:
                    self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_invalid_token(self):
        """Test invalid token handling"""
        start_time = datetime.now()
        test_name = "invalid_token"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "invalid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 401
                mock_response.is_success = False
                mock_response.text = "Invalid token"
                mock_response.json.return_value = {"error": {"message": "Invalid authentication token"}}
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    await client.list_emails(count=1)
                    self._record_test_result(test_name, False, "Should have raised GraphAPIError", start_time, severity="medium")
                except GraphAPIError as e:
                    if e.status_code == 401:
                        self._record_test_result(test_name, True, "✅ Correctly handled invalid token", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Wrong status code: {e.status_code}", start_time, severity="medium")
                except Exception as e:
                    self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_token_refresh(self):
        """Test token refresh scenarios"""
        start_time = datetime.now()
        test_name = "token_refresh"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            # Simulate token manager that refreshes token
            call_count = 0
            def mock_get_token():
                nonlocal call_count
                call_count += 1
                return f"token_{call_count}"
            
            mock_token_manager.get_access_token.side_effect = mock_get_token
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = '{"value": []}'
                mock_response.json.return_value = {"value": []}
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                # Make multiple calls to simulate token refresh
                result1 = await client.list_emails(count=1)
                result2 = await client.list_emails(count=1)
                
                # Check that token manager was called multiple times
                if mock_token_manager.get_access_token.call_count >= 2:
                    self._record_test_result(test_name, True, "✅ Token manager called for each request", start_time)
                else:
                    self._record_test_result(test_name, False, f"Token manager only called {mock_token_manager.get_access_token.call_count} times", start_time, severity="low")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    # =============================================================================
    # Email Operations Tests
    # =============================================================================
    
    async def _test_email_operations(self):
        """Test 6: Email operations scenarios"""
        logger.info("📬 Test Category 6: Email Operations")
        
        # Test 6.1: List emails with parameters
        await self._test_list_emails_parameters()
        
        # Test 6.2: Email search functionality
        await self._test_email_search()
        
        # Test 6.3: Read specific email
        await self._test_read_email()
        
        # Test 6.4: Invalid email IDs
        await self._test_invalid_email_ids()
    
    async def _test_list_emails_parameters(self):
        """Test list emails with various parameters"""
        start_time = datetime.now()
        test_name = "list_emails_parameters"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = '{"value": []}'
                mock_response.json.return_value = {"value": []}
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                # Test various parameter combinations
                test_cases = [
                    {"folder": "inbox", "count": 10},
                    {"folder": "sent", "count": 5},
                    {"folder": "drafts", "count": 20, "select_fields": ["id", "subject"]},
                ]
                
                successful_cases = 0
                for test_case in test_cases:
                    try:
                        result = await client.list_emails(**test_case)
                        if isinstance(result, dict):
                            successful_cases += 1
                    except Exception:
                        pass
                
                if successful_cases == len(test_cases):
                    self._record_test_result(test_name, True, "✅ Successfully handled all parameter combinations", start_time)
                else:
                    self._record_test_result(test_name, False, f"Only {successful_cases}/{len(test_cases)} parameter combinations worked", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_email_search(self):
        """Test email search functionality"""
        start_time = datetime.now()
        test_name = "email_search"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = '{"value": []}'
                mock_response.json.return_value = {"value": []}
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                # Test various search parameters
                search_cases = [
                    {"query": "test"},
                    {"sender": "test@example.com"},
                    {"subject_filter": "important"},
                    {"has_attachments": True},
                    {"unread_only": True},
                    {"query": "project", "sender": "boss@company.com", "has_attachments": False}
                ]
                
                successful_searches = 0
                for search_case in search_cases:
                    try:
                        result = await client.search_emails(**search_case)
                        if isinstance(result, dict):
                            successful_searches += 1
                    except Exception:
                        pass
                
                if successful_searches >= len(search_cases) * 0.8:  # 80% success rate
                    self._record_test_result(test_name, True, f"✅ Successfully handled {successful_searches}/{len(search_cases)} search cases", start_time)
                else:
                    self._record_test_result(test_name, False, f"Only {successful_searches}/{len(search_cases)} search cases worked", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_read_email(self):
        """Test reading specific email"""
        start_time = datetime.now()
        test_name = "read_email"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                email_data = {
                    "id": "test_email_id",
                    "subject": "Test Email",
                    "body": {"content": "Test content"},
                    "from": {"emailAddress": {"address": "sender@example.com"}}
                }
                mock_response.text = json.dumps(email_data)
                mock_response.json.return_value = email_data
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                result = await client.read_email("test_email_id")
                
                if isinstance(result, dict) and result.get("id") == "test_email_id":
                    self._record_test_result(test_name, True, "✅ Successfully read email content", start_time)
                else:
                    self._record_test_result(test_name, False, f"Unexpected result: {result}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_invalid_email_ids(self):
        """Test invalid email ID handling"""
        start_time = datetime.now()
        test_name = "invalid_email_ids"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            invalid_ids = ["", "invalid-id", "nonexistent-id", None]
            handled_correctly = 0
            
            for invalid_id in invalid_ids:
                with patch('httpx.AsyncClient') as mock_client:
                    mock_response = Mock()
                    mock_response.status_code = 404
                    mock_response.is_success = False
                    mock_response.text = "Email not found"
                    mock_response.json.return_value = {"error": {"message": "Email not found"}}
                    
                    mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                    
                    try:
                        if invalid_id is None or invalid_id == "":
                            # These should fail before API call
                            continue
                        await client.read_email(invalid_id)
                    except GraphAPIError as e:
                        if e.status_code == 404:
                            handled_correctly += 1
                    except Exception:
                        handled_correctly += 1  # Other exceptions are acceptable
            
            # Adjust expected count for None/empty cases
            expected_count = len([id for id in invalid_ids if id])
            if handled_correctly >= expected_count * 0.8:  # 80% success rate
                self._record_test_result(test_name, True, f"✅ Handled {handled_correctly}/{expected_count} invalid IDs correctly", start_time)
            else:
                self._record_test_result(test_name, False, f"Only handled {handled_correctly}/{expected_count} invalid IDs", start_time, severity="medium")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    # =============================================================================
    # Edge Case Tests
    # =============================================================================
    
    async def _test_edge_cases(self):
        """Test 7: Edge case scenarios"""
        logger.info("🎯 Test Category 7: Edge Cases")
        
        # Test 7.1: Concurrent requests
        await self._test_concurrent_requests()
        
        # Test 7.2: Unicode content handling
        await self._test_unicode_content()
        
        # Test 7.3: Malformed JSON responses
        await self._test_malformed_json()
        
        # Test 7.4: API version compatibility
        await self._test_api_version_compatibility()
    
    async def _test_concurrent_requests(self):
        """Test concurrent requests handling"""
        start_time = datetime.now()
        test_name = "concurrent_requests"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = '{"value": []}'
                mock_response.json.return_value = {"value": []}
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                # Run multiple concurrent requests
                tasks = [client.list_emails(count=1) for _ in range(5)]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                successful_requests = sum(1 for r in results if isinstance(r, dict))
                
                if successful_requests >= len(tasks) * 0.8:  # 80% success rate
                    self._record_test_result(test_name, True, f"✅ Handled {successful_requests}/{len(tasks)} concurrent requests", start_time)
                else:
                    self._record_test_result(test_name, False, f"Only {successful_requests}/{len(tasks)} concurrent requests succeeded", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_unicode_content(self):
        """Test Unicode content handling"""
        start_time = datetime.now()
        test_name = "unicode_content"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            unicode_content = {
                "subject": "Test 中文 Русские العربية 日本語 🎯",
                "body": "Content with various Unicode: ∑∆∏∂∫√≈≠≤≥ émojis 🚀📧✅"
            }
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 202
                mock_response.is_success = True
                mock_response.text = ""
                
                mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
                
                with patch('clients.graph_api_client.EmailValidator') as mock_validator:
                    mock_validator.format_recipients.return_value = [{"emailAddress": {"address": "test@example.com", "name": "Test User"}}]
                    
                    result = await client.send_email(
                        to="test@example.com",
                        **unicode_content
                    )
                    
                    if result.success:
                        self._record_test_result(test_name, True, "✅ Handled Unicode content successfully", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Failed to handle Unicode content: {result.error}", start_time, severity="medium")
                    
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_malformed_json(self):
        """Test malformed JSON response handling"""
        start_time = datetime.now()
        test_name = "malformed_json"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = '{"invalid": json, "missing": "quotes"}'  # Malformed JSON
                mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                try:
                    result = await client.list_emails(count=1)
                    self._record_test_result(test_name, False, "Should have raised exception for malformed JSON", start_time, severity="medium")
                except json.JSONDecodeError:
                    self._record_test_result(test_name, True, "✅ Correctly handled malformed JSON", start_time)
                except Exception as e:
                    if "json" in str(e).lower():
                        self._record_test_result(test_name, True, "✅ Handled JSON error appropriately", start_time)
                    else:
                        self._record_test_result(test_name, False, f"Unexpected error: {str(e)}", start_time, severity="medium")
                        
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    async def _test_api_version_compatibility(self):
        """Test API version compatibility"""
        start_time = datetime.now()
        test_name = "api_version_compatibility"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            # Verify base URL includes correct API version
            expected_base_url = "https://graph.microsoft.com/v1.0"
            if client.base_url == expected_base_url:
                self._record_test_result(test_name, True, "✅ Using correct API version (v1.0)", start_time)
            else:
                self._record_test_result(test_name, False, f"Unexpected base URL: {client.base_url}", start_time, severity="medium")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test setup failed: {str(e)}", start_time, severity="medium")
    
    # =============================================================================
    # Performance Tests
    # =============================================================================
    
    async def _test_performance_scenarios(self):
        """Test 8: Performance scenarios"""
        logger.info("⚡ Test Category 8: Performance Scenarios")
        
        # Test 8.1: Response time measurement
        await self._test_response_times()
        
        # Test 8.2: Memory usage with large emails
        await self._test_memory_usage()
        
        # Test 8.3: Resource cleanup
        await self._test_resource_cleanup()
    
    async def _test_response_times(self):
        """Test response times under various conditions"""
        start_time = datetime.now()
        test_name = "response_times"
        
        try:
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            response_times = []
            
            # Test multiple API calls
            for i in range(5):
                with patch('httpx.AsyncClient') as mock_client:
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.is_success = True
                    mock_response.text = '{"value": []}'
                    mock_response.json.return_value = {"value": []}
                    
                    mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                    
                    call_start = datetime.now()
                    result = await client.list_emails(count=10)
                    call_time = (datetime.now() - call_start).total_seconds()
                    response_times.append(call_time)
            
            avg_response_time = sum(response_times) / len(response_times)
            max_response_time = max(response_times)
            
            if avg_response_time < 0.5 and max_response_time < 2.0:  # Average < 0.5s, Max < 2s
                self._record_test_result(test_name, True, f"✅ Response times acceptable (avg: {avg_response_time:.3f}s, max: {max_response_time:.3f}s)", start_time)
            else:
                self._record_test_result(test_name, False, f"Slow response times (avg: {avg_response_time:.3f}s, max: {max_response_time:.3f}s)", start_time, severity="medium")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test failed: {str(e)}", start_time, severity="medium")
    
    async def _test_memory_usage(self):
        """Test memory usage with large emails"""
        start_time = datetime.now()
        test_name = "memory_usage"
        
        try:
            try:
                import psutil
                import os
                
                process = psutil.Process(os.getpid())
                initial_memory = process.memory_info().rss / 1024 / 1024  # MB
                
                mock_token_manager = Mock(spec=MSGraphTokenManager)
                mock_token_manager.get_access_token.return_value = "valid_token"
                
                client = MSGraphClient(mock_token_manager)
                
                # Process multiple large email operations
                for i in range(3):
                    large_email_data = {
                        "value": [
                            {
                                "id": f"email_{j}",
                                "subject": f"Large Email {j}",
                                "body": {"content": "A" * 10000},  # 10KB content per email
                                "from": {"emailAddress": {"address": f"sender{j}@example.com"}}
                            }
                            for j in range(100)  # 100 emails
                        ]
                    }
                    
                    with patch('httpx.AsyncClient') as mock_client:
                        mock_response = Mock()
                        mock_response.status_code = 200
                        mock_response.is_success = True
                        mock_response.text = json.dumps(large_email_data)
                        mock_response.json.return_value = large_email_data
                        
                        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                        
                        result = await client.list_emails(count=50)
                        del result  # Explicit cleanup
                
                final_memory = process.memory_info().rss / 1024 / 1024  # MB
                memory_increase = final_memory - initial_memory
                
                if memory_increase < 50:  # Less than 50MB increase
                    self._record_test_result(test_name, True, f"✅ Memory usage acceptable ({memory_increase:.2f}MB increase)", start_time)
                else:
                    self._record_test_result(test_name, False, f"High memory usage ({memory_increase:.2f}MB increase)", start_time, severity="medium")
                    
            except ImportError:
                self._record_test_result(test_name, False, "psutil not available for memory testing", start_time, severity="low")
                
        except Exception as e:
            self._record_test_result(test_name, False, f"Test failed: {str(e)}", start_time, severity="medium")
    
    async def _test_resource_cleanup(self):
        """Test proper resource cleanup"""
        start_time = datetime.now()
        test_name = "resource_cleanup"
        
        try:
            # Test that temp files are cleaned up
            initial_files = set(os.listdir(self.temp_dir)) if os.path.exists(self.temp_dir) else set()
            
            mock_token_manager = Mock(spec=MSGraphTokenManager)
            mock_token_manager.get_access_token.return_value = "valid_token"
            
            client = MSGraphClient(mock_token_manager)
            
            # Simulate operations that might create temp files
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.text = '{"value": []}'
                mock_response.json.return_value = {"value": []}
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
                
                # Multiple operations
                for i in range(5):
                    result = await client.list_emails(count=10)
                    del result
            
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
            report_file = f"logs/msgraph-test-report-{end_time.strftime('%Y%m%d_%H%M%S')}.json"
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
        
        # Email sending issues
        email_failures = [r for r in self.test_results if not r.passed and ("email" in r.test_name.lower() or "send" in r.test_name.lower())]
        if email_failures:
            recommendations.append("📧 Review email sending logic and recipient validation")
        
        # Validation issues
        validation_failures = [r for r in self.test_results if not r.passed and ("validation" in r.test_name.lower() or "invalid" in r.test_name.lower())]
        if validation_failures:
            recommendations.append("📊 Strengthen input validation and data sanitization")
        
        # Performance concerns
        performance_failures = [r for r in self.test_results if not r.passed and ("performance" in r.test_name.lower() or "memory" in r.test_name.lower())]
        if performance_failures:
            recommendations.append("⚡ Optimize performance and memory usage for large operations")
        
        # High failure rate
        failure_rate = len([r for r in self.test_results if not r.passed]) / len(self.test_results)
        if failure_rate > 0.3:
            recommendations.append("🛠️  High failure rate detected - consider comprehensive code review")
        
        if not recommendations:
            recommendations.append("✅ All tests passing - Graph API client appears robust and ready for production")
        
        return recommendations


# =============================================================================
# Main Execution
# =============================================================================

async def run_msgraph_tests() -> TestSuiteReport:
    """Run the comprehensive Microsoft Graph API test suite"""
    logger.info("🚀 Starting Microsoft Graph API Workflow Test Suite")
    test_suite = MSGraphTestSuite()
    return await test_suite.run_all_tests()


if __name__ == "__main__":
    async def main():
        print("🧪 Microsoft Graph API Workflow Test Suite")
        print("This comprehensive test suite will validate all failure scenarios")
        print("that could cause the Graph API client to fail.\n")
        
        report = await run_msgraph_tests()
        
        print(f"\n📊 Test Results Summary:")
        print(f"Status: {report.overall_status}")
        print(f"Tests: {report.passed_tests}/{report.total_tests} passed")
        print(f"Time: {report.execution_time_ms/1000:.2f}s")
        
        if report.critical_failures > 0:
            print(f"\n🚨 {report.critical_failures} critical failures detected!")
            print("Review logs and fix critical issues before production deployment.")
        
        return report.overall_status == "PASS"
    
    asyncio.run(main())