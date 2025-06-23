"""
Deterministic BuildingConnected/Autodesk Construction API client  
Direct API access without MCP protocol overhead
"""

import logging
import json
import os
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from enum import Enum
import math

import httpx
from pydantic import BaseModel, Field

from auth.auth_helpers import TokenManager

logger = logging.getLogger(__name__)


class ProjectState(str, Enum):
    """Project state enumeration"""
    ACTIVE = "active"
    CLOSED = "closed"
    DRAFT = "draft"


class Project(BaseModel):
    """BuildingConnected project model"""
    id: str
    name: str
    bidsDueAt: Optional[str] = None
    state: Optional[str] = None
    isBiddingSealed: Optional[bool] = None
    description: Optional[str] = None
    location: Optional[Any] = None  # Can be string or dict from API


class ProjectsDueResponse(BaseModel):
    """Response model for projects due in N days"""
    projects: List[Project]
    targetDate: str
    daysFromNow: int
    total: int
    timestamp: str


class UserInfo(BaseModel):
    """User information model"""
    id: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    company: Optional[str] = None
    authenticated: bool = False


class BiddingInvitationData(BaseModel):
    """Bidding invitation data model"""
    id: str
    state: str
    projectId: str
    bidPackageId: str
    bidPackageName: str
    bidsDueAt: str
    daysUntilBidsDue: int
    userId: str
    firstName: str
    lastName: str
    title: str
    email: str
    linkToBid: str


class BidPackage(BaseModel):
    """Bid package model"""
    id: str
    name: str
    projectId: str


class Invitee(BaseModel):
    """Invitee model"""
    state: str
    userId: str
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    title: Optional[str] = None
    email: str


class Invite(BaseModel):
    """Invite model"""
    id: str
    projectId: str
    bidPackageId: str
    invitees: List[Invitee]


class PaginationInfo(BaseModel):
    """Pagination information"""
    nextUrl: Optional[str] = None


class BidPackageApiResponse(BaseModel):
    """Bid package API response"""
    results: List[BidPackage]
    pagination: PaginationInfo


class InviteApiResponse(BaseModel):
    """Invite API response"""
    results: List[Invite]
    pagination: PaginationInfo


class BuildingConnectedError(Exception):
    """BuildingConnected API error"""
    def __init__(self, status_code: int, message: str, response_text: str = ""):
        self.status_code = status_code
        self.message = message
        self.response_text = response_text
        super().__init__(f"BuildingConnected API Error {status_code}: {message}")


class BuildingConnectedClient:
    """Deterministic BuildingConnected API client"""
    
    def __init__(self, token_manager: TokenManager):
        self.token_manager = token_manager
        self.base_url = "https://developer.api.autodesk.com/construction/buildingconnected/v2"
        logger.info(f"BuildingConnectedClient initialized with base URL: {self.base_url}")
        
    async def _make_request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Make authenticated request to BuildingConnected API"""
        logger.debug(f"🌐 Making {method.upper()} request to path: {path}")
        if params:
            logger.debug(f"Query parameters: {params}")
        if data:
            logger.debug(f"Request data: {data}")
            
        access_token = await self.token_manager.get_access_token()
        logger.debug("✅ Retrieved access token from token manager")
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        # Log partial token for security (but use full token in headers)
        logger.debug(f"🔑 Using Bearer token: {access_token[:20]}...")
        
        url = f"{self.base_url}/{path.lstrip('/')}"
        logger.info(f"🔗 API Request: {method.upper()} {url}")
        
        async with httpx.AsyncClient() as client:
            if method.upper() == 'GET':
                response = await client.get(url, headers=headers, params=params)
            elif method.upper() == 'POST':
                response = await client.post(url, headers=headers, json=data)
            elif method.upper() == 'PATCH':
                response = await client.patch(url, headers=headers, json=data)
            elif method.upper() == 'DELETE':
                response = await client.delete(url, headers=headers)
            else:
                logger.error(f"❌ Unsupported HTTP method: {method}")
                raise ValueError(f"Unsupported HTTP method: {method}")
                
        logger.info(f"📡 Response: {response.status_code} {response.reason_phrase}")
        
        # Handle authentication errors
        if response.status_code == 401:
            logger.error("❌ Authentication failed - token may be expired")
            raise BuildingConnectedError(401, "Authentication required - token may be expired")
        
        # Handle other errors
        if not response.is_success:
            error_text = response.text
            logger.error(f"❌ API Error {response.status_code}: {error_text[:200]}...")
            try:
                error_json = response.json()
                error_message = error_json.get('error', {}).get('message', error_text)
            except:
                error_message = error_text
            
            raise BuildingConnectedError(response.status_code, error_message, error_text)
        
        # Handle empty responses
        if not response.text.strip():
            logger.warning("⚠️  Empty response received")
            return {}
        
        logger.debug(f"✅ Successful API response ({len(response.text)} chars)")
        return response.json()
    
    async def get_user_info(self) -> UserInfo:
        """
        Get authenticated user information
        
        Returns:
            UserInfo with authentication status and details
        """
        logger.info("👤 Getting user information")
        try:
            # Get user profile from the correct endpoint
            response = await self._make_request('GET', 'users/me')
            
            user_info = UserInfo(
                id=response.get('id'),
                email=response.get('email'),
                name=f"{response.get('firstName', '')} {response.get('lastName', '')}".strip(),
                company=response.get('companyId'),
                authenticated=True
            )
            
            logger.info(f"✅ User info retrieved: {user_info.name} ({user_info.email})")
            return user_info
            
        except BuildingConnectedError as e:
            logger.error(f"❌ BuildingConnected API error in get_user_info: {e.status_code} - {e.message}")
            if e.status_code == 401:
                return UserInfo(authenticated=False)
            raise
        except Exception as e:
            logger.error(f"❌ General error in get_user_info: {e}")
            return UserInfo(authenticated=False)
    
    async def get_all_projects(self, limit: int = 100) -> List[Project]:
        """
        Get all BuildingConnected projects
        
        Args:
            limit: Maximum number of projects to return
            
        Returns:
            List of Project objects
        """
        logger.info(f"📋 Getting all projects (limit: {limit})")
        try:
            params = {
                'limit': str(min(limit, 200))  # API max limit
            }
            
            response = await self._make_request('GET', 'projects', params=params)
            
            projects = []
            if response.get('results') and isinstance(response['results'], list):
                logger.info(f"📋 Processing {len(response['results'])} projects from API")
                for project_data in response['results']:
                    project = Project(
                        id=project_data.get('id', ''),
                        name=project_data.get('name', ''),
                        bidsDueAt=project_data.get('bidsDueAt'),
                        state=project_data.get('state'),
                        isBiddingSealed=project_data.get('isBiddingSealed'),
                        description=project_data.get('description'),
                        location=project_data.get('location')
                    )
                    projects.append(project)
                    logger.debug(f"  - {project.name} (ID: {project.id})")
            else:
                logger.warning("⚠️  No projects found in API response")
            
            logger.info(f"✅ Retrieved {len(projects)} projects")
            return projects
            
        except BuildingConnectedError:
            raise
        except Exception as e:
            raise BuildingConnectedError(500, f"Unexpected error getting projects: {str(e)}")
    
    async def get_projects_due_in_n_days(self, days: int) -> ProjectsDueResponse:
        """
        Get projects with bid due dates exactly N days from today
        
        Args:
            days: Number of days from today (0-365)
            
        Returns:
            ProjectsDueResponse with filtered projects and metadata
        """
        logger.info(f"📅 Getting projects due in {days} days")
        
        if not (0 <= days <= 365):
            logger.error(f"❌ Invalid days value: {days} (must be 0-365)")
            raise ValueError("Days must be between 0 and 365")
        
        try:
            # Calculate target date (N days from now)
            target_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            target_date += timedelta(days=days)
            
            target_date_end = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            logger.info(f"🎯 Target date range: {target_date.strftime('%Y-%m-%d')} to {target_date_end.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Get all projects first
            logger.info("📋 Fetching all projects to filter by date")
            all_projects = await self.get_all_projects()
            logger.info(f"📋 Retrieved {len(all_projects)} total projects for filtering")
            
            # Filter projects that are due exactly on the target date
            projects_due_on_target_date = []
            
            logger.info("🔍 Filtering projects by target date")
            for project in all_projects:
                if not project.bidsDueAt:
                    logger.debug(f"  - Skipping {project.name}: No bid due date")
                    continue
                
                try:
                    # Parse the bid due date
                    bid_due_date = datetime.fromisoformat(
                        project.bidsDueAt.replace('Z', '+00:00')
                    ).replace(tzinfo=None)  # Convert to naive datetime for comparison
                    
                    # Check if bid due date falls within the target day
                    if target_date <= bid_due_date <= target_date_end:
                        projects_due_on_target_date.append(project)
                        logger.info(f"  ✅ Match: {project.name} due {bid_due_date.strftime('%Y-%m-%d %H:%M')}")
                    else:
                        logger.debug(f"  - Skip: {project.name} due {bid_due_date.strftime('%Y-%m-%d %H:%M')} (outside range)")
                        
                except (ValueError, AttributeError) as e:
                    # Skip projects with invalid date formats
                    logger.warning(f"  ⚠️  Invalid date format for {project.name}: {project.bidsDueAt} - {e}")
                    continue
            
            response = ProjectsDueResponse(
                projects=projects_due_on_target_date,
                targetDate=target_date.strftime('%Y-%m-%d'),
                daysFromNow=days,
                total=len(projects_due_on_target_date),
                timestamp=datetime.now().isoformat()
            )
            
            logger.info(f"✅ Found {len(projects_due_on_target_date)} projects due in {days} days")
            return response
            
        except BuildingConnectedError:
            raise
        except Exception as e:
            logger.error(f"❌ Unexpected error filtering projects: {str(e)}")
            raise BuildingConnectedError(500, f"Unexpected error filtering projects: {str(e)}")
    
    async def get_project_details(self, project_id: str) -> Optional[Project]:
        """
        Get detailed information about a specific project
        
        Args:
            project_id: The project ID
            
        Returns:
            Project object with details or None if not found
        """
        try:
            response = await self._make_request('GET', f'projects/{project_id}')
            
            return Project(
                id=response.get('id', ''),
                name=response.get('name', ''),
                bidsDueAt=response.get('bidsDueAt'),
                state=response.get('state'),
                isBiddingSealed=response.get('isBiddingSealed'),
                description=response.get('description'),
                location=response.get('location')
            )
            
        except BuildingConnectedError as e:
            if e.status_code == 404:
                return None
            raise
        except Exception as e:
            raise BuildingConnectedError(500, f"Unexpected error getting project details: {str(e)}")
    
    async def get_project_invitations(self, project_id: str) -> Dict[str, Any]:
        """
        Get bidding invitations for a specific project
        
        Args:
            project_id: The project ID
            
        Returns:
            Dictionary with invitation data
        """
        try:
            # Note: This endpoint may not exist in the actual API
            # This is a placeholder based on the original MCP implementation
            response = await self._make_request('GET', f'projects/{project_id}/invitations')
            return response
            
        except BuildingConnectedError as e:
            if e.status_code == 404:
                return {"message": f"No invitations found for project {project_id}"}
            raise
        except Exception as e:
            raise BuildingConnectedError(500, f"Unexpected error getting project invitations: {str(e)}")
        
    async def get_bidding_invitations(self, project_id: str) -> List[BiddingInvitationData]:
        """
        Get comprehensive bidding invitations for a specific project
        
        This method:
        1. Gets project details to extract bid due date
        2. Gets all bid packages for the project (with pagination)
        3. For each bid package, gets all invites (with pagination)
        4. Processes each invite to extract invitation data
        
        Args:
            project_id: The project ID
            
        Returns:
            List of BiddingInvitationData objects
        """
        logger.info(f"🎯 Generating bidding invitations for project {project_id}")
        
        if not project_id or not isinstance(project_id, str):
            raise ValueError("project_id is required and must be a string")
        
        try:
            # Step 1: Get project details to extract bid due date
            logger.info(f"📋 Fetching project details for project {project_id}")
            project_data = await self._make_request('GET', f'projects/{project_id}')
            
            # Extract bid due date and calculate days until due
            bids_due_at = project_data.get('bidsDueAt', '')
            days_until_bids_due = 0
            
            if bids_due_at:
                try:
                    bids_due_date = datetime.fromisoformat(bids_due_at.replace('Z', '+00:00')).replace(tzinfo=None)
                    now = datetime.now()
                    time_diff = bids_due_date - now
                    days_until_bids_due = math.ceil(time_diff.total_seconds() / (24 * 3600))
                except (ValueError, AttributeError) as e:
                    logger.warning(f"⚠️  Invalid bid due date format: {bids_due_at} - {e}")
            
            logger.info(f"📅 Bids due at: {bids_due_at}, Days until due: {days_until_bids_due}")
            
            # Step 2: Get all bid packages for the project
            logger.info("📦 Fetching bid packages for project")
            all_bid_packages = []
            next_bid_package_url = f"bid-packages?filter[projectId]={project_id}"
            bid_package_page_count = 0
            
            while next_bid_package_url:
                bid_package_page_count += 1
                logger.info(f"📦 Fetching bid packages page {bid_package_page_count}")
                
                try:
                    bid_package_data = await self._make_request('GET', next_bid_package_url)
                    
                    # Parse response using Pydantic model
                    bid_package_response = BidPackageApiResponse(**bid_package_data)
                    logger.info(f"✅ Successfully fetched page {bid_package_page_count} with {len(bid_package_response.results)} bid packages")
                    
                    all_bid_packages.extend(bid_package_response.results)
                    
                    # Handle pagination
                    if bid_package_response.pagination.nextUrl:
                        raw_next_url = bid_package_response.pagination.nextUrl
                        if raw_next_url.startswith('/'):
                            next_bid_package_url = raw_next_url[1:]  # Remove leading slash for our _make_request method
                        elif raw_next_url.startswith('http'):
                            # Extract path from full URL
                            next_bid_package_url = raw_next_url.split('/construction/buildingconnected/v2/')[-1]
                        else:
                            next_bid_package_url = raw_next_url
                    else:
                        next_bid_package_url = None
                    
                    if bid_package_page_count > 50:
                        logger.warning("⚠️  Reached maximum page limit (50) for bid packages")
                        break
                        
                except BuildingConnectedError as e:
                    logger.error(f"❌ Bid Package API error: {e.status_code} - {e.message}")
                    break
            
            logger.info(f"📦 Total bid packages found: {len(all_bid_packages)}")
            
            # Step 3: For each bid package, get all invites and generate invitation data
            all_invitation_data = []
            
            for bid_package in all_bid_packages:
                bid_package_id = bid_package.id
                bid_package_name = bid_package.name
                
                logger.info(f"🎪 Processing bid package: {bid_package_name} ({bid_package_id})")
                
                # Get all invites for this bid package
                next_invite_url = f"invites?filter[projectId]={project_id}&filter[bidPackageId]={bid_package_id}"
                invite_page_count = 0
                
                while next_invite_url:
                    invite_page_count += 1
                    logger.info(f"📧 Fetching invites page {invite_page_count} for bid package {bid_package_id}")
                    
                    try:
                        invite_data = await self._make_request('GET', next_invite_url)
                        
                        # Save raw invite data to JSON file for debugging
                        try:
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            filename = f"invite_data_{project_id}_{bid_package_id}_page{invite_page_count}_{timestamp}.json"
                            filepath = os.path.join("logs", filename)
                            
                            # Create logs directory if it doesn't exist
                            os.makedirs("logs", exist_ok=True)
                            
                            with open(filepath, 'w') as f:
                                json.dump(invite_data, f, indent=2)
                            
                            logger.info(f"💾 Saved invite data to: {filepath}")
                        except Exception as save_error:
                            logger.warning(f"⚠️  Failed to save invite data to JSON: {save_error}")
                        
                        # Parse response using Pydantic model
                        invite_response = InviteApiResponse(**invite_data)
                        logger.info(f"✅ Successfully fetched page {invite_page_count} with {len(invite_response.results)} invites")
                        
                        # Process only the FIRST invite to avoid double-counting people
                        if invite_response.results:
                            invite = invite_response.results[0]  # Only process the first invite
                            logger.debug(f"  Processing first invite {invite.id} (out of {len(invite_response.results)} total invites)")
                            
                            # Process ALL invitees in this first invite
                            if invite.invitees and len(invite.invitees) > 0:
                                logger.debug(f"  Processing {len(invite.invitees)} invitees for invite {invite.id}")
                                
                                for current_invitee in invite.invitees:
                                    invitation_data = BiddingInvitationData(
                                        id=invite.id,
                                        state=current_invitee.state,
                                        projectId=invite.projectId,
                                        bidPackageId=invite.bidPackageId,
                                        bidPackageName=bid_package_name,
                                        bidsDueAt=bids_due_at,
                                        daysUntilBidsDue=days_until_bids_due,
                                        userId=current_invitee.userId,
                                        firstName=current_invitee.firstName or '',
                                        lastName=current_invitee.lastName or '',
                                        title=current_invitee.title or '',
                                        email=current_invitee.email,
                                        linkToBid=f"https://app.buildingconnected.com/opportunities/{invite.id}/info"
                                    )
                                    
                                    all_invitation_data.append(invitation_data)
                                    logger.debug(f"    - Added: {current_invitee.firstName} {current_invitee.lastName} ({current_invitee.email})")
                            else:
                                logger.debug(f"  No invitees found for invite {invite.id}")
                        else:
                            logger.debug(f"  No invites found in this page")
                        
                        # Handle pagination
                        if invite_response.pagination.nextUrl:
                            raw_next_url = invite_response.pagination.nextUrl
                            if raw_next_url.startswith('/'):
                                next_invite_url = raw_next_url[1:]  # Remove leading slash for our _make_request method
                            elif raw_next_url.startswith('http'):
                                # Extract path from full URL
                                next_invite_url = raw_next_url.split('/construction/buildingconnected/v2/')[-1]
                            else:
                                next_invite_url = raw_next_url
                        else:
                            next_invite_url = None
                        
                        if invite_page_count > 50:
                            logger.warning("⚠️  Reached maximum page limit (50) for invites")
                            break
                            
                    except BuildingConnectedError as e:
                        logger.error(f"❌ Invite API error: {e.status_code} - {e.message}")
                        break
            
            logger.info(f"🎯 Generated {len(all_invitation_data)} bidding invitation records")
            
            # Log the raw invitation data for debugging
            logger.debug("=== BIDDING INVITATION DATA ===")
            for invitation in all_invitation_data:
                logger.debug(f"  - {invitation.firstName} {invitation.lastName} ({invitation.email}) - {invitation.bidPackageName}")
            logger.debug("=== END BIDDING INVITATION DATA ===")
            
            return all_invitation_data
            
        except BuildingConnectedError:
            raise
        except Exception as e:
            logger.error(f"❌ Unexpected error generating bidding invitations: {str(e)}")
            raise BuildingConnectedError(500, f"Unexpected error generating bidding invitations: {str(e)}")