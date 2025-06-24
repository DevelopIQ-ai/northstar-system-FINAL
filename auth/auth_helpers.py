"""
Authentication helpers for Microsoft Graph API and BuildingConnected/Autodesk API access
Ported from TypeScript implementation for deterministic API access
"""

import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from pydantic import BaseModel
from dotenv import load_dotenv

# Import the new JSON token storage
from .token_storage import TokenStorage

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# Initialize global token storage
token_storage = TokenStorage()


class TokenData(BaseModel):
    """Token storage model"""
    access_token: str
    expires_at: int  # Unix timestamp in milliseconds
    refresh_token: Optional[str] = None


class TokenManager:
    """Base token manager class for OAuth2 flows"""
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        encryption_key: str,
        token_url: str,
        scope: str,
        encrypted_refresh_token: str = None  # Made optional - we only use tokens.json now
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.encrypted_refresh_token = encrypted_refresh_token  # Legacy field, not used anymore
        self.encryption_key = encryption_key
        self.token_url = token_url
        self.scope = scope
        self._cached_token: Optional[TokenData] = None
        self._refresh_lock = asyncio.Semaphore(1)  # Prevent concurrent refreshes
    
    async def decrypt_refresh_token(self) -> str:
        """Load refresh token from JSON storage only (no .env fallback)"""
        try:
            # Determine service name based on token manager type
            service_name = 'autodesk' if isinstance(self, BuildingConnectedTokenManager) else 'microsoft'
            
            # Load from JSON storage only
            token = token_storage.load_refresh_token(service_name, self.encryption_key)
            
            if token:
                logger.info(f"✅ Loaded {service_name} token from JSON storage (length: {len(token)})")
                return token
            else:
                raise ValueError(f"No refresh token found in tokens.json for {service_name}. Please run setup_bid_reminder.py to configure authentication.")
            
        except Exception as e:
            raise ValueError(f"Failed to load refresh token from tokens.json: {str(e)}")
    
    async def get_access_token(self) -> str:
        """Get valid access token, refreshing if necessary"""
        service_name = 'autodesk' if isinstance(self, BuildingConnectedTokenManager) else 'microsoft'
        
        # Check if cached token is still valid (with 60 second buffer)
        if (self._cached_token and 
            datetime.now(timezone.utc).timestamp() * 1000 < self._cached_token.expires_at - 60_000):
            logger.info(f"🔄 Using cached {service_name} token (expires at: {datetime.fromtimestamp(self._cached_token.expires_at/1000, tz=timezone.utc)})")
            return self._cached_token.access_token
        
        # Use semaphore to prevent concurrent refresh attempts
        async with self._refresh_lock:
            # Double-check in case another coroutine refreshed while we waited
            if (self._cached_token and 
                datetime.now(timezone.utc).timestamp() * 1000 < self._cached_token.expires_at - 60_000):
                return self._cached_token.access_token
            
            # Refresh token
            refresh_token = await self.decrypt_refresh_token()
            
            token_data = {
                'client_id': self.client_id,
                'client_secret': self.client_secret, 
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
                'scope': self.scope
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:

                response = await client.post(
                    self.token_url,
                    data=token_data,
                    headers={'Content-Type': 'application/x-www-form-urlencoded'}
                )
                
                if response.status_code != 200:
                    error_details = f"Token refresh failed: {response.status_code} - {response.text}"
                    
                    # For BuildingConnected, provide more specific error guidance
                    if isinstance(self, BuildingConnectedTokenManager) and "invalid_grant" in response.text:
                        error_details += "\n\nBuildingConnected refresh token has expired or been invalidated."
                        error_details += "\nThis commonly happens because:"
                        error_details += "\n1. Refresh token expired (14-day limit)"
                        error_details += "\n2. Multiple concurrent refresh attempts"
                        error_details += "\n3. User re-authenticated in another app"
                        error_details += "\n\nTo fix: Run 'python -c \"import asyncio; from auth.oauth_setup import setup_autodesk_auth_flow; asyncio.run(setup_autodesk_auth_flow())\"'"
                    
                    raise ValueError(error_details)
                
                token_response = response.json()
                
                # Cache the new token
                expires_in = token_response.get('expires_in', 3600)  # Default 1 hour
                expires_at = int(datetime.now(timezone.utc).timestamp() * 1000) + (expires_in * 1000)
                
                self._cached_token = TokenData(
                    access_token=token_response['access_token'],
                    expires_at=expires_at,
                    refresh_token=token_response.get('refresh_token')  # May update
                )
                
                # Debug logging for token refresh
                print(f"🔑 Token refresh successful for {self.__class__.__name__}")
                print(f"   Access token: {self._cached_token.access_token[:20]}...")
                print(f"   Expires at: {datetime.fromtimestamp(expires_at/1000)}")
                if self._cached_token.refresh_token:
                    print(f"   New refresh token provided: {self._cached_token.refresh_token[:20]}...")
                    print(f"   Old refresh token was: {refresh_token[:20]}...")
                else:
                    print("   No new refresh token provided")
                
                # Update stored refresh token if a new one was provided (Autodesk rotates refresh tokens)
                if self._cached_token.refresh_token and self._cached_token.refresh_token != refresh_token:
                    print("🔄 New refresh token detected - updating stored token")
                    await self._update_stored_refresh_token(self._cached_token.refresh_token)
                else:
                    print("📝 No token rotation needed (same refresh token)")
                
                return self._cached_token.access_token
    
    async def _update_stored_refresh_token(self, new_refresh_token: str) -> None:
        """Update the stored refresh token using JSON storage only"""
        try:
            logger.info(f"🔄 Updating stored refresh token for {type(self).__name__}")
            logger.info(f"🔐 New refresh token length: {len(new_refresh_token)}")
            
            # Determine service name based on token manager type
            service_name = 'autodesk' if isinstance(self, BuildingConnectedTokenManager) else 'microsoft'
            
            # Determine which env var to update based on token manager type
            if isinstance(self, BuildingConnectedTokenManager):
                env_var = 'AUTODESK_ENCRYPTED_REFRESH_TOKEN'
            else:
                env_var = 'ENCRYPTED_REFRESH_TOKEN'
            
            # Log the token rotation for debugging
            print(f"🔄 Token rotation: Updating {env_var} in .env file AND runtime environment")
            print(f"   Old token: {self.encrypted_refresh_token[:20]}...")
            print(f"   New token: {encrypted_token[:20]}...")
            
            # Update .env file for persistence
            set_key('.env', env_var, encrypted_token)
            
            # CRITICAL: Also update the current process environment variables
            # This ensures subsequent requests in the same server process use the new token
            os.environ[env_var] = encrypted_token
            print(f"   ✅ Updated both .env file and runtime environment for {env_var}")
            
            # Update instance variable
            self.encrypted_refresh_token = encrypted_token
            
            print(f"✅ Token rotation completed for {env_var}")
            
        except Exception as e:
            # Log the error but don't fail the token refresh

            print(f"❌ Warning: Failed to update stored refresh token: {str(e)}")
            import traceback
            traceback.print_exc()


class MSGraphTokenManager(TokenManager):
    """Microsoft Graph API token management"""
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        encryption_key: str
    ):
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            encryption_key=encryption_key,
            token_url=os.getenv('MICROSOFT_TOKEN_URL', 'https://login.microsoftonline.com/common/oauth2/v2.0/token'),
            scope=os.getenv('MICROSOFT_SCOPE', 'Mail.Read Mail.Send Mail.ReadWrite')
        )


class BuildingConnectedTokenManager(TokenManager):
    """BuildingConnected/Autodesk Construction API token management"""
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        encryption_key: str
    ):
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            encryption_key=encryption_key,
            token_url=os.getenv('AUTODESK_TOKEN_URL', 'https://developer.api.autodesk.com/authentication/v2/token'),
            scope=os.getenv('AUTODESK_SCOPE', 'user-profile:read data:read data:write account:read account:write')
        )


class EmailValidator:
    """Email validation utilities"""
    
    @staticmethod
    def is_valid_email(email: str) -> bool:
        """Validate email address format"""
        import re
        pattern = r'^[a-zA-Z0-9.!#$%&\'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$'
        return re.match(pattern, email) is not None
    
    @staticmethod
    def format_recipients(email_list: str, field_name: str = 'recipients') -> list[Dict[str, Any]]:
        """Format comma-separated email list for Microsoft Graph API"""
        if not email_list:
            return []
        
        recipients = []
        for email in email_list.split(','):
            email = email.strip()
            
            if not EmailValidator.is_valid_email(email):
                raise ValueError(f"Invalid email address in {field_name}: {email}")
            
            recipients.append({
                'emailAddress': {
                    'address': email
                }
            })
        
        return recipients


def create_token_manager_from_env() -> MSGraphTokenManager:
    """Create Microsoft Graph token manager from environment variables (client credentials only)"""
    required_vars = [
        'MS_CLIENT_ID',
        'MS_CLIENT_SECRET',
        'ENCRYPTION_KEY'
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    return MSGraphTokenManager(
        client_id=os.getenv('MS_CLIENT_ID'),
        client_secret=os.getenv('MS_CLIENT_SECRET'),
        encryption_key=os.getenv('ENCRYPTION_KEY')
    )


def create_buildingconnected_token_manager_from_env() -> BuildingConnectedTokenManager:
    """Create BuildingConnected token manager from environment variables (client credentials only)"""
    required_vars = [
        'AUTODESK_CLIENT_ID',
        'AUTODESK_CLIENT_SECRET',
        'AUTODESK_ENCRYPTION_KEY'
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(f"Missing required BuildingConnected environment variables: {', '.join(missing_vars)}")
    
    return BuildingConnectedTokenManager(
        client_id=os.getenv('AUTODESK_CLIENT_ID'),
        client_secret=os.getenv('AUTODESK_CLIENT_SECRET'),
        encryption_key=os.getenv('AUTODESK_ENCRYPTION_KEY')
    )