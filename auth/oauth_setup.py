#!/usr/bin/env python3
"""
OAuth setup helpers for Microsoft Graph and Autodesk/BuildingConnected APIs
Handles the complete OAuth flow including token encryption
"""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv, set_key

# Load environment variables
load_dotenv()

# =============================================================================
# CONFIGURATION CONSTANTS - Read from environment with defaults
# =============================================================================

# Microsoft OAuth Configuration
MICROSOFT_AUTH_URL = os.getenv("MICROSOFT_AUTH_URL", "https://login.microsoftonline.com/common/oauth2/v2.0/authorize")
MICROSOFT_TOKEN_URL = os.getenv("MICROSOFT_TOKEN_URL", "https://login.microsoftonline.com/common/oauth2/v2.0/token")
MICROSOFT_CALLBACK_PORT = int(os.getenv("MICROSOFT_CALLBACK_PORT", "3333"))
MICROSOFT_CALLBACK_PATH = os.getenv("MICROSOFT_CALLBACK_PATH", "/auth/callback")
MICROSOFT_SCOPE = os.getenv("MICROSOFT_SCOPE", "Mail.Read Mail.Send Mail.ReadWrite offline_access")

# Autodesk/BuildingConnected OAuth Configuration
AUTODESK_AUTH_URL = os.getenv("AUTODESK_AUTH_URL", "https://developer.api.autodesk.com/authentication/v2/authorize")
AUTODESK_TOKEN_URL = os.getenv("AUTODESK_TOKEN_URL", "https://developer.api.autodesk.com/authentication/v2/token")
AUTODESK_CALLBACK_PORT = int(os.getenv("AUTODESK_CALLBACK_PORT", "5173"))
AUTODESK_CALLBACK_PATH = os.getenv("AUTODESK_CALLBACK_PATH", "/oauth/callback")
AUTODESK_SCOPE = os.getenv("AUTODESK_SCOPE", "user-profile:read data:read data:write account:read account:write")

# OAuth Flow Configuration
OAUTH_TIMEOUT_SECONDS = int(os.getenv("OAUTH_TIMEOUT_SECONDS", "300"))  # 5 minutes

# =============================================================================


class OAuthCallbackHandler(SimpleHTTPRequestHandler):
    """HTTP server to handle OAuth callback"""
    
    def __init__(self, *args, **kwargs):
        self.auth_code = None
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        """Handle OAuth callback GET request"""
        parsed_path = urlparse(self.path)
        query_params = parse_qs(parsed_path.query)
        
        # Only handle /auth/callback or /oauth/callback paths
        if parsed_path.path not in ['/auth/callback', '/oauth/callback']:
            self.send_response(404)
            self.end_headers()
            return
        
        if 'code' in query_params:
            # Store the authorization code
            self.server.auth_code = query_params['code'][0]
            
            # Send success response
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            html_content = """
            <html>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: green;">Authentication Successful!</h1>
                <p>You can close this window and return to the terminal.</p>
            </body>
            </html>
            """
            self.wfile.write(html_content.encode('utf-8'))
        elif 'error' in query_params:
            error = query_params.get('error', ['unknown'])[0]
            error_description = query_params.get('error_description', ['No description'])[0]
            
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            error_html = f"""
            <html>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: red;">❌ Authentication Failed</h1>
                <p><strong>Error:</strong> {error}</p>
                <p><strong>Description:</strong> {error_description}</p>
                <p>Please close this window and try again.</p>
            </body>
            </html>
            """
            self.wfile.write(error_html.encode('utf-8'))
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            invalid_html = """
            <html>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: red;">❌ Invalid Callback</h1>
                <p>No authorization code received.</p>
            </body>
            </html>
            """
            self.wfile.write(invalid_html.encode('utf-8'))
    
    def log_message(self, format, *args):
        """Suppress server logs"""
        pass


def generate_encryption_key() -> str:
    """Generate a secure encryption key"""
    return secrets.token_hex(32)


def encrypt_token(token: str, encryption_key: str) -> str:
    """Encrypt a token using AES-CBC"""
    # Generate random IV
    iv = os.urandom(16)
    
    # Create key from encryption key string using SHA-256
    key_hash = hashlib.sha256(encryption_key.encode()).digest()
    
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


async def run_oauth_flow(
    auth_url: str,
    token_url: str,
    client_id: str,
    client_secret: str,
    callback_port: int = 3333,
    callback_path: str = "/auth/callback"
) -> Tuple[str, str]:
    """
    Run complete OAuth flow and return access_token and refresh_token
    """
    callback_url = f"http://localhost:{callback_port}{callback_path}"
    
    # Start local server for callback
    server = HTTPServer(('localhost', callback_port), OAuthCallbackHandler)
    server.auth_code = None
    
    print(f"🌐 Starting local server on port {callback_port}...")
    
    # Open browser for authentication
    print(f"🔓 Opening browser for authentication...")
    webbrowser.open(auth_url)
    
    # Wait for callback with timeout
    print("⏳ Waiting for authentication callback...")
    timeout_seconds = OAUTH_TIMEOUT_SECONDS
    
    def handle_request_with_timeout():
        server.timeout = 1  # Check every second
        start_time = datetime.now()
        
        while not server.auth_code:
            server.handle_request()
            if (datetime.now() - start_time).seconds > timeout_seconds:
                raise TimeoutError("OAuth callback timed out after 5 minutes")
        
        return server.auth_code
    
    try:
        auth_code = handle_request_with_timeout()
        server.server_close()
        
        if not auth_code:
            raise ValueError("No authorization code received")
        
        print("✅ Authorization code received!")
        
        # Exchange code for tokens
        print("🔄 Exchanging code for tokens...")
        print(f"🔗 Token exchange redirect_uri: {callback_url}")
        
        token_data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'authorization_code',
            'code': auth_code,
            'redirect_uri': callback_url
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data=token_data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            if response.status_code != 200:
                print(f"❌ Token exchange failed with status {response.status_code}")
                print(f"❌ Response: {response.text}")
                print(f"❌ Request data: {token_data}")
                raise ValueError(f"Token exchange failed: {response.status_code} - {response.text}")
            
            token_response = response.json()
            
            access_token = token_response.get('access_token')
            refresh_token = token_response.get('refresh_token')
            
            if not access_token or not refresh_token:
                raise ValueError("Missing tokens in response")
            
            return access_token, refresh_token
            
    except Exception as e:
        server.server_close()
        raise e


async def setup_microsoft_oauth(client_id: str, client_secret: str) -> Tuple[str, str]:
    """Setup Microsoft Graph OAuth and return encrypted refresh token and encryption key"""
    
    callback_url = f"http://localhost:{MICROSOFT_CALLBACK_PORT}{MICROSOFT_CALLBACK_PATH}"
    
    # Build authorization URL
    auth_params = {
        'client_id': client_id,
        'response_type': 'code',
        'redirect_uri': callback_url,
        'scope': MICROSOFT_SCOPE,
        'response_mode': 'query'
    }
    
    auth_url = f"{MICROSOFT_AUTH_URL}?{urllib.parse.urlencode(auth_params)}"
    token_url = MICROSOFT_TOKEN_URL
    
    print("🔐 Setting up Microsoft Graph OAuth...")
    print(f"📋 Required permissions: {MICROSOFT_SCOPE}")
    print(f"🔗 Authorization URL: {auth_url}")
    print(f"🔗 Redirect URI being used: {callback_url}")
    
    # Run OAuth flow
    access_token, refresh_token = await run_oauth_flow(
        auth_url=auth_url,
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
        callback_port=MICROSOFT_CALLBACK_PORT,
        callback_path=MICROSOFT_CALLBACK_PATH
    )
    
    # Generate encryption key and encrypt refresh token
    encryption_key = generate_encryption_key()
    encrypted_refresh_token = encrypt_token(refresh_token, encryption_key)
    
    print("🔒 Tokens encrypted and ready for storage!")
    
    return encrypted_refresh_token, encryption_key


async def setup_autodesk_oauth(client_id: str, client_secret: str) -> Tuple[str, str]:
    """Setup Autodesk/BuildingConnected OAuth and return encrypted refresh token and encryption key"""
    
    callback_url = f"http://localhost:{AUTODESK_CALLBACK_PORT}{AUTODESK_CALLBACK_PATH}"
    
    # Build authorization URL
    auth_params = {
        'client_id': client_id,
        'response_type': 'code',
        'redirect_uri': callback_url,
        'scope': AUTODESK_SCOPE
    }
    
    auth_url = f"{AUTODESK_AUTH_URL}?{urllib.parse.urlencode(auth_params)}"
    token_url = AUTODESK_TOKEN_URL
    
    print("🏗️ Setting up Autodesk/BuildingConnected OAuth...")
    print(f"📋 Required permissions: {AUTODESK_SCOPE}")
    print(f"🔗 Authorization URL: {auth_url}")
    print(f"🔗 Redirect URI being used: {callback_url}")
    print(f"🔗 Token URL: {token_url}")
    
    # Run OAuth flow
    access_token, refresh_token = await run_oauth_flow(
        auth_url=auth_url,
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
        callback_port=AUTODESK_CALLBACK_PORT,
        callback_path=AUTODESK_CALLBACK_PATH
    )
    
    # Generate encryption key and encrypt refresh token
    encryption_key = generate_encryption_key()
    encrypted_refresh_token = encrypt_token(refresh_token, encryption_key)
    
    print("🔒 Tokens encrypted and ready for storage!")
    
    return encrypted_refresh_token, encryption_key


def save_to_env(key: str, value: str):
    """Save key-value pair to .env file"""
    set_key('.env', key, value)
    print(f"✅ Saved {key} to .env file")


async def setup_microsoft_auth_flow():
    """Complete Microsoft authentication setup"""
    print("\n📧 Microsoft Graph Authentication Setup")
    print("=" * 50)
    
    # Get client credentials from environment or user input
    client_id = os.getenv('MS_CLIENT_ID')
    client_secret = os.getenv('MS_CLIENT_SECRET')
    
    if not client_id:
        print("❌ MS_CLIENT_ID not found in .env file")
        client_id = input("Enter Microsoft Client ID: ").strip()
        if client_id:
            save_to_env('MS_CLIENT_ID', client_id)
    
    if not client_secret:
        print("❌ MS_CLIENT_SECRET not found in .env file")
        client_secret = input("Enter Microsoft Client Secret: ").strip()
        if client_secret:
            save_to_env('MS_CLIENT_SECRET', client_secret)
    
    if not client_id or not client_secret:
        print("❌ Missing Microsoft credentials")
        return False
    
    try:
        encrypted_token, encryption_key = await setup_microsoft_oauth(client_id, client_secret)
        
        # Save to .env file
        save_to_env('ENCRYPTED_REFRESH_TOKEN', encrypted_token)
        save_to_env('ENCRYPTION_KEY', encryption_key)
        
        print("✅ Microsoft Graph authentication setup complete!")
        return True
        
    except Exception as e:
        print(f"❌ Microsoft authentication failed: {str(e)}")
        return False


async def setup_autodesk_auth_flow():
    """Complete Autodesk authentication setup"""
    print("\n🏗️ Autodesk/BuildingConnected Authentication Setup")
    print("=" * 50)
    
    # Get client credentials from environment or user input
    client_id = os.getenv('AUTODESK_CLIENT_ID')
    client_secret = os.getenv('AUTODESK_CLIENT_SECRET')
    
    if not client_id:
        print("❌ AUTODESK_CLIENT_ID not found in .env file")
        client_id = input("Enter Autodesk Client ID: ").strip()
        if client_id:
            save_to_env('AUTODESK_CLIENT_ID', client_id)
    
    if not client_secret:
        print("❌ AUTODESK_CLIENT_SECRET not found in .env file")
        client_secret = input("Enter Autodesk Client Secret: ").strip()
        if client_secret:
            save_to_env('AUTODESK_CLIENT_SECRET', client_secret)
    
    if not client_id or not client_secret:
        print("❌ Missing Autodesk credentials")
        return False
    
    try:
        encrypted_token, encryption_key = await setup_autodesk_oauth(client_id, client_secret)
        
        # Save to .env file
        save_to_env('AUTODESK_ENCRYPTED_REFRESH_TOKEN', encrypted_token)
        save_to_env('AUTODESK_ENCRYPTION_KEY', encryption_key)
        
        print("✅ Autodesk/BuildingConnected authentication setup complete!")
        return True
        
    except Exception as e:
        print(f"❌ Autodesk authentication failed: {str(e)}")
        return False


async def main():
    """Main OAuth setup flow"""
    print("🔐 OAuth Setup for Bid Reminder Agent")
    print("=" * 50)
    print("This script will set up OAuth authentication for:")
    print("• Microsoft Graph (for sending emails)")
    print("• Autodesk/BuildingConnected (for project data)")
    print()
    
    # Setup Microsoft
    print("Setting up Microsoft Graph authentication...")
    ms_success = await setup_microsoft_auth_flow()
    
    if not ms_success:
        print("❌ Cannot proceed without Microsoft authentication")
        return
    
    # Setup Autodesk
    print("\nSetting up Autodesk authentication...")
    autodesk_success = await setup_autodesk_auth_flow()
    
    if not autodesk_success:
        print("❌ Cannot proceed without Autodesk authentication")
        return
    
    print("\n🎉 OAuth setup complete!")
    print("All tokens have been encrypted and saved to your .env file.")
    print("\nYou can now run: python setup_bid_reminder.py")


if __name__ == "__main__":
    asyncio.run(main())