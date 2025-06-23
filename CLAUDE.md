# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is Claude's Bid Reminder Agent - a simple, deterministic LangGraph-based automation system that monitors BuildingConnected projects and sends email reminders for upcoming bid deadlines. The system uses direct API integration without MCP (Model Context Protocol) wrappers.

### Core Workflow

**Simple Flow:**
1. **Setup (one time)**: User authenticates both Outlook and BuildingConnected accounts
2. **Workflow (when triggered)**: 
   - Check BuildingConnected for projects due in 5-10 days
   - Send reminder email about those projects
   - Done!

### Architecture

- **LangGraph State Machine**: Deterministic nodes with structured state transitions
- **Direct API Integration**: No MCP protocol overhead, direct HTTP calls to Microsoft Graph and BuildingConnected APIs
- **Encrypted Token Management**: Secure OAuth2 refresh token storage with AES encryption for both services
- **Type-Safe Models**: Full Pydantic validation throughout the pipeline

### Key Components

- `bid_reminder_agent.py` - Main LangGraph agent that implements the workflow
- `buildingconnected_client.py` - Direct BuildingConnected/Autodesk Construction API client
- `graph_api_client.py` - Direct Microsoft Graph API client for email sending  
- `auth/auth_helpers.py` - OAuth2 token management and encryption for both services
- `auth/oauth_setup.py` - OAuth2 flow implementation
- `auth/setup_bid_reminder.py` - Complete setup script for both authentications
- `app.py` - FastAPI REST API server with single bid reminder endpoint

## Development Commands

### Environment Setup
```bash
# Activate virtual environment (always required)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration & Setup
```bash
# Setup both Outlook and BuildingConnected authentication (one time)
python auth/setup_bid_reminder.py

# Run the bid reminder workflow
python bid_reminder_agent.py

# Run the bid reminder workflow directly
python bid_reminder_agent.py

# Start the FastAPI API server
python app.py
```

### Authentication Flow
The setup requires these environment variables in `.env`:

**Outlook (Email sending):**
- `MS_CLIENT_ID` - Microsoft application client ID
- `MS_CLIENT_SECRET` - Microsoft application secret
- `ENCRYPTED_REFRESH_TOKEN` - Encrypted refresh token (format: `iv:encrypted_data`)
- `ENCRYPTION_KEY` - AES encryption key for token security

**BuildingConnected (Project monitoring):**
- `AUTODESK_CLIENT_ID` - Autodesk application client ID
- `AUTODESK_CLIENT_SECRET` - Autodesk application secret
- `AUTODESK_ENCRYPTED_REFRESH_TOKEN` - Encrypted refresh token for BuildingConnected
- `AUTODESK_ENCRYPTION_KEY` - AES encryption key for BuildingConnected tokens

**General:**
- `DEFAULT_EMAIL_RECIPIENT` - Email address for bid reminders

## Development Patterns

### LangGraph State Machine
The bid reminder agent follows a strict state flow:
```
START → initialize_auth → check_upcoming_projects → send_reminder_email → finalize_result → END
```
Each node returns updated `BidReminderState` with error handling that routes to `finalize_result` on failures.

**Workflow Details:**
1. **initialize_auth**: Authenticate both Outlook and BuildingConnected APIs
2. **check_upcoming_projects**: Query BuildingConnected for projects due in 5-10 days  
3. **send_reminder_email**: Send formatted reminder email with project details
4. **finalize_result**: Create summary and final status

### Error Handling Strategy
- Authentication errors: Token refresh failures for both Outlook and BuildingConnected
- API errors: Microsoft Graph failures, BuildingConnected API timeouts, network issues
- Project data errors: Missing bid dates, invalid project responses
- Email errors: Invalid recipients, email formatting issues
- Encryption errors: Token decryption failures

All errors are captured with structured messages and appropriate fallback behavior.

### Security Requirements
- Refresh tokens are encrypted with AES-CBC before storage
- Access tokens are cached in memory only, never persisted
- No credentials should be logged or exposed in error messages
- Environment variables must be used for all sensitive configuration

## Code Conventions

- Use Pydantic models for all data structures and API responses
- Async/await for all I/O operations (HTTP calls, file operations)
- Type hints are required for all function signatures
- Error handling should return structured responses, not raise exceptions in nodes
- Follow the existing naming patterns: snake_case for functions, PascalCase for classes

## Integration Points

### Main Entry Point (Bid Reminder)
```python
from bid_reminder_agent import run_bid_reminder

# Simple bid reminder workflow
result = await run_bid_reminder()
```

### Direct BuildingConnected API Usage
```python
from auth.auth_helpers import create_buildingconnected_token_manager_from_env
from buildingconnected_client import BuildingConnectedClient

token_manager = create_buildingconnected_token_manager_from_env()
client = BuildingConnectedClient(token_manager)
projects = await client.get_projects_due_in_n_days(5)
```

### REST API Usage
```bash
# Start the API server
python app.py

# Run bid reminder via API
curl -X POST http://localhost:8000/run-bid-reminder

# Check health
curl http://localhost:8000/health
```

## Deployment

The system is designed to be run:
- **Manually**: `python bid_reminder_agent.py`
- **Scheduled**: Via cron job (e.g., daily at 9 AM)
- **API**: Via FastAPI server with single endpoint
- **Triggered**: By external systems calling the API endpoint

Example cron job for daily reminders:
```bash
0 9 * * * cd /path/to/project && python bid_reminder_agent.py
```