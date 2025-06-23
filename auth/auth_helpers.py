"""
Authentication helpers for Microsoft Graph API and BuildingConnected/Autodesk API access
Ported from TypeScript implementation for deterministic API access
"""

import asyncio
import base64
import json
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


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
        encrypted_refresh_token: str,
        encryption_key: str,
        token_url: str,
        scope: str
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.encrypted_refresh_token = encrypted_refresh_token
        self.encryption_key = encryption_key
        self.token_url = token_url
        self.scope = scope
        self._cached_token: Optional[TokenData] = None
    
    async def decrypt_refresh_token(self) -> str:
        """Decrypt the stored refresh token using AES-CBC"""
        try:
            # Parse the encrypted data format: iv:encrypted
            iv_hex, encrypted_hex = self.encrypted_refresh_token.split(':')
            
            # Convert hex strings to bytes
            iv = bytes.fromhex(iv_hex)
            encrypted = bytes.fromhex(encrypted_hex)
            
            # Create key from encryption key string using SHA-256
            import hashlib
            key_hash = hashlib.sha256(self.encryption_key.encode()).digest()
            
            # Decrypt using AES-CBC
            cipher = Cipher(
                algorithms.AES(key_hash),
                modes.CBC(iv),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            decrypted = decryptor.update(encrypted) + decryptor.finalize()
            
            # Remove PKCS7 padding
            padding_length = decrypted[-1]
            return decrypted[:-padding_length].decode('utf-8')
            
        except Exception as e:
            raise ValueError(f"Failed to decrypt refresh token: {str(e)}")
    
    async def get_access_token(self) -> str:
        """Get valid access token, refreshing if necessary"""
        # Check if cached token is still valid (with 60 second buffer)
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
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.token_url,
                data=token_data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            if response.status_code != 200:
                raise ValueError(f"Token refresh failed: {response.status_code} - {response.text}")
            
            token_response = response.json()
            
            # Cache the new token
            expires_in = token_response.get('expires_in', 3600)  # Default 1 hour
            expires_at = int(datetime.now(timezone.utc).timestamp() * 1000) + (expires_in * 1000)
            
            self._cached_token = TokenData(
                access_token=token_response['access_token'],
                expires_at=expires_at,
                refresh_token=token_response.get('refresh_token')  # May update
            )
            
            # Update stored refresh token if a new one was provided (Autodesk rotates refresh tokens)
            if self._cached_token.refresh_token and self._cached_token.refresh_token != refresh_token:
                await self._update_stored_refresh_token(self._cached_token.refresh_token)
            
            return self._cached_token.access_token
    
    async def _update_stored_refresh_token(self, new_refresh_token: str) -> None:
        """Update the stored refresh token with new encrypted value"""
        try:
            # Encrypt the new refresh token
            encrypted_token = self._encrypt_token(new_refresh_token)
            
            # Update environment variable in .env file
            from dotenv import set_key
            
            # Determine which env var to update based on token manager type
            if isinstance(self, BuildingConnectedTokenManager):
                env_var = 'AUTODESK_ENCRYPTED_REFRESH_TOKEN'
            else:
                env_var = 'ENCRYPTED_REFRESH_TOKEN'
            
            set_key('.env', env_var, encrypted_token)
            
            # Update instance variable
            self.encrypted_refresh_token = encrypted_token
            
        except Exception as e:
            # Log the error but don't fail the token refresh
            print(f"Warning: Failed to update stored refresh token: {str(e)}")
    
    def _encrypt_token(self, token: str) -> str:
        """Encrypt a token using AES-CBC (same logic as oauth_setup.py)"""
        import os
        import hashlib
        
        # Generate random IV
        iv = os.urandom(16)
        
        # Create key from encryption key string using SHA-256
        key_hash = hashlib.sha256(self.encryption_key.encode()).digest()
        
        # Pad the token to 16-byte boundary (PKCS7 padding)  
        token_bytes = token.encode('utf-8')
        padding_length = 16 - (len(token_bytes) % 16)
        padded_token = token_bytes + bytes([padding_length] * padding_length)
        
        # Encrypt using AES-CBC
        cipher = Cipher(
            algorithms.AES(key_hash),
            modes.CBC(iv),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(padded_token) + encryptor.finalize()
        
        # Return IV and encrypted data as hex strings separated by colon
        return f"{iv.hex()}:{encrypted.hex()}"


class MSGraphTokenManager(TokenManager):
    """Microsoft Graph API token management"""
    
    def __init__(
        self,
        client_id: str,
        client_secret: str, 
        encrypted_refresh_token: str,
        encryption_key: str
    ):
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            encrypted_refresh_token=encrypted_refresh_token,
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
        encrypted_refresh_token: str,
        encryption_key: str
    ):
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            encrypted_refresh_token=encrypted_refresh_token,
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
    """Create Microsoft Graph token manager from environment variables"""
    required_vars = [
        'MS_CLIENT_ID',
        'MS_CLIENT_SECRET', 
        'ENCRYPTED_REFRESH_TOKEN',
        'ENCRYPTION_KEY'
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    return MSGraphTokenManager(
        client_id=os.getenv('MS_CLIENT_ID'),
        client_secret=os.getenv('MS_CLIENT_SECRET'),
        encrypted_refresh_token=os.getenv('ENCRYPTED_REFRESH_TOKEN'),
        encryption_key=os.getenv('ENCRYPTION_KEY')
    )


def create_buildingconnected_token_manager_from_env() -> BuildingConnectedTokenManager:
    """Create BuildingConnected token manager from environment variables"""
    required_vars = [
        'AUTODESK_CLIENT_ID',
        'AUTODESK_CLIENT_SECRET',
        'AUTODESK_ENCRYPTED_REFRESH_TOKEN',
        'AUTODESK_ENCRYPTION_KEY'
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(f"Missing required BuildingConnected environment variables: {', '.join(missing_vars)}")
    
    return BuildingConnectedTokenManager(
        client_id=os.getenv('AUTODESK_CLIENT_ID'),
        client_secret=os.getenv('AUTODESK_CLIENT_SECRET'),
        encrypted_refresh_token=os.getenv('AUTODESK_ENCRYPTED_REFRESH_TOKEN'),
        encryption_key=os.getenv('AUTODESK_ENCRYPTION_KEY')
    )