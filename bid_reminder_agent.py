"""
Simple Bid Reminder Agent
Checks BuildingConnected for projects due in 5-10 days and sends reminder emails
"""

import os
import logging
import random
import html
from typing import Optional, List
from datetime import datetime

import sentry_sdk
from sentry_config import (
    init_sentry, set_workflow_context, capture_exception_with_context,
    capture_message_with_context, add_breadcrumb, create_transaction,
    SentryOperations, SentryComponents, SentrySeverity
)

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel
from typing_extensions import TypedDict
from langsmith import traceable

from auth.auth_helpers import (
    create_token_manager_from_env,
    create_buildingconnected_token_manager_from_env,
    MSGraphTokenManager,
    BuildingConnectedTokenManager
)
from clients.graph_api_client import MSGraphClient, EmailImportance
from clients.buildingconnected_client import BuildingConnectedClient, Project, BiddingInvitationData
from email_tracker import EmailTracker

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

# Initialize Sentry with enhanced configuration for workflow component
sentry_initialized = init_sentry(component=SentryComponents.WORKFLOW)
if sentry_initialized:
    logger.info("✅ Sentry initialized for workflow component with enhanced configuration")
else:
    logger.warning("⚠️ Sentry not initialized for workflow - SENTRY_DSN not configured")


class BidReminderState(TypedDict):
    """Simple state for bid reminder workflow"""
    # Authentication
    outlook_token_manager: Optional[MSGraphTokenManager]
    building_token_manager: Optional[BuildingConnectedTokenManager]
    outlook_client: Optional[MSGraphClient]
    building_client: Optional[BuildingConnectedClient]
    
    # Project data
    upcoming_projects: Optional[List[Project]]
    bidding_invitations: Optional[List[BiddingInvitationData]]
    
    # Email data
    reminder_email_sent: bool
    email_tracker: Optional[EmailTracker]
    
    # Test parameters
    test_project_id: Optional[str]
    test_days_out: Optional[int]
    
    # Results
    error_message: Optional[str]
    workflow_successful: bool
    result_message: Optional[str]


class BidReminderAgent:
    """Simple agent that checks for upcoming bids and sends reminder emails"""
    
    def __init__(self, test_project_id: Optional[str] = None, test_days_out: Optional[int] = None):
        self.default_recipient = os.getenv("DEFAULT_EMAIL_RECIPIENT", "kush@developiq.ai")
        self.days_before_bid = [1, 2, 3, 7]
        self.urgency_threshold_days = int(os.getenv("URGENCY_THRESHOLD_DAYS", "5"))  # Days at which messages become urgent
        self.run_start_time = datetime.now()
        
        # Test parameters
        self.test_project_id = test_project_id
        self.test_days_out = test_days_out
        
        logger.info("BidReminderAgent initialized")
        logger.info(f"Default email recipient: {self.default_recipient}")
        logger.info(f"Days before bid to check: {self.days_before_bid}")
        logger.info(f"Urgency threshold: {self.urgency_threshold_days} days")
        if test_project_id:
            logger.info(f"🧪 Test mode - Target project ID: {test_project_id}")
        if test_days_out:
            logger.info(f"🧪 Test mode - Override days out: {test_days_out}")
    
    def _create_run_name(self, project_count: Optional[int] = None, success: bool = True) -> str:
        """Create descriptive run name for LangSmith"""
        if not success:
            return f"🚨 Bid Check Failed - {self.run_start_time.strftime('%H:%M:%S')}"
        
        if project_count is None:
            return f"🔄 Bid Check Running - {self.run_start_time.strftime('%H:%M:%S')}"
        
        if project_count == 0:
            return f"✅ No Upcoming Bids - {self.run_start_time.strftime('%H:%M:%S')}"
        
        return f"📋 {project_count} Project{'s' if project_count != 1 else ''} Due (5-10 days) - {self.run_start_time.strftime('%H:%M:%S')}"
    
    def _create_run_metadata(self, project_count: Optional[int] = None, success: bool = True) -> dict:
        """Create rich metadata for LangSmith tracing"""
        metadata = {
            "agent_version": "1.0.0",
            "environment": os.getenv("ENVIRONMENT", "development"),
            "run_timestamp": self.run_start_time.isoformat(),
            "recipient": self.default_recipient,
            "check_days": self.days_before_bid,
            "success": success
        }
        
        if project_count is not None:
            metadata["projects_found"] = project_count
            
        return metadata
    
    @traceable(name="🔐 Initialize Authentication", tags=["auth", "setup"])
    async def initialize_auth_node(self, state: BidReminderState) -> BidReminderState:
        """Initialize authentication for both Outlook and BuildingConnected"""
        # Set workflow context for this node
        set_workflow_context("initialize_auth")
        
        logger.info("🔐 Starting authentication initialization node")
        
        add_breadcrumb(
            message="Authentication initialization started",
            category="workflow",
            level="info",
            data={"node": "initialize_auth"}
        )
        
        try:
            # Initialize Outlook authentication
            logger.info("Creating Outlook token manager from environment")
            outlook_token_manager = create_token_manager_from_env()
            logger.info("✅ Outlook token manager created successfully")
            
            logger.info("Creating Outlook client with token manager")
            outlook_client = MSGraphClient(outlook_token_manager)
            logger.info("✅ Outlook client created successfully")
            
            # Initialize BuildingConnected authentication
            logger.info("Creating BuildingConnected token manager from environment")
            building_token_manager = create_buildingconnected_token_manager_from_env()
            logger.info("✅ BuildingConnected token manager created successfully")
            
            logger.info("Creating BuildingConnected client with token manager")
            building_client = BuildingConnectedClient(building_token_manager)
            logger.info("✅ BuildingConnected client created successfully")
            
            # Initialize email tracker
            logger.info("Initializing email tracker")
            email_tracker = EmailTracker()
            await email_tracker.create_table_if_not_exists()
            logger.info("✅ Email tracker initialized successfully")
            
            # Verify BuildingConnected auth by testing projects endpoint instead of user info
            logger.info("Testing BuildingConnected authentication by fetching test projects")
            try:
                test_projects = await building_client.get_all_projects(limit=1)
                logger.info(f"✅ BuildingConnected authentication verified - retrieved {len(test_projects)} test projects")
                print(f"✅ BuildingConnected authentication verified - can access projects")
            except Exception as auth_test_error:
                logger.error(f"❌ BuildingConnected authentication test failed: {str(auth_test_error)}")
                raise ValueError(f"BuildingConnected authentication test failed: {str(auth_test_error)}")
            
            logger.info("✅ Authentication node completed successfully")
            return {
                **state,
                "outlook_token_manager": outlook_token_manager,
                "building_token_manager": building_token_manager,
                "outlook_client": outlook_client,
                "building_client": building_client,
                "email_tracker": email_tracker,
                "error_message": None
            }
            
        except Exception as e:
            logger.error(f"❌ Authentication initialization failed: {str(e)}")
            
            # Capture authentication failure
            capture_exception_with_context(
                e,
                operation=SentryOperations.AUTH_FLOW,
                component=SentryComponents.WORKFLOW,
                severity=SentrySeverity.CRITICAL,
                extra_context={
                    "node": "initialize_auth",
                    "stage": "initialization"
                }
            )
            
            return {
                **state,
                "outlook_token_manager": None,
                "building_token_manager": None,
                "outlook_client": None,
                "building_client": None,
                "email_tracker": None,
                "error_message": f"Authentication failed: {str(e)}",
                "workflow_successful": False,
                "upcoming_projects": None,
                "bidding_invitations": None,
                "reminder_email_sent": False
            }
    
    @traceable(name="📋 Check Upcoming Projects", tags=["projects", "data-fetch"])
    async def check_upcoming_projects_node(self, state: BidReminderState) -> BidReminderState:
        """Check BuildingConnected for projects due in 5-10 days or specific project"""
        # Set workflow context for this node
        set_workflow_context("check_upcoming_projects")
        
        test_project_id = state.get("test_project_id")
        test_days_out = state.get("test_days_out")
        
        logger.info("📋 Starting project check node")
        if test_project_id:
            logger.info(f"🧪 Test mode - Targeting specific project: {test_project_id}")
        
        add_breadcrumb(
            message="Project check started",
            category="workflow", 
            level="info",
            data={
                "node": "check_upcoming_projects", 
                "days_to_check": self.days_before_bid,
                "test_project_id": test_project_id,
                "test_days_out": test_days_out
            }
        )
        
        if state.get("error_message"):
            logger.warning("Skipping project check due to previous error")
            return state
        
        building_client = state["building_client"]
        if not building_client:
            logger.error("❌ BuildingConnected client not initialized")
            return {
                **state,
                "error_message": "BuildingConnected client not initialized",
                "workflow_successful": False
            }
        
        try:
            if test_project_id:
                # Test mode: Get specific project by ID
                logger.info(f"🧪 Test mode - Fetching specific project: {test_project_id}")
                try:
                    # Get the specific project (we'll need to fetch all projects and filter)
                    # Since BuildingConnected doesn't have a get-by-ID endpoint, we fetch recent projects
                    all_projects_response = await building_client.get_all_projects(limit=100)
                    target_project = None
                    
                    for project in all_projects_response:
                        if project.id == test_project_id:
                            target_project = project
                            break
                    
                    if target_project:
                        logger.info(f"✅ Found target project: {target_project.name}")
                        unique_projects = [target_project]
                    else:
                        logger.error(f"❌ Project not found: {test_project_id}")
                        return {
                            **state,
                            "upcoming_projects": [],
                            "error_message": f"Project not found: {test_project_id}",
                            "workflow_successful": False
                        }
                except Exception as e:
                    logger.error(f"❌ Failed to fetch specific project {test_project_id}: {str(e)}")
                    return {
                        **state,
                        "upcoming_projects": [],
                        "error_message": f"Failed to fetch project {test_project_id}: {str(e)}",
                        "workflow_successful": False
                    }
            else:
                # Normal mode: Get projects due in specified days
                logger.info(f"Checking projects due in {self.days_before_bid} days")
                all_upcoming_projects = []
                
                for days in self.days_before_bid:
                    logger.info(f"Fetching projects due in {days} days")
                    projects_response = await building_client.get_projects_due_in_n_days(days)
                    projects_count = len(projects_response.projects)
                    logger.info(f"Found {projects_count} projects due in {days} days")
                    all_upcoming_projects.extend(projects_response.projects)
                    
                logger.info(f"Total projects found across all days: {len(all_upcoming_projects)}")
                    
                # Remove duplicates (same project might appear in multiple days)
                logger.info("Removing duplicate projects")
                unique_projects = []
                seen_project_ids = set()
                for project in all_upcoming_projects:
                    if project.id not in seen_project_ids:
                        unique_projects.append(project)
                        seen_project_ids.add(project.id)
                        logger.debug(f"Added project: {project.name} (ID: {project.id})")
                    else:
                        logger.debug(f"Skipped duplicate project: {project.name} (ID: {project.id})")
            
            logger.info(f"✅ Project check completed: {len(unique_projects)} unique projects found")
            
            # Update workflow context with project count
            set_workflow_context("check_upcoming_projects", len(unique_projects))
            
            # Log project details
            for project in unique_projects:
                logger.info(f"  - {project.name} | Due: {project.bidsDueAt} | State: {project.state}")
            
            add_breadcrumb(
                message="Projects found and processed",
                category="workflow",
                level="info",
                data={
                    "node": "check_upcoming_projects",
                    "projects_found": len(unique_projects),
                    "unique_projects": len(unique_projects),
                    "test_mode": bool(test_project_id)
                }
            )
            
            return {
                **state,
                "upcoming_projects": unique_projects,
                "error_message": None
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to check projects: {str(e)}")
            
            # Capture project check failure
            capture_exception_with_context(
                e,
                operation=SentryOperations.PROJECT_QUERY,
                component=SentryComponents.WORKFLOW,
                severity=SentrySeverity.HIGH,
                extra_context={
                    "node": "check_upcoming_projects",
                    "days_to_check": self.days_before_bid
                }
            )
            
            return {
                **state,
                "upcoming_projects": None,
                "error_message": f"Failed to check projects: {str(e)}",
                "workflow_successful": False
            }
    
    async def get_bidding_invitations_node(self, state: BidReminderState) -> BidReminderState:
        """Get bidding invitations for each upcoming project"""
        # Set workflow context for this node  
        upcoming_projects = state.get("upcoming_projects", [])
        project_count = len(upcoming_projects) if upcoming_projects else 0
        set_workflow_context("get_bidding_invitations", project_count)
        
        logger.info("📧 Starting bidding invitations check node")
        
        add_breadcrumb(
            message="Bidding invitations check started",
            category="workflow",
            level="info",
            data={"node": "get_bidding_invitations", "projects_to_process": project_count}
        )
        
        if state.get("error_message"):
            logger.warning("Skipping bidding invitations check due to previous error")
            return state
        
        building_client = state["building_client"]
        upcoming_projects = state.get("upcoming_projects", [])
        
        if not building_client:
            logger.error("❌ BuildingConnected client not initialized")
            return {
                **state,
                "error_message": "BuildingConnected client not initialized",
                "workflow_successful": False
            }
        
        if not upcoming_projects:
            logger.info("No upcoming projects found, skipping bidding invitations check")
            return {
                **state,
                "bidding_invitations": [],
                "error_message": None
            }
        
        try:
            all_bidding_invitations = []
            
            logger.info(f"Getting bidding invitations for {len(upcoming_projects)} projects")
            
            for project in upcoming_projects:
                logger.info(f"🎯 Getting bidding invitations for project: {project.name} (ID: {project.id})")
                
                try:
                    # Call the get_bidding_invitations method with the project ID
                    project_invitations = await building_client.get_bidding_invitations(project.id)
                    logger.info(f"✅ Found {len(project_invitations)} bidding invitations for project {project.name}")
                    
                    # Add project invitations to the overall list
                    all_bidding_invitations.extend(project_invitations)
                    
                    # Log some details about the invitations
                    for invitation in project_invitations:
                        logger.debug(f"  - Invitation: {invitation.firstName} {invitation.lastName} ({invitation.email}) - {invitation.bidPackageName}")
                    
                except Exception as project_error:
                    logger.error(f"❌ Failed to get invitations for project {project.name} (ID: {project.id}): {str(project_error)}")
                    # Continue with other projects even if one fails
                    continue
            
            logger.info(f"✅ Bidding invitations check completed: {len(all_bidding_invitations)} total invitations found")
            
            add_breadcrumb(
                message="Bidding invitations retrieved",
                category="workflow",
                level="info",
                data={
                    "node": "get_bidding_invitations",
                    "invitations_found": len(all_bidding_invitations),
                    "projects_processed": len(upcoming_projects)
                }
            )
            
            return {
                **state,
                "bidding_invitations": all_bidding_invitations,
                "error_message": None
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to get bidding invitations: {str(e)}")
            
            # Capture invitation fetch failure
            capture_exception_with_context(
                e,
                operation=SentryOperations.INVITATION_FETCH,
                component=SentryComponents.WORKFLOW,
                severity=SentrySeverity.HIGH,
                extra_context={
                    "node": "get_bidding_invitations",
                    "projects_count": len(upcoming_projects) if upcoming_projects else 0
                }
            )
            
            return {
                **state,
                "bidding_invitations": None,
                "error_message": f"Failed to get bidding invitations: {str(e)}",
                "workflow_successful": False
            }
    
    @traceable(name="📧 Send Invitation Emails", tags=["email", "invitations"])
    async def send_reminder_email_node(self, state: BidReminderState) -> BidReminderState:
        """Send personalized emails to each bidding invitation"""
        # Set workflow context for this node
        bidding_invitations = state.get("bidding_invitations", [])
        invitation_count = len(bidding_invitations) if bidding_invitations else 0
        set_workflow_context("send_reminder_email", invitation_count)
        
        logger.info("📧 Starting email sending node")
        
        add_breadcrumb(
            message="Email sending started",
            category="workflow",
            level="info",
            data={"node": "send_reminder_email", "emails_to_send": invitation_count}
        )
        
        if state.get("error_message"):
            logger.warning("Skipping email sending due to previous error")
            return {
                **state,
                "reminder_email_sent": False,
                "workflow_successful": False
            }
        
        outlook_client = state["outlook_client"]
        bidding_invitations = state.get("bidding_invitations", [])
        upcoming_projects = state.get("upcoming_projects", [])
        email_tracker = state.get("email_tracker")
        
        if not outlook_client:
            logger.error("❌ Outlook client not initialized")
            return {
                **state,
                "error_message": "Outlook client not initialized",
                "reminder_email_sent": False,
                "workflow_successful": False
            }
        
        try:
            if not bidding_invitations:
                logger.info("No bidding invitations found, no emails to send")
                return {
                    **state,
                    "reminder_email_sent": False,
                    "error_message": None
                }
            
            # Create project lookup for invitation context
            project_lookup = {project.id: project for project in upcoming_projects}
            
            logger.info(f"Sending personalized emails to {len(bidding_invitations)} invitations")
            
            emails_sent = 0
            failed_emails = []
            
            for invitation in bidding_invitations:
                try:
                    logger.info(f"Sending email to {invitation.firstName} {invitation.lastName} ({invitation.email})")
                    
                    # Find the associated project
                    project = project_lookup.get(invitation.projectId)
                    
                    # Determine project name for subject line
                    project_name = project.name if project else invitation.bidPackageName
                    
                    # Calculate days until due for subject line (with override support)
                    test_days_out = state.get("test_days_out")
                    days_until_due = self._calculate_days_until_due(project, test_days_out)
                    
                    # Skip if not in allowed days (unless testing with override)
                    if test_days_out is None and days_until_due not in [1, 2, 3, 7]:
                        logger.info(f"⏭️  Skipping {invitation.email} - project due in {days_until_due} days (not in allowed list)")
                        continue
                    
                    # Create personalized email with timeline-based subject line
                    email_subject = await self._get_subject_line(invitation.bidPackageName, project_name, days_until_due, invitation, project, email_tracker)
                    email_body = self._create_personalized_invitation_email(invitation, project, test_days_out)
                    
                    # Send email
                    send_response = await outlook_client.send_email(
                        to=invitation.email,
                        subject=email_subject,
                        body=email_body,
                        importance=EmailImportance.HIGH
                    )
                    
                    # Log email attempt to database
                    if email_tracker:
                        try:
                            if send_response.success:
                                await email_tracker.log_email_attempt(invitation, project, "SUCCESS")
                                emails_sent += 1
                                logger.info(f"✅ Email sent successfully to {invitation.email}")
                            else:
                                await email_tracker.log_email_attempt(invitation, project, "FAILED")
                                failed_emails.append(f"{invitation.email}: {send_response.error}")
                                logger.error(f"❌ Failed to send email to {invitation.email}: {send_response.error}")
                        except Exception as db_error:
                            logger.error(f"❌ Failed to log email attempt to database: {str(db_error)}")
                            # Continue with original logic if database logging fails
                            if send_response.success:
                                emails_sent += 1
                                logger.info(f"✅ Email sent successfully to {invitation.email}")
                            else:
                                failed_emails.append(f"{invitation.email}: {send_response.error}")
                                logger.error(f"❌ Failed to send email to {invitation.email}: {send_response.error}")
                    else:
                        # Fallback if email tracker not available
                        if send_response.success:
                            emails_sent += 1
                            logger.info(f"✅ Email sent successfully to {invitation.email}")
                        else:
                            failed_emails.append(f"{invitation.email}: {send_response.error}")
                            logger.error(f"❌ Failed to send email to {invitation.email}: {send_response.error}")
                        
                except Exception as email_error:
                    failed_emails.append(f"{invitation.email}: {str(email_error)}")
                    logger.error(f"❌ Failed to send email to {invitation.email}: {str(email_error)}")
                    
                    # Log failed attempt to database if possible
                    if email_tracker:
                        try:
                            await email_tracker.log_email_attempt(invitation, project_lookup.get(invitation.projectId), "FAILED")
                        except Exception as db_error:
                            logger.error(f"❌ Failed to log failed email attempt to database: {str(db_error)}")
            
            # Determine overall success
            if emails_sent > 0:
                success_message = f"✅ Successfully sent {emails_sent} invitation emails"
                if failed_emails:
                    success_message += f", {len(failed_emails)} failed"
                logger.info(success_message)
                
                add_breadcrumb(
                    message="Emails sent successfully",
                    category="workflow",
                    level="info",
                    data={
                        "node": "send_reminder_email",
                        "emails_sent": emails_sent,
                        "emails_failed": len(failed_emails)
                    }
                )
                
                return {
                    **state,
                    "reminder_email_sent": True,
                    "workflow_successful": True,
                    "error_message": None
                }
            else:
                error_message = f"Failed to send any emails. Errors: {'; '.join(failed_emails[:3])}"
                logger.error(error_message)
                
                # Capture email sending failure
                capture_message_with_context(
                    "All email sends failed",
                    "error",
                    operation=SentryOperations.EMAIL_SEND,
                    component=SentryComponents.WORKFLOW,
                    extra_context={
                        "node": "send_reminder_email",
                        "failed_emails": failed_emails[:5],  # First 5 errors
                        "total_attempts": len(bidding_invitations)
                    }
                )
                
                return {
                    **state,
                    "reminder_email_sent": False,
                    "workflow_successful": False,
                    "error_message": error_message
                }
                
        except Exception as e:
            logger.error(f"❌ Email sending process failed: {str(e)}")
            
            # Capture email process failure
            capture_exception_with_context(
                e,
                operation=SentryOperations.EMAIL_SEND,
                component=SentryComponents.WORKFLOW,
                severity=SentrySeverity.CRITICAL,
                extra_context={
                    "node": "send_reminder_email",
                    "invitations_count": len(bidding_invitations) if bidding_invitations else 0
                }
            )
            
            return {
                **state,
                "reminder_email_sent": False,
                "workflow_successful": False,
                "error_message": f"Email sending failed: {str(e)}"
            }
    
    @traceable(name="🏁 Finalize Results", tags=["finalize", "summary"])
    async def finalize_result_node(self, state: BidReminderState) -> BidReminderState:
        """Finalize the workflow result - showing project data, bidding invitations, and email status"""
        # Set workflow context for finalization
        upcoming_projects = state.get("upcoming_projects", [])
        bidding_invitations = state.get("bidding_invitations", [])
        project_count = len(upcoming_projects) if upcoming_projects else 0
        invitation_count = len(bidding_invitations) if bidding_invitations else 0
        
        set_workflow_context("finalize_result", project_count)
        
        logger.info("🏁 Starting finalize result node")
        
        add_breadcrumb(
            message="Workflow finalization started",
            category="workflow",
            level="info",
            data={
                "node": "finalize_result",
                "projects_found": project_count,
                "invitations_found": invitation_count
            }
        )
        
        upcoming_projects = state.get("upcoming_projects", [])
        bidding_invitations = state.get("bidding_invitations", [])
        reminder_email_sent = state.get("reminder_email_sent", False)
        error_message = state.get("error_message")
        
        logger.info(f"Projects found: {len(upcoming_projects) if upcoming_projects else 0}")
        logger.info(f"Bidding invitations found: {len(bidding_invitations) if bidding_invitations else 0}")
        logger.info(f"Emails sent: {reminder_email_sent}")
        
        # Only iterate if bidding_invitations is not None
        if bidding_invitations:
            for invitation in bidding_invitations:
                logger.info(f"  - {invitation.firstName} {invitation.lastName} ({invitation.email}) - {invitation.bidPackageName}")
                logger.info(f"  - {invitation.linkToBid}\n\n")
        else:
            logger.info("  - No bidding invitations to display")
            
        logger.info(f"Error message: {error_message if error_message else 'None'}")
        
        if error_message:
            # Provide clear messaging for authentication failures
            if "Authentication failed" in error_message or "authentication" in error_message.lower():
                result_message = f"❌ Workflow stopped: Authentication failed. Please run 'python auth/setup_bid_reminder.py' to reconfigure authentication. Error: {error_message}"
            else:
                result_message = f"❌ Workflow failed: {error_message}"
            workflow_successful = False
            logger.error(f"Workflow failed with error: {error_message}")
        else:
            project_count = len(upcoming_projects) if upcoming_projects else 0
            invitation_count = len(bidding_invitations) if bidding_invitations else 0
            email_status = "✅ Emails sent successfully" if reminder_email_sent else "⚠️ No emails sent (no invitations found)"
            
            result_message = (
                f"✅ Bid reminder workflow completed successfully!\n"
                f"📋 Found {project_count} projects due in 5-10 days\n"
                f"📧 Found {invitation_count} bidding invitations across all projects\n"
                f"💌 {email_status}"
            )
            workflow_successful = True
            logger.info(f"✅ Workflow completed successfully with {project_count} projects, {invitation_count} invitations, emails sent: {reminder_email_sent}")
        
        logger.info("🏁 Finalize result node completed")
        
        # Final workflow status for Sentry
        final_status = "success" if workflow_successful else "failed"
        
        add_breadcrumb(
            message="Workflow finalized",
            category="workflow",
            level="info" if workflow_successful else "error",
            data={
                "node": "finalize_result",
                "workflow_status": final_status,
                "projects_found": project_count,
                "invitations_found": invitation_count,
                "emails_sent": reminder_email_sent
            }
        )
        
        # Capture workflow completion message
        if not workflow_successful and error_message:
            capture_message_with_context(
                f"Workflow completed with errors: {error_message}",
                "warning",
                operation=SentryOperations.BID_REMINDER,
                component=SentryComponents.WORKFLOW,
                extra_context={
                    "node": "finalize_result",
                    "final_status": final_status
                }
            )
        
        return {
            **state,
            "result_message": result_message,
            "workflow_successful": workflow_successful
        }
    
    @traceable(name="🔄 Prepare Next Run", tags=["token-refresh", "proactive"])
    async def prepare_next_run_node(self, state: BidReminderState) -> BidReminderState:
        """Proactively refresh BuildingConnected token for next run"""
        logger.info("🔄 Starting proactive token refresh for next run")
        
        # Always attempt token refresh, regardless of workflow success
        # This is critical for Autodesk's use-once refresh token policy
        
        building_token_manager = state.get("building_token_manager")
        
        # If we don't have a token manager (due to auth failure), try to create one
        if not building_token_manager:
            logger.info("🔧 No BuildingConnected token manager in state, attempting to create fresh one")
            try:
                from auth.auth_helpers import BuildingConnectedTokenManager
                building_token_manager = BuildingConnectedTokenManager(
                    client_id=os.getenv("AUTODESK_CLIENT_ID"),
                    client_secret=os.getenv("AUTODESK_CLIENT_SECRET"),
                    encrypted_refresh_token=os.getenv("AUTODESK_ENCRYPTED_REFRESH_TOKEN")
                )
                logger.info("✅ Fresh BuildingConnected token manager created for proactive refresh")
            except Exception as e:
                logger.warning(f"⚠️ Could not create fresh token manager: {str(e)}")
                return state
        
        try:
            logger.info("🔑 Proactively refreshing BuildingConnected token for next run")
            logger.info("   This is critical due to Autodesk's use-once refresh token policy")
            
            # Force a token refresh by clearing the cached token
            building_token_manager._cached_token = None
            
            # Get a fresh access token (this will refresh and rotate the refresh token)
            fresh_token = await building_token_manager.get_access_token()
            
            if fresh_token and len(fresh_token) > 50:
                logger.info("✅ Proactive token refresh successful - next run will have fresh tokens")
                logger.info(f"   New token expires at: {datetime.fromtimestamp(building_token_manager._cached_token.expires_at/1000) if building_token_manager._cached_token else 'Unknown'}")
                logger.info("   📝 New refresh token should be saved to .env file automatically")
            else:
                logger.warning("⚠️ Proactive token refresh returned invalid token")
                
        except Exception as e:
            # Don't fail the workflow if proactive refresh fails, but log details
            logger.warning(f"⚠️ Proactive token refresh failed: {str(e)}")
            
            # If this is an invalid_grant error, provide guidance
            if "invalid_grant" in str(e).lower():
                logger.warning("   This suggests the refresh token is already expired")
                logger.warning("   🔧 Solution: Run fresh OAuth flow with:")
                logger.warning("   python -c \"import asyncio; from auth.oauth_setup import setup_autodesk_auth_flow; asyncio.run(setup_autodesk_auth_flow())\"")
            else:
                logger.info("   Next run may need to handle token refresh")
        
        logger.info("🔄 Prepare next run node completed")
        return state
    
    def _get_greeting(self, first_name: str) -> str:
        """Get a random greeting variation based on specific day values"""
        # Handle empty or missing first names
        name_part = first_name if first_name and first_name.strip() else ""
        
        if name_part:
            greetings = [
                f"Hello {name_part},",
                f"Hi {name_part},",
                f"Good morning {name_part},",
                f"Hey {name_part},"
            ]
        else:
            greetings = [
                "Hello there,",
                "Hi there,",
                "Good morning,"
            ]
        return random.choice(greetings)
    
    def _get_intro(self, project_name: str, bid_package_name: str, days_until_due: int) -> str:
        """Get a random intro variation based on specific day values"""
        
        if days_until_due == 1:  # 1 day
            intros = [
                f"Just reaching out as a final notice for our project, {project_name}, for the {bid_package_name} bid package.",
                f"This is a reminder of your last chance to bid on our project, {project_name}, for the {bid_package_name} bid package.",
                f"This is a final notice for our project, {project_name}, for the {bid_package_name} bid package.",
                f"I wanted to give you one last opportunity to bid on {project_name} for the {bid_package_name} work.",
            ]
        elif days_until_due == 2:  # 2 days
            intros = [
                f"Following up on our urgent bid opportunity for {project_name}, for the {bid_package_name} bid package.",
                f"This is a time-sensitive bid request for our project, {project_name}, for the {bid_package_name} bid package.",
                f"Reaching out about a last-minute opportunity for {project_name}, for the {bid_package_name} bid package.",
                f"I wanted to follow up about the {bid_package_name} work on our {project_name} project.",
            ]
        elif days_until_due == 3:  # 3 days
            intros = [
                f"This is a quick turnaround bid opportunity for our project, {project_name}, for the {bid_package_name} bid package.",
                f"Following up on a time-sensitive bid request for {project_name}, specifically for the {bid_package_name} package.",
                f"This is a last-minute opportunity for our project, {project_name}, for the {bid_package_name} bid package.",
                f"I wanted to reach out again about the {bid_package_name} work on {project_name}.",
            ]
        elif days_until_due == 7:  # 7 days
            intros = [
                f"I wanted to personally invite you to bid on our project, {project_name}, for the {bid_package_name} bid package.",
                f"I'm reaching out to invite you to submit a bid for {project_name}, specifically for the {bid_package_name} package.",
                f"We have an exciting opportunity for you to bid on {project_name} - the {bid_package_name} bid package.",
                f"I'd like to invite you to participate in bidding for the {bid_package_name} work on our {project_name} project.",
            ]
        else:  # Any other number of days
            intros = [
                f"I'd like to invite you to bid on {project_name} for the {bid_package_name} package.",
                f"Bid opportunity for {project_name} - {bid_package_name} work available.",
                f"New project invitation: {project_name} - {bid_package_name} package.",
                f"I wanted to reach out about a bidding opportunity for the {bid_package_name} work on {project_name}.",
            ]
        return random.choice(intros)
    
    def _get_timing_info(self, days_until_due: int) -> str:
        """Get a random timing information variation"""
        # Handle singular vs plural
        day_word = "day" if days_until_due == 1 else "days"
        
        if days_until_due == 1:
            urgent_phrases = [
                f"The bid deadline is tomorrow, so this is your final opportunity to submit.",
                f"With bids due tomorrow, I wanted to give you one last chance to participate.",
                f"Since the deadline is tomorrow, this is the final call for submissions.",
                f"The bidding closes tomorrow, so please let me know if you can still participate.",
            ]
            return random.choice(urgent_phrases)
        elif days_until_due == 2:
            urgent_phrases = [
                f"Bids are due in just 2 days, so time is getting tight.",
                f"With only 2 days until the deadline, I wanted to follow up with you.",
                f"The deadline is coming up quickly - we need submissions within 2 days.",
                f"Time is running short with the bid due in 2 days.",
            ]
            return random.choice(urgent_phrases)
        elif days_until_due == 3:
            urgent_phrases = [
                f"Bids are due in 3 days, so this is a quick turnaround opportunity.",
                f"With 3 days until the deadline, I wanted to reach out again.",
                f"The timeline is tight with bids due in 3 days.",
                f"We're looking for submissions within the next 3 days.",
            ]
            return random.choice(urgent_phrases)
        elif days_until_due == 7:
            normal_phrases = [
                f"Bids are due in one week, giving you a good window to prepare your submission.",
                f"You have about a week to put together your bid - the deadline is in 7 days.",
                f"The bidding deadline is next week, so you have time to review the details.",
                f"We're looking for submissions within the next week.",
            ]
            return random.choice(normal_phrases)
        else:
            normal_phrases = [
                f"Bids are due in {days_until_due} {day_word}.",
                f"You have {days_until_due} {day_word} to review the project and submit your bid.",
                f"The deadline is {days_until_due} {day_word} away.",
                f"We're looking for submissions within {days_until_due} {day_word}.",
            ]
            return random.choice(normal_phrases)
    
    def _get_portal_access(self, link: str, days_until_due: int) -> str:
        """Get a random portal access variation based on specific day values"""
        
        if days_until_due == 1:  # 1 day
            portal_phrases = [
                f"Please access the bidding portal immediately if you can still submit: {link}.",
                f"If you're able to get a bid in by tomorrow, here's the portal link: {link}.",
                f"The portal is still open until tomorrow if you can make it work: {link}.",
                f"Final access to submit your bid before the deadline: {link}.",
            ]
        elif days_until_due == 2:  # 2 days
            portal_phrases = [
                f"If you can work with this tight timeline, please access the portal here: {link}.",
                f"For those who can handle the quick turnaround, the bidding portal is: {link}.",
                f"Please check out the portal if you think you can submit within 2 days: {link}.",
                f"The project details and submission portal are available here: {link}.",
            ]
        elif days_until_due == 3:  # 3 days
            portal_phrases = [
                f"If this timeline works for you, please review the project details here: {link}.",
                f"For those interested in this quick opportunity, the portal is: {link}.",
                f"Please take a look at the project scope and requirements here: {link}.",
                f"You can access all the bidding information and submit here: {link}.",
            ]
        elif days_until_due == 7:  # 7 days
            portal_phrases = [
                f"You can review all the project details and requirements here: {link}.",
                f"The complete project information and bidding portal is available at: {link}.",
                f"Please take a look when you have a chance - here's the portal link: {link}.",
                f"All the specs and submission details can be found here: {link}.",
            ]
        else:  # Any other number of days
            portal_phrases = [
                f"You can review the project details and submit your bid here: {link}.",
                f"The complete project information is available at: {link}.",
                f"Please check out the portal when you get a chance: {link}.",
                f"All the bidding details and submission portal are here: {link}.",
            ]
        return random.choice(portal_phrases)
    
    def _get_closing_sentiment(self, days_until_due: int) -> str:
        """Get a random closing sentiment based on specific day values"""
        
        if days_until_due == 1:  # 1 day
            closings = [
                "I know it's last minute, but hope you can still make it work.",
                "Any chance you could pull together a quick bid for tomorrow's deadline?",
                "If you can make this work on such short notice, that would be great.",
                "Hope you can still participate despite the tight timing.",
            ]
        elif days_until_due == 2:  # 2 days
            closings = [
                "I know 2 days isn't much notice, but I wanted to give you the opportunity.",
                "Hope you can handle the quick turnaround and submit something.",
                "If you think you can make this timeline work, that would be fantastic.",
                "I'd appreciate it if you could take a look and see if this works for you.",
            ]
        elif days_until_due == 3:  # 3 days
            closings = [
                "I know it's a quick timeline, but I wanted to reach out in case you could make it work.",
                "Hope this could work with your schedule and you can submit a bid.",
                "If you think this timeline is manageable, I'd love to see your submission.",
                "I'd appreciate you taking a look to see if this opportunity fits.",
            ]
        elif days_until_due == 7:  # 7 days
            closings = [
                "Hope this looks like a good fit for your company.",
                "I'd appreciate you taking a look at the project details.",
                "Hope you'll consider submitting a bid for this opportunity.",
                "Looking forward to potentially seeing your submission.",
            ]
        else:  # Any other number of days
            closings = [
                "Hope this opportunity looks interesting to you.",
                "I'd appreciate you taking a look at the project details.",
                "Hope you'll consider participating in this bidding opportunity.",
                "Looking forward to potentially working together on this project.",
            ]
        return random.choice(closings)
    
    async def _get_subject_line(self, bid_package_name: str, project_name: str, days_until_due: int, 
                               invitation: BiddingInvitationData, project: Optional[Project], 
                               email_tracker: Optional[EmailTracker]) -> str:
        """Get email subject line based on specific day values"""
        
        # Generate subject line based on days until due
        if days_until_due == 1:  # 1 day - Final Reminder
            subjects = [
                f"Final Reminder: {bid_package_name} - DUE TOMORROW!",
                f"Final Reminder: {bid_package_name} Bid Closes Tomorrow!",
                f"Final Reminder: {bid_package_name} - Last Chance!",
                # Add your 1-day subject lines here
            ]
        elif days_until_due == 2:  # 2 days - Third Request
            subjects = [
                f"Third Request: {bid_package_name} - 2 days left!",
                f"Third Request: {bid_package_name} Bid Due in 2 days",
                f"Third Request: {bid_package_name} - {project_name}",
                # Add your 2-day subject lines here
            ]
        elif days_until_due == 3:  # 3 days - Second Request
            subjects = [
                f"Second Request: {bid_package_name} Bid",
                f"Second Request: {bid_package_name} - {project_name}",
                f"Second Request: {bid_package_name} Opportunity",
                # Add your 3-day subject lines here
            ]
        elif days_until_due == 7:  # 7 days - Generic/First Request
            subjects = [
                f"Bid Invitation: {bid_package_name} - {project_name}",
                f"New Bid Opportunity: {bid_package_name}",
                f"Project Invitation: {bid_package_name} Work",
                # Add your 7-day subject lines here
            ]
        else:  # Any other number of days - Generic
            subjects = [
                f"Bid Opportunity: {bid_package_name}",
                f"Project Bid: {bid_package_name} - {project_name}",
                f"New Opportunity: {bid_package_name} Work",
                # Add your default subject lines here
            ]
        return random.choice(subjects)
    
    def _get_signature(self) -> str:
        """Get Paul Herndon's email signature with links"""
        return """Best regards,
<br><br>
<strong>Paul Herndon</strong><br>
<a href="tel:+12819353863">281-935-3863</a><br>

<strong>Offices:</strong> <a href="https://maps.google.com/?q=Houston,TX">Houston</a> | <a href="https://maps.google.com/?q=San Antonio,TX">San Antonio</a><br>
<strong>Website:</strong> <a href="https://www.buildncs.com">www.buildncs.com</a>"""
    
    def _calculate_days_until_due(self, project: Optional[Project], override_days: Optional[int] = None) -> int:
        """Calculate days until bid is due (or use override for testing)"""
        # Use override if provided (for testing)
        if override_days is not None:
            logger.info(f"🧪 Using days override: {override_days}")
            return override_days
        
        if not project or not project.bidsDueAt:
            return 7  # Default fallback
        
        try:
            due_date = datetime.fromisoformat(project.bidsDueAt.replace('Z', '+00:00'))
            days_diff = (due_date.date() - datetime.now().date()).days
            return max(1, days_diff)  # Ensure at least 1 day
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning(f"Failed to parse bid due date '{project.bidsDueAt}': {e}")
            return 7  # Default fallback
    
    def _create_personalized_invitation_email(self, invitation: BiddingInvitationData, project: Optional[Project], override_days: Optional[int] = None) -> str:
        """Create personalized HTML email for bidding invitation using random variations"""
        
        # Determine project name - use bid package name as fallback and escape HTML
        project_name = html.escape(project.name if project else invitation.bidPackageName)
        bid_package_name = html.escape(invitation.bidPackageName)
        first_name = html.escape(invitation.firstName or "")
        
        # Calculate days until due (with override support)
        days_until_due = self._calculate_days_until_due(project, override_days)
        
        # Build the email using random variations based on timeline
        greeting = self._get_greeting(first_name)
        intro = self._get_intro(project_name, bid_package_name, days_until_due)
        timing = self._get_timing_info(days_until_due)
        portal_access = self._get_portal_access(invitation.linkToBid, days_until_due)
        closing = self._get_closing_sentiment(days_until_due)
        signature = self._get_signature()
        
        # Create HTML email with proper formatting
        email_body = f"""<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .email-content {{ margin: 0; }}
        .signature {{ margin-top: 20px; padding-top: 15px; }}
        a {{ color: #0066cc; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="email-content">
        <p>{greeting}</p>

        <p>{intro}</p>

        <p>{timing} {portal_access}</p>

        <br />
        <p>{closing}</p>

        <div class="signature">
            {signature}
        </div>
    </div>
</body>
</html>"""
        
        return email_body
    
    def should_continue_after_auth(self, state: BidReminderState) -> str:
        """Continue to check projects or end on auth error"""
        if state.get("error_message"):
            logger.info("➡️  Auth failed, routing to finalize_result")
            return "finalize_result"
        logger.info("➡️  Auth successful, routing to check_upcoming_projects")
        return "check_upcoming_projects"
    
    def should_continue_after_projects(self, state: BidReminderState) -> str:
        """Go to get bidding invitations if no error, otherwise finalize"""
        if state.get("error_message"):
            logger.info("➡️  Projects check failed, routing to finalize_result")
            return "finalize_result"
        logger.info("➡️  Projects checked successfully, routing to get_bidding_invitations")
        return "get_bidding_invitations"
    
    def should_continue_after_invitations(self, state: BidReminderState) -> str:
        """Go to send emails after getting bidding invitations, or finalize on error"""
        if state.get("error_message"):
            logger.info("➡️  Bidding invitations check failed, routing to finalize_result")
            return "finalize_result"
        logger.info("➡️  Bidding invitations checked successfully, routing to send_reminder_email")
        return "send_reminder_email"
    
    def should_continue_after_email(self, state: BidReminderState) -> str:
        """Go to finalize after sending emails"""
        logger.info("➡️  Email sending completed, routing to finalize_result")
        return "finalize_result"
    
    def build_graph(self) -> StateGraph:
        """Build the workflow graph with complete email functionality"""
        logger.info("🏗️  Building LangGraph workflow")
        graph = StateGraph(BidReminderState)
        
        # Add nodes
        logger.info("Adding workflow nodes:")
        graph.add_node("initialize_auth", self.initialize_auth_node)
        logger.info("  - initialize_auth")
        graph.add_node("check_upcoming_projects", self.check_upcoming_projects_node)
        logger.info("  - check_upcoming_projects")
        graph.add_node("get_bidding_invitations", self.get_bidding_invitations_node)
        logger.info("  - get_bidding_invitations")
        graph.add_node("send_reminder_email", self.send_reminder_email_node)
        logger.info("  - send_reminder_email")
        graph.add_node("finalize_result", self.finalize_result_node)
        logger.info("  - finalize_result")
        graph.add_node("prepare_next_run", self.prepare_next_run_node)
        logger.info("  - prepare_next_run")
        
        # Add edges (complete flow with email sending)
        logger.info("Adding workflow edges:")
        graph.add_edge(START, "initialize_auth")
        logger.info("  - START → initialize_auth")
        graph.add_conditional_edges(
            "initialize_auth",
            self.should_continue_after_auth,
            {
                "check_upcoming_projects": "check_upcoming_projects",
                "finalize_result": "finalize_result"
            }
        )
        logger.info("  - initialize_auth → check_upcoming_projects OR finalize_result")
        graph.add_conditional_edges(
            "check_upcoming_projects",
            self.should_continue_after_projects,
            {
                "get_bidding_invitations": "get_bidding_invitations",
                "finalize_result": "finalize_result"
            }
        )
        logger.info("  - check_upcoming_projects → get_bidding_invitations OR finalize_result")
        graph.add_conditional_edges(
            "get_bidding_invitations",
            self.should_continue_after_invitations,
            {
                "send_reminder_email": "send_reminder_email",
                "finalize_result": "finalize_result"
            }
        )
        logger.info("  - get_bidding_invitations → send_reminder_email OR finalize_result")
        graph.add_conditional_edges(
            "send_reminder_email",
            self.should_continue_after_email,
            {
                "finalize_result": "finalize_result"
            }
        )
        logger.info("  - send_reminder_email → finalize_result")
        graph.add_edge("finalize_result", "prepare_next_run")
        logger.info("  - finalize_result → prepare_next_run")
        graph.add_edge("prepare_next_run", END)
        logger.info("  - prepare_next_run → END")
        
        logger.info("✅ Workflow graph compiled successfully")
        return graph.compile()
    
    async def run_bid_reminder_workflow(self) -> dict:
        """Run the bid reminder workflow"""
        logger.info("🚀 Starting bid reminder workflow execution")
        
        # Create main workflow transaction
        with create_transaction(
            name="bid_reminder_workflow_execution",
            operation=SentryOperations.BID_REMINDER,
            component=SentryComponents.WORKFLOW,
            description="Complete bid reminder workflow execution"
        ) as transaction:
            
            add_breadcrumb(
                message="Workflow execution started",
                category="workflow",
                level="info",
                data={"start_time": self.run_start_time.isoformat()}
            )
            
            graph = self.build_graph()
        
            # Initial state
            logger.info("Initializing workflow state")
            initial_state: BidReminderState = {
                "outlook_token_manager": None,
                "building_token_manager": None,
                "outlook_client": None,
                "building_client": None,
                "upcoming_projects": None,
                "bidding_invitations": None,
                "reminder_email_sent": False,
                "email_tracker": None,
                "test_project_id": self.test_project_id,
                "test_days_out": self.test_days_out,
                "error_message": None,
                "workflow_successful": False,
                "result_message": None
            }
            logger.info("✅ Initial state created")
            
            # Execute workflow with enhanced tracing
            logger.info("🔄 Executing LangGraph workflow...")
            config = {}
            if os.getenv("LANGSMITH_TRACING") == "true" and os.getenv("LANGSMITH_API_KEY"):
                # Create enhanced run configuration
                run_name = self._create_run_name()
                metadata = self._create_run_metadata()
                
                config = {
                    "configurable": {
                        "thread_id": f"bid-reminder-{self.run_start_time.strftime('%Y%m%d-%H%M%S')}"
                    },
                    "tags": ["bid-reminder", "langgraph", "automation"],
                    "metadata": metadata,
                    "run_name": run_name
                }
                logger.info(f"🔍 Enhanced LangSmith tracing enabled: {run_name}")
            
            result = await graph.ainvoke(initial_state, config=config)
            logger.info("✅ Workflow execution completed")
                
            # Set transaction data
            transaction.set_data("workflow_successful", result.get('workflow_successful', False))
            transaction.set_data("projects_found", len(result.get('upcoming_projects', [])))
            transaction.set_data("email_sent", result.get('reminder_email_sent', False))
            
            if result.get('error_message'):
                transaction.set_tag("error", True)
                transaction.set_data("error_message", result.get('error_message'))
            
            # Log final results
            logger.info("📊 Workflow Results:")
            logger.info(f"  - Successful: {result.get('workflow_successful', False)}")
            logger.info(f"  - Projects found: {len(result.get('upcoming_projects', []))}")
            logger.info(f"  - Email sent: {result.get('reminder_email_sent', False)}")
            if result.get('error_message'):
                logger.error(f"  - Error: {result.get('error_message')}")
            
            add_breadcrumb(
                message="Workflow execution completed",
                category="workflow",
                level="info",
                data={
                    "workflow_successful": result.get('workflow_successful', False),
                    "projects_found": len(result.get('upcoming_projects', [])),
                    "email_sent": result.get('reminder_email_sent', False)
                }
            )
            
            return result


# Convenience function
async def run_bid_reminder(project_id: Optional[str] = None, days_out: Optional[int] = None) -> dict:
    """Simple function to run bid reminder workflow with optional test parameters"""
    logger.info("📞 Called run_bid_reminder() convenience function")
    if project_id or days_out:
        logger.info(f"🧪 Test mode - Project ID: {project_id}, Days Out: {days_out}")
    agent = BidReminderAgent(test_project_id=project_id, test_days_out=days_out)
    return await agent.run_bid_reminder_workflow()


if __name__ == "__main__":
    import asyncio
    
    async def main():
        logger.info("="*50)
        logger.info("🚀 STARTING BID REMINDER AGENT")
        logger.info("="*50)
        
        print("🚀 Running Bid Reminder Agent...")
        print("This will check BuildingConnected for projects due in 5-10 days")
        print("and send personalized invitation emails to each bidder.\n")
        
        result = await run_bid_reminder()
        
        logger.info("="*50)
        logger.info("📋 FINAL RESULTS")
        logger.info("="*50)
        
        print(result.get("result_message", "No result message"))
        print(f"\nWorkflow successful: {result.get('workflow_successful', False)}")
        
        if result.get("upcoming_projects"):
            projects = result["upcoming_projects"]
            print(f"\nProjects found: {len(projects)}")
            for project in projects[:5]:  # Show first 5
                print(f"  - {project.name} (Due: {project.bidsDueAt})")
        
        logger.info("🏁 BID REMINDER AGENT COMPLETED")
        logger.info("="*50)
    
    asyncio.run(main())