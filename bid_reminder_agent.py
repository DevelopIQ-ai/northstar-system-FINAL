"""
Simple Bid Reminder Agent
Checks BuildingConnected for projects due in 5-10 days and sends reminder emails
"""

import os
import logging
import random
from typing import Optional, List
from datetime import datetime

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

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

load_dotenv()

# Initialize Sentry for standalone agent
sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[
            LoggingIntegration(
                level=logging.INFO,        # Capture info and above as breadcrumbs
                event_level=logging.WARNING  # Send warnings and above as events
            ),
        ],
        traces_sample_rate=0.1,
        environment=os.getenv("ENVIRONMENT", "production"),
        release=os.getenv("RELEASE_VERSION", "1.0.0"),
        send_default_pii=False,
        # Enhanced logging options
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
    
    # Results
    error_message: Optional[str]
    workflow_successful: bool
    result_message: Optional[str]


class BidReminderAgent:
    """Simple agent that checks for upcoming bids and sends reminder emails"""
    
    def __init__(self):
        self.default_recipient = os.getenv("DEFAULT_EMAIL_RECIPIENT", "kush@developiq.ai")
        self.days_before_bid = [5, 6, 7, 8, 9, 10]  # Check 5-10 days before bid due
        self.run_start_time = datetime.now()
        logger.info("BidReminderAgent initialized")
        logger.info(f"Default email recipient: {self.default_recipient}")
        logger.info(f"Days before bid to check: {self.days_before_bid}")
    
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
        logger.info("🔐 Starting authentication initialization node")
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
                "error_message": None
            }
            
        except Exception as e:
            logger.error(f"❌ Authentication initialization failed: {str(e)}")
            return {
                **state,
                "outlook_token_manager": None,
                "building_token_manager": None,
                "outlook_client": None,
                "building_client": None,
                "error_message": f"Authentication failed: {str(e)}",
                "workflow_successful": False
            }
    
    @traceable(name="📋 Check Upcoming Projects", tags=["projects", "data-fetch"])
    async def check_upcoming_projects_node(self, state: BidReminderState) -> BidReminderState:
        """Check BuildingConnected for projects due in 5-10 days"""
        logger.info("📋 Starting project check node")
        
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
            logger.info(f"Checking projects due in {self.days_before_bid} days")
            # Get projects due in 5-10 days
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
            
            # Log project details
            for project in unique_projects:
                logger.info(f"  - {project.name} | Due: {project.bidsDueAt} | State: {project.state}")
            
            return {
                **state,
                "upcoming_projects": unique_projects,
                "error_message": None
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to check projects: {str(e)}")
            return {
                **state,
                "upcoming_projects": None,
                "error_message": f"Failed to check projects: {str(e)}",
                "workflow_successful": False
            }
    
    async def get_bidding_invitations_node(self, state: BidReminderState) -> BidReminderState:
        """Get bidding invitations for each upcoming project"""
        logger.info("📧 Starting bidding invitations check node")
        
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
            
            return {
                **state,
                "bidding_invitations": all_bidding_invitations,
                "error_message": None
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to get bidding invitations: {str(e)}")
            return {
                **state,
                "bidding_invitations": None,
                "error_message": f"Failed to get bidding invitations: {str(e)}",
                "workflow_successful": False
            }
    
    @traceable(name="📧 Send Invitation Emails", tags=["email", "invitations"])
    async def send_reminder_email_node(self, state: BidReminderState) -> BidReminderState:
        """Send personalized emails to each bidding invitation"""
        logger.info("📧 Starting email sending node")
        
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
                    
                    # Create personalized email
                    email_subject = f"Bid Invitation: {invitation.bidPackageName}"
                    email_body = self._create_personalized_invitation_email(invitation, project)
                    
                    # Send email
                    send_response = await outlook_client.send_email(
                        to=invitation.email,
                        subject=email_subject,
                        body=email_body,
                        importance=EmailImportance.HIGH
                    )
                    
                    if send_response.success:
                        emails_sent += 1
                        logger.info(f"✅ Email sent successfully to {invitation.email}")
                    else:
                        failed_emails.append(f"{invitation.email}: {send_response.error}")
                        logger.error(f"❌ Failed to send email to {invitation.email}: {send_response.error}")
                        
                except Exception as email_error:
                    failed_emails.append(f"{invitation.email}: {str(email_error)}")
                    logger.error(f"❌ Failed to send email to {invitation.email}: {str(email_error)}")
            
            # Determine overall success
            if emails_sent > 0:
                success_message = f"✅ Successfully sent {emails_sent} invitation emails"
                if failed_emails:
                    success_message += f", {len(failed_emails)} failed"
                logger.info(success_message)
                
                return {
                    **state,
                    "reminder_email_sent": True,
                    "workflow_successful": True,
                    "error_message": None
                }
            else:
                error_message = f"Failed to send any emails. Errors: {'; '.join(failed_emails[:3])}"
                logger.error(error_message)
                return {
                    **state,
                    "reminder_email_sent": False,
                    "workflow_successful": False,
                    "error_message": error_message
                }
                
        except Exception as e:
            logger.error(f"❌ Email sending process failed: {str(e)}")
            return {
                **state,
                "reminder_email_sent": False,
                "workflow_successful": False,
                "error_message": f"Email sending failed: {str(e)}"
            }
    
    @traceable(name="🏁 Finalize Results", tags=["finalize", "summary"])
    async def finalize_result_node(self, state: BidReminderState) -> BidReminderState:
        """Finalize the workflow result - showing project data, bidding invitations, and email status"""
        logger.info("🏁 Starting finalize result node")
        
        upcoming_projects = state.get("upcoming_projects", [])
        bidding_invitations = state.get("bidding_invitations", [])
        reminder_email_sent = state.get("reminder_email_sent", False)
        error_message = state.get("error_message")
        
        logger.info(f"Projects found: {len(upcoming_projects) if upcoming_projects else 0}")
        logger.info(f"Bidding invitations found: {len(bidding_invitations) if bidding_invitations else 0}")
        logger.info(f"Emails sent: {reminder_email_sent}")
        for invitation in bidding_invitations:
            logger.info(f"  - {invitation.firstName} {invitation.lastName} ({invitation.email}) - {invitation.bidPackageName}")
            logger.info(f"  - {invitation.linkToBid}\n\n")
        logger.info(f"Error message: {error_message if error_message else 'None'}")
        
        if error_message:
            result_message = f"❌ Workflow failed: {error_message}"
            workflow_successful = False
            logger.error(f"Workflow failed with error: {error_message}")
        else:
            project_count = len(upcoming_projects)
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
        """Get a random greeting variation"""
        # Handle empty or missing first names
        if not first_name or first_name.strip() == "":
            greetings = [
                "Hey there",
                "Hi there",
                "Hello",
                "Good morning",
                "Hope you're doing well",
                "Greetings",
            ]
        else:
            greetings = [
                f"Hey {first_name}",
                f"Hi {first_name}",
                f"Hello {first_name}",
                f"Good morning {first_name}",
                f"Hope you're doing well {first_name}",
                f"Hi there {first_name}",
            ]
        return random.choice(greetings)
    
    def _get_intro(self, project_name: str, bid_package_name: str) -> str:
        """Get a random intro variation"""
        intros = [
            f"I wanted to personally invite you to bid on our project, {project_name}, for the {bid_package_name} bid package.",
            f"I'm reaching out to invite you to submit a bid for {project_name}, specifically for the {bid_package_name} package.",
            f"We have an exciting opportunity for you to bid on {project_name} - the {bid_package_name} bid package.",
            f"I'd love to have you consider bidding on our {project_name} project for the {bid_package_name} work.",
            f"I'm personally inviting you to participate in our {project_name} project bidding for the {bid_package_name} package.",
            f"We're looking for quality contractors to bid on {project_name}, and I think you'd be perfect for the {bid_package_name} work.",
            f"I wanted to extend a personal invitation for you to bid on the {bid_package_name} package for our {project_name} project.",
        ]
        return random.choice(intros)
    
    def _get_timing_info(self, days_until_due: int) -> str:
        """Get a random timing information variation"""
        # Handle singular vs plural
        day_word = "day" if days_until_due == 1 else "days"
        
        if days_until_due <= 5:
            urgent_phrases = [
                f"Bids are due in just {days_until_due} {day_word}",
                f"The deadline is coming up fast - only {days_until_due} {day_word} left",
                f"Time is running short with {days_until_due} {day_word} remaining",
                f"We're down to {days_until_due} {day_word} until the bid deadline",
            ]
            return random.choice(urgent_phrases)
        else:
            normal_phrases = [
                f"Bids are due in {days_until_due} {day_word}",
                f"You have {days_until_due} {day_word} to submit your bid",
                f"The deadline is {days_until_due} {day_word} away",
                f"We're looking for submissions within {days_until_due} {day_word}",
            ]
            return random.choice(normal_phrases)
    
    def _get_portal_access(self, link: str) -> str:
        """Get a random portal access variation"""
        portal_phrases = [
            f"and you can access the portal here: {link}",
            f" - you can find all the details and submit your bid at: {link}",
            f" - the bid portal is available at: {link}",
            f" - access the full project details and submit your bid here: {link}",
            f" - all project documents and the bidding portal are at: {link}",
            f" - you can review everything and submit your bid at: {link}",
        ]
        return random.choice(portal_phrases)
    
    def _get_closing_sentiment(self) -> str:
        """Get a random closing sentiment"""
        closings = [
            "I'm looking forward to potentially working with you!",
            "Hope to see your bid come through!",
            "Looking forward to your submission!",
            "I'd be excited to work with you on this project!",
            "Hope we can partner together on this one!",
            "Looking forward to a great partnership!",
            "Can't wait to see what you put together!",
            "Hope this opportunity interests you!",
        ]
        return random.choice(closings)
    
    def _get_signature(self) -> str:
        """Get Paul Herndon's email signature with links"""
        return """Best regards,
<br /><br />
<strong>Paul Herndon</strong><br>
<a href="tel:+12819353863">281-935-3863</a>

<strong>Offices:</strong> <a href="https://maps.google.com/?q=Houston,TX">Houston</a> | <a href="https://maps.google.com/?q=San Antonio,TX">San Antonio</a><br>
<strong>Website:</strong> <a href="https://www.buildncs.com">www.buildncs.com</a>"""
    
    def _calculate_days_until_due(self, project: Optional[Project]) -> int:
        """Calculate days until bid is due"""
        if not project or not project.bidsDueAt:
            return 7  # Default fallback
        
        try:
            due_date = datetime.fromisoformat(project.bidsDueAt.replace('Z', '+00:00'))
            days_diff = (due_date.date() - datetime.now().date()).days
            return max(1, days_diff)  # Ensure at least 1 day
        except:
            return 7  # Default fallback
    
    def _create_personalized_invitation_email(self, invitation: BiddingInvitationData, project: Optional[Project]) -> str:
        """Create personalized HTML email for bidding invitation using random variations"""
        
        # Determine project name - use bid package name as fallback
        project_name = project.name if project else invitation.bidPackageName
        
        # Calculate days until due
        days_until_due = self._calculate_days_until_due(project)
        
        # Build the email using random variations
        greeting = self._get_greeting(invitation.firstName)
        intro = self._get_intro(project_name, invitation.bidPackageName)
        timing = self._get_timing_info(days_until_due)
        portal_access = self._get_portal_access(invitation.linkToBid)
        closing = self._get_closing_sentiment()
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
        <p>{greeting},</p>

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
        
        # Log final results
        logger.info("📊 Workflow Results:")
        logger.info(f"  - Successful: {result.get('workflow_successful', False)}")
        logger.info(f"  - Projects found: {len(result.get('upcoming_projects', []))}")
        logger.info(f"  - Email sent: {result.get('reminder_email_sent', False)}")
        if result.get('error_message'):
            logger.error(f"  - Error: {result.get('error_message')}")
        
        return result


# Convenience function
async def run_bid_reminder() -> dict:
    """Simple function to run bid reminder workflow"""
    logger.info("📞 Called run_bid_reminder() convenience function")
    agent = BidReminderAgent()
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