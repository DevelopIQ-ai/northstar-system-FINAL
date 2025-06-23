"""
Simple Bid Reminder Agent
Checks BuildingConnected for projects due in 5-10 days and sends reminder emails
"""

import os
import logging
from typing import Optional, List
from datetime import datetime

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel
from typing_extensions import TypedDict

from auth.auth_helpers import (
    create_token_manager_from_env,
    create_buildingconnected_token_manager_from_env,
    MSGraphTokenManager,
    BuildingConnectedTokenManager
)
from clients.graph_api_client import MSGraphClient, EmailImportance
from clients.buildingconnected_client import BuildingConnectedClient, Project

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bid_reminder_agent.log')
    ]
)
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
        logger.info("BidReminderAgent initialized")
        logger.info(f"Default email recipient: {self.default_recipient}")
        logger.info(f"Days before bid to check: {self.days_before_bid}")
    
    async def initialize_auth_node(self, state: BidReminderState) -> BidReminderState:
        """Initialize authentication for BuildingConnected only (email auth commented out)"""
        logger.info("🔐 Starting authentication initialization node")
        try:
            logger.info("Creating BuildingConnected token manager from environment")
            # Initialize BuildingConnected only for now
            building_token_manager = create_buildingconnected_token_manager_from_env()
            logger.info("✅ BuildingConnected token manager created successfully")
            
            logger.info("Creating BuildingConnected client with token manager")
            building_client = BuildingConnectedClient(building_token_manager)
            logger.info("✅ BuildingConnected client created successfully")
            
            # Verify BuildingConnected auth by testing projects endpoint instead of user info
            # This bypasses potential user info endpoint issues
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
                "outlook_token_manager": None,  # Commented out for now
                "building_token_manager": building_token_manager,
                "outlook_client": None,  # Commented out for now
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
    
    # COMMENTED OUT FOR NOW - only want to see project data
    # async def send_reminder_email_node(self, state: BidReminderState) -> BidReminderState:
    #     """Send reminder email about upcoming projects"""
    #     if state.get("error_message"):
    #         return {
    #             **state,
    #             "reminder_email_sent": False,
    #             "workflow_successful": False
    #         }
    #     
    #     outlook_client = state["outlook_client"]
    #     upcoming_projects = state.get("upcoming_projects", [])
    #     
    #     if not outlook_client:
    #         return {
    #             **state,
    #             "error_message": "Outlook client not initialized",
    #             "reminder_email_sent": False,
    #             "workflow_successful": False
    #         }
    #     
    #     try:
    #         if not upcoming_projects:
    #             # No projects due - send empty reminder
    #             email_subject = "BuildingConnected Bid Reminder - No Upcoming Bids"
    #             email_body = self._create_no_projects_email()
    #         else:
    #             # Projects found - send reminder
    #             email_subject = f"BuildingConnected Bid Reminder - {len(upcoming_projects)} Projects Due Soon"
    #             email_body = self._create_reminder_email(upcoming_projects)
    #         
    #         # Send email
    #         send_response = await outlook_client.send_email(
    #             to=self.default_recipient,
    #             subject=email_subject,
    #             body=email_body,
    #             importance=EmailImportance.HIGH
    #         )
    #         
    #         if send_response.success:
    #             return {
    #                 **state,
    #                 "reminder_email_sent": True,
    #                 "workflow_successful": True,
    #                 "error_message": None
    #             }
    #         else:
    #             return {
    #                 **state,
    #                 "reminder_email_sent": False,
    #                 "workflow_successful": False,
    #                 "error_message": f"Email sending failed: {send_response.error}"
    #             }
    #             
    #     except Exception as e:
    #         return {
    #             **state,
    #             "reminder_email_sent": False,
    #             "workflow_successful": False,
    #             "error_message": f"Email sending failed: {str(e)}"
    #         }
    
    async def finalize_result_node(self, state: BidReminderState) -> BidReminderState:
        """Finalize the workflow result - only showing project data for now"""
        logger.info("🏁 Starting finalize result node")
        
        upcoming_projects = state.get("upcoming_projects", [])
        error_message = state.get("error_message")
        
        logger.info(f"Projects found: {len(upcoming_projects) if upcoming_projects else 0}")
        logger.info(f"Error message: {error_message if error_message else 'None'}")
        
        if error_message:
            result_message = f"❌ Workflow failed: {error_message}"
            workflow_successful = False
            logger.error(f"Workflow failed with error: {error_message}")
        else:
            project_count = len(upcoming_projects)
            result_message = (
                f"✅ Project check completed successfully!\n"
                f"📋 Found {project_count} projects due in 5-10 days\n"
                f"📧 Email sending is currently disabled - only showing project data"
            )
            workflow_successful = True
            logger.info(f"✅ Workflow completed successfully with {project_count} projects")
        
        logger.info("🏁 Finalize result node completed")
        
        return {
            **state,
            "result_message": result_message,
            "workflow_successful": workflow_successful,
            "reminder_email_sent": False  # Always false since email is disabled
        }
    
    # COMMENTED OUT - Email functions not needed for now
    # def _create_reminder_email(self, projects: List[Project]) -> str:
    #     """Create HTML email body for project reminders"""
    #     html_parts = [
    #         "<html><body>",
    #         "<h2>🚨 BuildingConnected Bid Reminder</h2>",
    #         f"<p>You have <strong>{len(projects)}</strong> projects with bids due in the next 5-10 days:</p>",
    #         "<table border='1' cellpadding='10' cellspacing='0' style='border-collapse: collapse; width: 100%;'>",
    #         "<tr style='background-color: #f0f0f0;'>",
    #         "<th>Project Name</th>",
    #         "<th>Bid Due Date</th>",
    #         "<th>State</th>",
    #         "<th>Sealed Bidding</th>",
    #         "</tr>"
    #     ]
    #     
    #     for project in projects:
    #         # Format date for display
    #         try:
    #             if project.bidsDueAt:
    #                 due_date = datetime.fromisoformat(project.bidsDueAt.replace('Z', '+00:00'))
    #                 formatted_date = due_date.strftime('%Y-%m-%d %H:%M')
    #             else:
    #                 formatted_date = "Not specified"
    #         except:
    #             formatted_date = project.bidsDueAt or "Not specified"
    #         
    #         sealed_status = "Yes" if project.isBiddingSealed else "No"
    #         
    #         html_parts.extend([
    #             "<tr>",
    #             f"<td><strong>{project.name}</strong></td>",
    #             f"<td>{formatted_date}</td>",
    #             f"<td>{project.state or 'Unknown'}</td>",
    #             f"<td>{sealed_status}</td>",
    #             "</tr>"
    #         ])
    #     
    #     html_parts.extend([
    #         "</table>",
    #         "<br>",
    #         "<p><strong>⚠️ Action Required:</strong> Review these projects and ensure your bids are ready!</p>",
    #         "<p><em>This reminder was automatically generated by Claude's Bid Reminder Agent.</em></p>",
    #         f"<p><small>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>",
    #         "</body></html>"
    #     ])
    #     
    #     return "".join(html_parts)
    # 
    # def _create_no_projects_email(self) -> str:
    #     """Create email body when no projects are due"""
    #     return """
    #     <html><body>
    #     <h2>✅ BuildingConnected Bid Reminder</h2>
    #     <p>Good news! You have <strong>no projects</strong> with bids due in the next 5-10 days.</p>
    #     <p>You can relax for now, but don't forget to check back later!</p>
    #     <p><em>This reminder was automatically generated by Claude's Bid Reminder Agent.</em></p>
    #     <p><small>Generated on: {}</small></p>
    #     </body></html>
    #     """.format(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    
    def should_continue_after_auth(self, state: BidReminderState) -> str:
        """Continue to check projects or end on auth error"""
        if state.get("error_message"):
            logger.info("➡️  Auth failed, routing to finalize_result")
            return "finalize_result"
        logger.info("➡️  Auth successful, routing to check_upcoming_projects")
        return "check_upcoming_projects"
    
    def should_continue_after_projects(self, state: BidReminderState) -> str:
        """Go directly to finalize since email is disabled"""
        logger.info("➡️  Projects checked, routing to finalize_result")
        return "finalize_result"
    
    def build_graph(self) -> StateGraph:
        """Build the simplified workflow graph (email nodes commented out)"""
        logger.info("🏗️  Building LangGraph workflow")
        graph = StateGraph(BidReminderState)
        
        # Add nodes (email node commented out)
        logger.info("Adding workflow nodes:")
        graph.add_node("initialize_auth", self.initialize_auth_node)
        logger.info("  - initialize_auth")
        graph.add_node("check_upcoming_projects", self.check_upcoming_projects_node)
        logger.info("  - check_upcoming_projects")
        # graph.add_node("send_reminder_email", self.send_reminder_email_node)  # COMMENTED OUT
        graph.add_node("finalize_result", self.finalize_result_node)
        logger.info("  - finalize_result")
        
        # Add edges (simplified flow without email)
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
                "finalize_result": "finalize_result"  # Direct to finalize, no email
            }
        )
        logger.info("  - check_upcoming_projects → finalize_result")
        # graph.add_edge("send_reminder_email", "finalize_result")  # COMMENTED OUT
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
            "reminder_email_sent": False,
            "error_message": None,
            "workflow_successful": False,
            "result_message": None
        }
        logger.info("✅ Initial state created")
        
        # Execute workflow
        logger.info("🔄 Executing LangGraph workflow...")
        result = await graph.ainvoke(initial_state)
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
        print("and send a reminder email.\n")
        
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