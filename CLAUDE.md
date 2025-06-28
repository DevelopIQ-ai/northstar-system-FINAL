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
4. `send_reminder_email` - Send personalized text emails with bid portal links using spyntax formatting
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

### Database Email Tracking
**EmailTracker Integration**: Comprehensive PostgreSQL-based email logging system:

- **AsyncPG Integration**: Uses `asyncpg` for high-performance async database operations
- **Email Tracking Table**: 15-field schema tracking all email attempts with timestamps
- **Status Monitoring**: Tracks SUCCESS/FAILED status for each email send
- **Analytics Support**: Built-in methods for email statistics and recent send history
- **Error Resilience**: Comprehensive error handling for database connectivity issues

## Key Environment Variables

### Authentication (Required)
```env
# Microsoft/Outlook
MS_CLIENT_ID=your_microsoft_client_id
MS_CLIENT_SECRET=your_microsoft_client_secret
MS_ENCRYPTED_REFRESH_TOKEN=encrypted_outlook_token
MS_ENCRYPTION_KEY=encryption_key_for_outlook

# Autodesk/BuildingConnected  
AUTODESK_CLIENT_ID=your_autodesk_client_id
AUTODESK_CLIENT_SECRET=your_autodesk_client_secret
AUTODESK_ENCRYPTED_REFRESH_TOKEN=encrypted_autodesk_token
AUTODESK_ENCRYPTION_KEY=encryption_key_for_autodesk

# Application
DEFAULT_EMAIL_RECIPIENT=your-email@domain.com

# Database (Required for email tracking)
DATABASE_URL=postgresql://user:password@host:port/database
```

### Optional Configuration
```env
LANGSMITH_TRACING=true  # Enable LangSmith workflow tracing
LANGSMITH_API_KEY=your_langsmith_key

# Environment Configuration (affects Sentry behavior)
ENVIRONMENT=development  # Options: development, dev, local, production
                        # Defaults to 'development' for local runs
                        # Set to 'production' on Railway/production deployment

# Sentry Error Monitoring (Optional)
SENTRY_DSN=your_sentry_dsn_url
RELEASE_VERSION=1.0.0  # Optional: track releases in Sentry
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
FastAPI REST API � LangGraph Workflow � Dual API Clients � PostgreSQL Database
     �                    �                    �                    �
- /run-bid-reminder    State Machine      OAuth Token Managers    Email Tracking
- Health checks        Error routing      - MSGraphClient         - AsyncPG Integration
- Graceful shutdown    LangSmith tracing  - BuildingConnectedClient - Email Analytics
```

### Email Workflow
1. **Project Query**: Fetch projects due in 5-10 days from BuildingConnected
2. **Invitation Retrieval**: Get detailed bidding invitations for each project  
3. **Email Generation**: Create personalized text emails using spyntax formatting with:
   - Contractor name and project details
   - Bid deadline with clear formatting
   - Direct bid portal links
   - Clean, readable text format
4. **Email Delivery**: Send via Microsoft Graph API with high importance
5. **Database Logging**: Track all email attempts in PostgreSQL with comprehensive metadata

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
- Comprehensive logging to both console and `logs/bid_reminder_agent.log`
- LangSmith integration for workflow tracing and debugging
- Structured logging with timestamps and log levels
- Security-conscious logging (no plain-text credentials)
- **Database email tracking** via `EmailTracker` class with PostgreSQL persistence

### Key Dependencies Added
- `asyncpg==0.29.0` - High-performance PostgreSQL async driver
- `psutil==5.9.0` - System monitoring and health checks

### Database Schema
The `email_tracking` table includes:
- Project and bid package identifiers
- Recipient details (name, email, company)
- Email content metadata (title, links, due dates)
- Delivery status and timestamp tracking
- Analytics-ready structure for reporting