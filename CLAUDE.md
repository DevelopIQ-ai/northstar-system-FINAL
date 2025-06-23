# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Environment Setup
```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Required: Setup OAuth authentication for both services
python auth/setup_bid_reminder.py
```

### Running the Application
```bash
# Run the agent directly (standalone mode)
python bid_reminder_agent.py

# Run the FastAPI server
python app.py
# or with uvicorn
uvicorn app:app --host 0.0.0.0 --port 8000

# API documentation available at:
# http://localhost:8000/docs (Swagger)
# http://localhost:8000/redoc (ReDoc)
```

### Testing
```bash
# Run tests (pytest framework configured but no tests implemented yet)
pytest
pytest -v  # verbose output
pytest tests/test_specific.py  # run specific test file
```

## Architecture Overview

### Core Workflow Engine
The application uses **LangGraph** for workflow orchestration with a 5-node state machine:

1. `initialize_auth` - Authenticate with Microsoft Graph + BuildingConnected APIs
2. `check_upcoming_projects` - Query projects with bids due in 5-10 days  
3. `get_bidding_invitations` - Retrieve contractor invitation details
4. `send_reminder_email` - Send personalized HTML emails with bid portal links
5. `finalize_result` - Log results and cleanup

Each node has conditional routing that handles errors gracefully and continues the workflow when possible.

### Authentication Architecture
**Dual OAuth2 Implementation**: The system manages two separate OAuth flows with sophisticated token handling:

- **Microsoft Graph API**: For sending emails through Outlook
- **Autodesk/BuildingConnected API**: For accessing construction project data

**Security Features**:
- AES-CBC encryption for refresh token storage
- Automatic token refresh with rotation support (Autodesk rotates refresh tokens)
- Interactive setup script that guides through complete OAuth flows
- Encrypted tokens stored as `iv:encrypted_data` format in environment variables

### API Client Pattern
Both `MSGraphClient` and `BuildingConnectedClient` follow a consistent pattern:
- Pydantic models for request/response validation
- Comprehensive error handling with specific exceptions
- Automatic token refresh before API calls
- Detailed logging without exposing sensitive data

### State Management
Uses `BidReminderState` TypedDict with LangGraph for workflow state:
- Authentication clients and token managers
- Project data and bidding invitations
- Email status and error tracking
- Success/failure state with detailed messages

## Key Environment Variables

### Authentication (Required)
```env
# Microsoft/Outlook
MS_CLIENT_ID=your_microsoft_client_id
MS_CLIENT_SECRET=your_microsoft_client_secret
ENCRYPTED_REFRESH_TOKEN=encrypted_outlook_token
ENCRYPTION_KEY=encryption_key_for_outlook

# Autodesk/BuildingConnected  
AUTODESK_CLIENT_ID=your_autodesk_client_id
AUTODESK_CLIENT_SECRET=your_autodesk_client_secret
AUTODESK_ENCRYPTED_REFRESH_TOKEN=encrypted_autodesk_token
AUTODESK_ENCRYPTION_KEY=encryption_key_for_autodesk

# Application
DEFAULT_EMAIL_RECIPIENT=your-email@domain.com
```

### Optional Configuration
```env
LANGSMITH_TRACING=true  # Enable LangSmith workflow tracing
LANGSMITH_API_KEY=your_langsmith_key
ENVIRONMENT=development
```

## Authentication Setup Process

**Critical**: Must run `python auth/setup_bid_reminder.py` before first use. This script:

1. Checks current configuration status
2. Guides through Microsoft OAuth flow (opens browser, runs local callback server)
3. Guides through Autodesk OAuth flow (separate browser flow)
4. Encrypts and stores all refresh tokens securely
5. Updates `.env` file with encrypted credentials

The setup process creates local callback servers on ports 3333 (Microsoft) and 5173 (Autodesk) to capture OAuth responses.

## Data Flow Architecture

```
FastAPI REST API ’ LangGraph Workflow ’ Dual API Clients
     “                    “                    “
- /run-bid-reminder    State Machine      OAuth Token Managers
- Health checks        Error routing      - MSGraphClient  
- Graceful shutdown    LangSmith tracing  - BuildingConnectedClient
```

### Email Workflow
1. **Project Query**: Fetch projects due in 5-10 days from BuildingConnected
2. **Invitation Retrieval**: Get detailed bidding invitations for each project  
3. **Email Generation**: Create personalized HTML emails with:
   - Contractor name and project details
   - Bid deadline with urgency styling
   - Direct "Access Bid Portal" button links
   - Professional responsive HTML templates
4. **Email Delivery**: Send via Microsoft Graph API with high importance

## Error Handling Strategy

The workflow uses **graceful degradation**:
- Continues processing other projects if one fails
- Routes around failed authentication to provide meaningful error messages
- Logs detailed error context while protecting sensitive data
- Returns structured error responses via FastAPI

## Development Notes

### Missing Test Infrastructure
- pytest configured but no test files exist in `tests/` directory
- Recommend adding comprehensive tests for all major components
- Use `pytest-asyncio` for testing async workflows

### Code Quality Tools Not Configured
Consider adding:
- `black` for code formatting
- `flake8` or `ruff` for linting  
- `mypy` for type checking
- `pre-commit` hooks for automated quality checks

### Logging Strategy
- Comprehensive logging to both console and `bid_reminder_agent.log`
- LangSmith integration for workflow tracing and debugging
- Structured logging with timestamps and log levels
- Security-conscious logging (no plain-text credentials)