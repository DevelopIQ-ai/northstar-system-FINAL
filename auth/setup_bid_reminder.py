#!/usr/bin/env python3
"""
Setup script for Bid Reminder Agent
Helps users authenticate both Outlook and BuildingConnected accounts
"""

import os
import sys
from dotenv import load_dotenv, set_key

# Import the new JSON token storage
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth.token_storage import TokenStorage

load_dotenv()

# Initialize token storage
token_storage = TokenStorage()

def check_environment_variables():
    """Check which environment variables are configured"""
    print("🔍 Checking current configuration...\n")
    
    # Check JSON token storage first
    print("📁 JSON Token Storage:")
    
    # Check Microsoft token
    microsoft_token_info = token_storage.get_token_info('microsoft')
    if microsoft_token_info.get('exists', False):
        print(f"  ✅ Microsoft Token: configured (updated: {microsoft_token_info.get('last_updated', 'unknown')})")
        microsoft_token_configured = True
    else:
        print(f"  ❌ Microsoft Token: NOT CONFIGURED in JSON storage")
        microsoft_token_configured = False
    
    # Check Autodesk token
    autodesk_token_info = token_storage.get_token_info('autodesk')
    if autodesk_token_info.get('exists', False):
        print(f"  ✅ Autodesk Token: configured (updated: {autodesk_token_info.get('last_updated', 'unknown')})")
        autodesk_token_configured = True
    else:
        print(f"  ❌ Autodesk Token: NOT CONFIGURED in JSON storage")
        autodesk_token_configured = False
    
    # Check .env credentials
    outlook_credentials = {
        'MS_CLIENT_ID': 'Microsoft Client ID',
        'MS_CLIENT_SECRET': 'Microsoft Client Secret',
        'ENCRYPTION_KEY': 'Encryption Key (Outlook)'
    }
    
    building_credentials = {
        'AUTODESK_CLIENT_ID': 'Autodesk Client ID',
        'AUTODESK_CLIENT_SECRET': 'Autodesk Client Secret',
        'AUTODESK_ENCRYPTION_KEY': 'Encryption Key (BuildingConnected)'
    }
    
    email_vars = {
        'DEFAULT_EMAIL_RECIPIENT': 'Default Email Recipient'
    }
    
    print("\n📧 Outlook Credentials (.env):")
    outlook_credentials_configured = True
    for var, description in outlook_credentials.items():
        value = os.getenv(var)
        if value:
            print(f"  ✅ {description}: {'*' * 20} (configured)")
        else:
            print(f"  ❌ {description}: NOT CONFIGURED")
            outlook_credentials_configured = False
    
    print("\n🏗️ BuildingConnected Credentials (.env):")
    building_credentials_configured = True
    for var, description in building_credentials.items():
        value = os.getenv(var)
        if value:
            print(f"  ✅ {description}: {'*' * 20} (configured)")
        else:
            print(f"  ❌ {description}: NOT CONFIGURED")
            building_credentials_configured = False
    
    print("\n📨 Email Configuration:")
    for var, description in email_vars.items():
        value = os.getenv(var)
        if value:
            print(f"  ✅ {description}: {value}")
        else:
            print(f"  ❌ {description}: NOT CONFIGURED")
    
    # Determine overall readiness
    outlook_configured = outlook_credentials_configured and microsoft_token_configured
    building_configured = building_credentials_configured and autodesk_token_configured
    
    print(f"\n📊 Summary:")
    print(f"  Outlook Ready: {'✅' if outlook_configured else '❌'} (credentials: {'✅' if outlook_credentials_configured else '❌'}, token: {'✅' if microsoft_token_configured else '❌'})")
    print(f"  BuildingConnected Ready: {'✅' if building_configured else '❌'} (credentials: {'✅' if building_credentials_configured else '❌'}, token: {'✅' if autodesk_token_configured else '❌'})")
    
    return outlook_configured, building_configured

def setup_email_recipient():
    """Setup default email recipient"""
    print("\n📨 Setting up email recipient...")
    
    current_recipient = os.getenv('DEFAULT_EMAIL_RECIPIENT')
    if current_recipient:
        print(f"Current recipient: {current_recipient}")
        change = input("Change recipient? (y/N): ").lower().strip()
        if change != 'y':
            return
    
    email = input("Enter email address for bid reminders: ").strip()
    if email:
        set_key('.env', 'DEFAULT_EMAIL_RECIPIENT', email)
        print(f"✅ Email recipient set to: {email}")
    else:
        print("❌ No email provided")

def setup_outlook_auth():
    """Guide user through Outlook authentication setup"""
    print("\n📧 Setting up Outlook Authentication...")
    print("━" * 50)
    
    # Check what's already configured
    client_id = os.getenv('MS_CLIENT_ID')
    client_secret = os.getenv('MS_CLIENT_SECRET')
    encrypted_token = os.getenv('ENCRYPTED_REFRESH_TOKEN')
    encryption_key = os.getenv('ENCRYPTION_KEY')
    
    # Check JSON storage for tokens
    microsoft_token_info = token_storage.get_token_info('microsoft')
    has_json_token = microsoft_token_info.get('exists', False)
    
    # If we have credentials but no tokens, run OAuth flow
    if client_id and client_secret and not has_json_token:
        print("✅ Found Microsoft credentials in .env file")
        print("❌ No Microsoft token found in JSON storage")
        print("🔄 Running OAuth flow to get refresh token...")
        print("🌐 Check your browser, or click on the link that will be displayed")
        
        import subprocess
        try:
            # Run the OAuth setup for Microsoft only
            result = subprocess.run([
                sys.executable, '-c',
                '''
import asyncio
import sys
from auth.oauth_setup import setup_microsoft_auth_flow

async def main():
    success = await setup_microsoft_auth_flow()
    sys.exit(0 if success else 1)

asyncio.run(main())
                '''
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                print("✅ OAuth flow completed successfully!")
                return True
            else:
                print(f"❌ OAuth flow failed with return code {result.returncode}")
                if result.stderr:
                    print(f"Error details: {result.stderr}")
                if result.stdout:
                    print(f"Output: {result.stdout}")
                return False
        except Exception as e:
            print(f"❌ Failed to run OAuth flow: {str(e)}")
            return False
    
    # If missing credentials, guide user
    if not client_id or not client_secret:
        print("❌ Missing Microsoft credentials in .env file")
        print("\n📋 To get Microsoft credentials:")
        print("1. Go to https://portal.azure.com")
        print("2. Create an App Registration")
        print("3. Add Microsoft Graph permissions: Mail.Read, Mail.Send, Mail.ReadWrite")
        print("4. Add your Client ID and Secret to .env file")
        print("5. Re-run this setup script")
        return False
    
    # If everything is already configured
    if client_id and client_secret and has_json_token:
        print("✅ Microsoft authentication already configured!")
        print(f"📅 Token last updated: {microsoft_token_info.get('last_updated', 'unknown')}")
        return True
    
    print("❌ Unexpected configuration state")
    return False

def setup_buildingconnected_auth():
    """Guide user through BuildingConnected authentication setup"""
    print("\n🏗️ Setting up BuildingConnected Authentication...")
    print("━" * 50)
    
    # Check what's already configured
    client_id = os.getenv('AUTODESK_CLIENT_ID')
    client_secret = os.getenv('AUTODESK_CLIENT_SECRET')
    encrypted_token = os.getenv('AUTODESK_ENCRYPTED_REFRESH_TOKEN')
    encryption_key = os.getenv('AUTODESK_ENCRYPTION_KEY')
    
    # Check JSON storage for tokens
    autodesk_token_info = token_storage.get_token_info('autodesk')
    has_json_token = autodesk_token_info.get('exists', False)
    
    # If we have credentials but no tokens, run OAuth flow
    if client_id and client_secret and not has_json_token:
        print("✅ Found Autodesk credentials in .env file")
        print("❌ No Autodesk token found in JSON storage")
        print("🔄 Running OAuth flow to get refresh token...")
        print("🌐 Check your browser, or click on the link that will be displayed")
        
        import subprocess
        try:
            # Run the OAuth setup for Autodesk only
            result = subprocess.run([
                sys.executable, '-c',
                '''
import asyncio
import sys
from auth.oauth_setup import setup_autodesk_auth_flow

async def main():
    success = await setup_autodesk_auth_flow()
    sys.exit(0 if success else 1)

asyncio.run(main())
                '''
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                print("✅ OAuth flow completed successfully!")
                return True
            else:
                print(f"❌ OAuth flow failed with return code {result.returncode}")
                if result.stderr:
                    print(f"Error details: {result.stderr}")
                if result.stdout:
                    print(f"Output: {result.stdout}")
                return False
        except Exception as e:
            print(f"❌ Failed to run OAuth flow: {str(e)}")
            return False
    
    # If missing credentials, guide user
    if not client_id or not client_secret:
        print("❌ Missing Autodesk credentials in .env file")
        print("\n📋 To get Autodesk credentials:")
        print("1. Go to https://developer.autodesk.com")
        print("2. Create an application with BuildingConnected API access")
        print("3. Add your Client ID and Secret to .env file")
        print("4. Re-run this setup script")
        return False
    
    # If everything is already configured
    if client_id and client_secret and has_json_token:
        print("✅ BuildingConnected authentication already configured!")
        print(f"📅 Token last updated: {autodesk_token_info.get('last_updated', 'unknown')}")
        return True
    
    print("❌ Unexpected configuration state")
    return False

def test_configuration():
    """Test the current configuration"""
    print("\n🧪 Testing Configuration...")
    print("━" * 50)
    
    try:
        from bid_reminder_agent import BidReminderAgent
        import asyncio
        
        async def test_auth():
            agent = BidReminderAgent()
            
            # Test authentication only (don't run full workflow)
            from auth.auth_helpers import create_token_manager_from_env, create_buildingconnected_token_manager_from_env
            from clients.graph_api_client import MSGraphClient
            from clients.buildingconnected_client import BuildingConnectedClient
            
            print("Testing Outlook authentication...")
            try:
                outlook_manager = create_token_manager_from_env()
                outlook_client = MSGraphClient(outlook_manager)
                await outlook_manager.get_access_token()
                print("✅ Outlook authentication successful!")
            except Exception as e:
                print(f"❌ Outlook authentication failed: {str(e)}")
                return False
            
            print("Testing BuildingConnected authentication...")
            try:
                building_manager = create_buildingconnected_token_manager_from_env()
                building_client = BuildingConnectedClient(building_manager)
                user_info = await building_client.get_user_info()
                if user_info.authenticated:
                    print(f"✅ BuildingConnected authentication successful! User: {user_info.name or user_info.email}")
                    return True
                else:
                    print("❌ BuildingConnected authentication failed: User not authenticated")
                    return False
            except Exception as e:
                print(f"❌ BuildingConnected authentication failed: {str(e)}")
                return False
        
        success = asyncio.run(test_auth())
        return success
        
    except Exception as e:
        print(f"❌ Configuration test failed: {str(e)}")
        return False

def main():
    """Main setup flow"""
    print("🚀 Bid Reminder Agent Setup")
    print("=" * 50)
    print("This script will help you configure authentication for:")
    print("• Microsoft Outlook (for sending reminder emails)")
    print("• BuildingConnected (for checking upcoming bid deadlines)")
    print()
    
    # Check current status
    outlook_ready, building_ready = check_environment_variables()
    
    if outlook_ready and building_ready:
        print("\n🎉 Both services are already configured!")
        test = input("Run configuration test? (Y/n): ").lower().strip()
        if test != 'n':
            if test_configuration():
                print("\n✅ Setup complete! You can now run the bid reminder agent.")
                print("Use: python bid_reminder_agent.py")
            else:
                print("\n❌ Configuration test failed. Please check your credentials.")
        return
    
    print(f"\n🔧 Setup Required:")
    if not outlook_ready:
        print("  • Outlook authentication needed")
    if not building_ready:
        print("  • BuildingConnected authentication needed")
    
    # Setup email recipient first
    setup_email_recipient()
    
    # Setup services
    if not outlook_ready:
        print("\n" + "=" * 50)
        if not setup_outlook_auth():
            print("❌ Cannot proceed without Outlook authentication")
            return
    
    if not building_ready:
        print("\n" + "=" * 50)
        if not setup_buildingconnected_auth():
            print("❌ Cannot proceed without BuildingConnected authentication")
            return
    
    print("\n" + "=" * 50)
    print("🎯 Setup Complete!")
    
    # Final test
    test = input("Test configuration now? (Y/n): ").lower().strip()
    if test != 'n':
        if test_configuration():
            print("\n✅ All tests passed! Your bid reminder agent is ready.")
            print("\nTo run the agent:")
            print("  python bid_reminder_agent.py")
            print("\nTo schedule it (cron example for daily 9 AM):")
            print("  0 9 * * * cd /path/to/project && python bid_reminder_agent.py")
        else:
            print("\n❌ Configuration test failed. Please double-check your credentials.")

if __name__ == "__main__":
    main()