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
        
        # Refresh token
        logger.info(f"🔄 Refreshing token for {type(self).__name__}")
        logger.info(f"🔍 Token refresh needed for {service_name} service")
        
        # Log current token info
        token_info = token_storage.get_token_info(service_name)
        if token_info['exists']:
            logger.info(f"📊 Current {service_name} token info:")
            logger.info(f"   Last updated: {token_info['last_updated']}")
            logger.info(f"   Token length: {token_info['token_length']}")
        else:
            logger.info(f"⚠️ No {service_name} token found in storage")
        
        try:
            refresh_token = await self.decrypt_refresh_token()
            logger.info(f"✅ Successfully decrypted refresh token (length: {len(refresh_token)})")
            logger.info(f"🔍 Refresh token preview: {refresh_token[:10]}...{refresh_token[-10:]}")
        except Exception as decrypt_error:
            logger.error(f"❌ Failed to decrypt refresh token: {str(decrypt_error)}")
            raise ValueError(f"Failed to decrypt refresh token: {str(decrypt_error)}")
        
        # Build token refresh request
        token_data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret, 
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
        }
        
        # Add scope for Autodesk (they seem to require it in refresh requests)
        if isinstance(self, BuildingConnectedTokenManager):
            # Use a more specific scope for refresh - Autodesk examples show simpler scopes work better
            token_data['scope'] = 'data:read data:write'
            logger.info(f"🏗️ Autodesk refresh with scope: {token_data['scope']}")
        else:
            token_data['scope'] = self.scope
            logger.info(f"📧 Microsoft refresh with scope: {token_data['scope']}")
        
        logger.info(f"🔗 Token URL: {self.token_url}")
        logger.info(f"📋 Request data (client_secret masked): {dict(token_data, client_secret='***')}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    self.token_url,
                    data=token_data,
                    headers={'Content-Type': 'application/x-www-form-urlencoded'}
                )
                
                logger.info(f"📊 Response status: {response.status_code}")
                logger.debug(f"📋 Response headers: {dict(response.headers)}")
                
                if response.status_code != 200:
                    logger.error(f"❌ Token refresh failed with status {response.status_code}")
                    logger.error(f"❌ Response body: {response.text}")
                    
                    # For Autodesk, try the alternative v1 refresh endpoint if v2 fails
                    if isinstance(self, BuildingConnectedTokenManager) and 'v2' in self.token_url:
                        logger.info("🔄 Trying alternative Autodesk v1 refresh endpoint...")
                        v1_url = self.token_url.replace('/v2/token', '/v1/refreshtoken')
                        
                        v1_response = await client.post(
                            v1_url,
                            data=token_data,
                            headers={'Content-Type': 'application/x-www-form-urlencoded'}
                        )
                        
                        logger.info(f"📊 V1 Response status: {v1_response.status_code}")
                        if v1_response.status_code == 200:
                            response = v1_response
                            logger.info("✅ V1 endpoint worked! Updating token URL for future use.")
                            # Update the token URL for future requests
                            self.token_url = v1_url
                        else:
                            logger.error(f"❌ V1 endpoint also failed: {v1_response.text}")
                    
                    if response.status_code != 200:
                        raise ValueError(f"Token refresh failed: {response.status_code} - {response.text}")
                
                token_response = response.json()
                logger.info(f"✅ Token refresh successful")
                
                # Cache the new token
                expires_in = token_response.get('expires_in', 3600)  # Default 1 hour
                expires_at = int(datetime.now(timezone.utc).timestamp() * 1000) + (expires_in * 1000)
                
                logger.info(f"🕐 New token expires in: {expires_in} seconds")
                
                self._cached_token = TokenData(
                    access_token=token_response['access_token'],
                    expires_at=expires_at,
                    refresh_token=token_response.get('refresh_token')  # May update
                )
                
                # Update stored refresh token if a new one was provided (Autodesk rotates refresh tokens)
                if self._cached_token.refresh_token and self._cached_token.refresh_token != refresh_token:
                    logger.info("🔄 New refresh token received, updating stored token")
                    logger.info(f"🔍 Old refresh token: {refresh_token[:10]}...{refresh_token[-10:]}")
                    logger.info(f"🔍 New refresh token: {self._cached_token.refresh_token[:10]}...{self._cached_token.refresh_token[-10:]}")
                    logger.info(f"🔄 TOKEN ROTATION DETECTED for {service_name}")
                    await self._update_stored_refresh_token(self._cached_token.refresh_token)
                else:
                    logger.info(f"ℹ️ Same refresh token returned for {service_name} (no rotation)")
                
                return self._cached_token.access_token
                
            except httpx.RequestError as req_error:
                raise ValueError(f"Network error during token refresh: {str(req_error)}")
            except Exception as parse_error:
                raise ValueError(f"Error parsing token response: {str(parse_error)}")
    
    async def _update_stored_refresh_token(self, new_refresh_token: str) -> None:
        """Update the stored refresh token using JSON storage only"""
        try:
            logger.info(f"🔄 Updating stored refresh token for {type(self).__name__}")
            logger.info(f"🔐 New refresh token length: {len(new_refresh_token)}")
            
            # Determine service name based on token manager type
            service_name = 'autodesk' if isinstance(self, BuildingConnectedTokenManager) else 'microsoft'
            
            # Save to JSON storage only
            success = token_storage.save_refresh_token(service_name, new_refresh_token, self.encryption_key)
            
            if success:
                logger.info(f"✅ Successfully updated {service_name} refresh token in JSON storage")
                
                # Verify the save by immediately reading it back
                verification_token = token_storage.load_refresh_token(service_name, self.encryption_key)
                if verification_token == new_refresh_token:
                    logger.info(f"✅ Token save verification successful - tokens match")
                else:
                    logger.error(f"❌ Token save verification failed - tokens don't match!")
                    logger.error(f"   Original length: {len(new_refresh_token)}")
                    logger.error(f"   Verified length: {len(verification_token) if verification_token else 'None'}")
                
            else:
                logger.error(f"❌ Failed to update {service_name} refresh token in JSON storage")
            
        except Exception as e:
            # Log the error but don't fail the token refresh
            logger.error(f"❌ Failed to update stored refresh token: {str(e)}")
            logger.error(f"❌ Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
    



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