"""
Simple Bid Reminder Agent
Checks BuildingConnected for projects due in 5-10 days and sends reminder emails
"""

import os
import logging
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
    
    def _create_personalized_invitation_email(self, invitation: BiddingInvitationData, project: Optional[Project]) -> str:
        """Create personalized HTML email for bidding invitation with LinkToBid button"""
        
        # Format the due date if available
        due_date_formatted = "Not specified"
        if project and project.bidsDueAt:
            try:
                due_date = datetime.fromisoformat(project.bidsDueAt.replace('Z', '+00:00'))
                due_date_formatted = due_date.strftime('%A, %B %d, %Y at %I:%M %p')
            except:
                due_date_formatted = project.bidsDueAt
        
        # Determine project name - use bid package name as fallback
        project_name = project.name if project else invitation.bidPackageName
        
        # Create the HTML email template
        html_template = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .project-details {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .cta-button {{ display: inline-block; background: #28a745; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold; margin: 20px 0; text-align: center; }}
                .cta-button:hover {{ background: #218838; }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 12px; }}
                .urgent {{ color: #dc3545; font-weight: bold; }}
                .highlight {{ background: #fff3cd; padding: 10px; border-left: 4px solid #ffc107; margin: 15px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🏗️ Bid Invitation</h1>
                    <p>You're invited to submit a bid</p>
                </div>
                
                <div class="content">
                    <h2>Hello {invitation.firstName} {invitation.lastName},</h2>
                    
                    <p>You have been invited to submit a bid for the following project:</p>
                    
                    <div class="project-details">
                        <h3>📋 Project Details</h3>
                        <p><strong>Project:</strong> {project_name}</p>
                        <p><strong>Bid Package:</strong> {invitation.bidPackageName}</p>
                        <p><strong>Bid Due Date:</strong> <span class="urgent">{due_date_formatted}</span></p>
                        {f'<p><strong>Project State:</strong> {project.state}</p>' if project and project.state else ''}
                        {f'<p><strong>Sealed Bidding:</strong> {"Yes" if project and project.isBiddingSealed else "No"}</p>' if project else ''}
                    </div>
                    
                    <div class="highlight">
                        <p><strong>⏰ Action Required:</strong> This bid is due soon! Please review the project details and submit your bid before the deadline.</p>
                    </div>
                    
                    <div style="text-align: center;">
                        <a href="{invitation.linkToBid}" class="cta-button">
                            🔗 Access Bid Portal
                        </a>
                    </div>
                    
                    <p><strong>Next Steps:</strong></p>
                    <ol>
                        <li>Click the "Access Bid Portal" button above</li>
                        <li>Review all project documents and specifications</li>
                        <li>Prepare and submit your bid before the deadline</li>
                        <li>Contact the project team if you have any questions</li>
                    </ol>
                    
                    <p>If you have any questions about this invitation or need assistance accessing the bid portal, please contact the project team directly.</p>
                    
                    <p>Good luck with your submission!</p>
                    
                    <div class="footer">
                        <p><em>This invitation was automatically sent by Claude's Bid Reminder Agent.</em></p>
                        <p><small>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        return html_template
    
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
        graph.add_edge("finalize_result", END)
        logger.info("  - finalize_result → END")
        
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