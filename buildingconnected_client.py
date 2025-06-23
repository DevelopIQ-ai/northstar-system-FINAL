"""
Deterministic BuildingConnected/Autodesk Construction API client  
Direct API access without MCP protocol overhead
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from enum import Enum

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
            'Authorization': f'Bearer {access_token[:20]}...',  # Log partial token for security
            'Content-Type': 'application/json'
        }
        
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
        try:
            params = {
                'limit': str(min(limit, 200))  # API max limit
            }
            
            response = await self._make_request('GET', 'projects', params=params)
            
            projects = []
            if response.get('results') and isinstance(response['results'], list):
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
        if not (0 <= days <= 365):
            raise ValueError("Days must be between 0 and 365")
        
        try:
            # Calculate target date (N days from now)
            target_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            target_date += timedelta(days=days)
            
            target_date_end = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            # Get all projects first
            all_projects = await self.get_all_projects()
            
            # Filter projects that are due exactly on the target date
            projects_due_on_target_date = []
            
            for project in all_projects:
                if not project.bidsDueAt:
                    continue
                
                try:
                    # Parse the bid due date
                    bid_due_date = datetime.fromisoformat(
                        project.bidsDueAt.replace('Z', '+00:00')
                    ).replace(tzinfo=None)  # Convert to naive datetime for comparison
                    
                    # Check if bid due date falls within the target day
                    if target_date <= bid_due_date <= target_date_end:
                        projects_due_on_target_date.append(project)
                        
                except (ValueError, AttributeError):
                    # Skip projects with invalid date formats
                    continue
            
            return ProjectsDueResponse(
                projects=projects_due_on_target_date,
                targetDate=target_date.strftime('%Y-%m-%d'),
                daysFromNow=days,
                total=len(projects_due_on_target_date),
                timestamp=datetime.now().isoformat()
            )
            
        except BuildingConnectedError:
            raise
        except Exception as e:
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