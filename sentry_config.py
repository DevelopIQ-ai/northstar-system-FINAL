"""
Centralized Sentry configuration for the Northstar Agent project
Provides enhanced logging, tagging, and error tracking across all components
"""

import os
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration


class SentryOperations:
    """Standard operation types for consistent tagging"""
    HEALTH_CHECK = "health_check"
    BID_REMINDER = "bid_reminder_workflow"
    EMAIL_SEND = "email_send"
    TOKEN_REFRESH = "token_refresh"
    PROJECT_QUERY = "project_query"
    INVITATION_FETCH = "invitation_fetch"
    DATABASE_OPERATION = "database_operation"
    API_REQUEST = "api_request"
    AUTH_FLOW = "auth_flow"


class SentryComponents:
    """Standard component types for consistent tagging"""
    API = "api"
    WORKFLOW = "workflow"
    AUTH = "auth"
    CLIENT = "client"
    DATABASE = "database"
    MIDDLEWARE = "middleware"


class SentrySeverity:
    """Standard severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def init_sentry(component: str = "unknown") -> bool:
    """
    Initialize Sentry with enhanced configuration for development and production
    
    Args:
        component: The component initializing Sentry (api, workflow, client, etc.)
    
    Returns:
        bool: True if Sentry was initialized, False otherwise
    """
    sentry_dsn = os.getenv("SENTRY_DSN")
    if not sentry_dsn:
        return False
    
    # Determine environment
    environment = os.getenv("ENVIRONMENT", "production").lower()
    is_development = environment in ["development", "dev", "local"]
    
    # Enhanced configuration based on environment
    config = {
        "dsn": sentry_dsn,
        "integrations": [
            FastApiIntegration(
                failed_request_status_codes=[400, range(500, 600)]
            ),
            StarletteIntegration(
                failed_request_status_codes=[400, range(500, 600)]
            ),
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.WARNING  # Send warnings and above as events
            ),
            AsyncioIntegration(),  # Better async error tracking
            HttpxIntegration(),   # Track HTTP client requests
        ],
        "environment": environment,
        "release": os.getenv("RELEASE_VERSION", "1.0.0"),
        "send_default_pii": False,
        "attach_stacktrace": True,
        "max_breadcrumbs": 100 if is_development else 50,
        "debug": is_development,
        "before_send": _before_send_filter,
        "traces_sample_rate": 0.2 if is_development else 0.1,
        "profiles_sample_rate": 0.1 if is_development else 0.05,
    }
    
    # Set global tags
    sentry_sdk.init(**config)
    
    # Set component-specific context
    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("component", component)
        scope.set_tag("server_type", "northstar_agent")
        scope.set_context("environment_info", {
            "component": component,
            "python_version": os.sys.version,
            "initialization_time": datetime.utcnow().isoformat()
        })
    
    return True


def _before_send_filter(event: Dict[str, Any], hint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Filter events before sending to Sentry"""
    # Don't send debug level events
    if event.get('level') == 'debug':
        return None
    
    # Filter out noisy errors in development
    if os.getenv("ENVIRONMENT", "production").lower() in ["development", "dev", "local"]:
        # Skip certain connection errors in development
        if event.get('exception'):
            for exception in event['exception'].get('values', []):
                if 'connection' in exception.get('type', '').lower():
                    return None
    
    return event


def set_operation_context(
    operation: str,
    component: str,
    severity: str = SentrySeverity.MEDIUM,
    extra_tags: Optional[Dict[str, str]] = None,
    user_context: Optional[Dict[str, Any]] = None
) -> None:
    """
    Set operation-specific context for Sentry tracking
    
    Args:
        operation: The operation being performed
        component: The component performing the operation
        severity: The severity level of the operation
        extra_tags: Additional tags to set
        user_context: User context information
    """
    with sentry_sdk.configure_scope() as scope:
        # Set operation tags
        scope.set_tag("operation", operation)
        scope.set_tag("component", component)
        scope.set_tag("severity", severity)
        
        # Set additional tags
        if extra_tags:
            for key, value in extra_tags.items():
                scope.set_tag(key, value)
        
        # Set user context if provided
        if user_context:
            scope.set_user(user_context)
        
        # Set operation context
        scope.set_context("operation_info", {
            "operation": operation,
            "component": component,
            "severity": severity,
            "timestamp": datetime.utcnow().isoformat(),
            **(extra_tags or {})
        })


def capture_exception_with_context(
    exception: Exception,
    operation: str,
    component: str,
    severity: str = SentrySeverity.HIGH,
    extra_context: Optional[Dict[str, Any]] = None,
    extra_tags: Optional[Dict[str, str]] = None
) -> str:
    """
    Capture exception with rich context information
    
    Args:
        exception: The exception to capture
        operation: The operation that failed
        component: The component where the error occurred
        severity: The severity of the error
        extra_context: Additional context information
        extra_tags: Additional tags
    
    Returns:
        str: The Sentry event ID
    """
    with sentry_sdk.configure_scope() as scope:
        # Set error-specific context
        set_operation_context(operation, component, severity, extra_tags)
        
        # Add error context
        error_context = {
            "error_type": type(exception).__name__,
            "error_message": str(exception),
            "operation": operation,
            "component": component,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if extra_context:
            error_context.update(extra_context)
        
        scope.set_context("error_details", error_context)
        
        # Capture the exception
        return sentry_sdk.capture_exception(exception)


def capture_message_with_context(
    message: str,
    level: str,
    operation: str,
    component: str,
    extra_context: Optional[Dict[str, Any]] = None,
    extra_tags: Optional[Dict[str, str]] = None
) -> str:
    """
    Capture message with context information
    
    Args:
        message: The message to capture
        level: The log level (info, warning, error)
        operation: The operation context
        component: The component context
        extra_context: Additional context
        extra_tags: Additional tags
    
    Returns:
        str: The Sentry event ID
    """
    with sentry_sdk.configure_scope() as scope:
        # Set message context
        set_operation_context(operation, component, extra_tags=extra_tags)
        
        # Add message context
        message_context = {
            "operation": operation,
            "component": component,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if extra_context:
            message_context.update(extra_context)
        
        scope.set_context("message_details", message_context)
        
        # Capture the message
        return sentry_sdk.capture_message(message, level)


def add_breadcrumb(
    message: str,
    category: str = "custom",
    level: str = "info",
    data: Optional[Dict[str, Any]] = None
) -> None:
    """
    Add a breadcrumb for debugging context
    
    Args:
        message: The breadcrumb message
        category: The category of the breadcrumb
        level: The level of the breadcrumb
        data: Additional data
    """
    sentry_sdk.add_breadcrumb(
        message=message,
        category=category,
        level=level,
        data=data or {},
        timestamp=datetime.utcnow()
    )


def create_transaction(
    name: str,
    operation: str,
    component: str,
    description: Optional[str] = None
):
    """
    Create a Sentry transaction for performance monitoring
    
    Args:
        name: Transaction name
        operation: Operation type
        component: Component performing the operation
        description: Optional description
    
    Returns:
        Sentry transaction object
    """
    transaction = sentry_sdk.start_transaction(
        name=name,
        op=operation,
        description=description
    )
    
    # Set transaction tags
    transaction.set_tag("component", component)
    transaction.set_tag("operation", operation)
    
    return transaction


# Health check specific helpers
def set_health_check_context(test_suite: str, status: str) -> None:
    """Set context for health check operations"""
    set_operation_context(
        operation=SentryOperations.HEALTH_CHECK,
        component=SentryComponents.API,
        severity=SentrySeverity.LOW,
        extra_tags={
            "test_suite": test_suite,
            "health_status": status
        }
    )


# Workflow specific helpers  
def set_workflow_context(node_name: str, project_count: int = 0) -> None:
    """Set context for workflow operations"""
    set_operation_context(
        operation=SentryOperations.BID_REMINDER,
        component=SentryComponents.WORKFLOW,
        severity=SentrySeverity.MEDIUM,
        extra_tags={
            "workflow_node": node_name,
            "project_count": str(project_count)
        }
    )


# API client specific helpers
def set_api_client_context(client_type: str, endpoint: str, method: str = "GET") -> None:
    """Set context for API client operations"""
    set_operation_context(
        operation=SentryOperations.API_REQUEST,
        component=SentryComponents.CLIENT,
        severity=SentrySeverity.MEDIUM,
        extra_tags={
            "client_type": client_type,
            "endpoint": endpoint,
            "http_method": method
        }
    )


# Database specific helpers
def set_database_context(operation_type: str, table: str = "unknown") -> None:
    """Set context for database operations"""
    set_operation_context(
        operation=SentryOperations.DATABASE_OPERATION,
        component=SentryComponents.DATABASE,
        severity=SentrySeverity.MEDIUM,
        extra_tags={
            "db_operation": operation_type,
            "table": table
        }
    )


# Auth specific helpers
def set_auth_context(auth_type: str, flow_stage: str) -> None:
    """Set context for authentication operations"""
    set_operation_context(
        operation=SentryOperations.AUTH_FLOW,
        component=SentryComponents.AUTH,
        severity=SentrySeverity.HIGH,
        extra_tags={
            "auth_type": auth_type,
            "flow_stage": flow_stage
        }
    )