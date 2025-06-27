# Northstar Bid Reminder System

An automated bid reminder system that integrates with BuildingConnected and Microsoft Outlook to send personalized reminder emails to contractors based on project deadlines.

## Features

- 🔄 **Automated Workflow**: Checks projects due in 1, 2, 3, and 7 days
- 📧 **Smart Email Progression**: Different subject lines and urgency based on timeline
- 🎯 **Personalized Messages**: Customized content for each contractor and project
- 📊 **Email Tracking**: Database logging of all email attempts
- 🧪 **Testing Support**: Override parameters for specific project testing
- 🔐 **Secure Authentication**: OAuth integration with BuildingConnected and Microsoft Graph
- 📈 **Monitoring**: Sentry integration for error tracking and performance monitoring

## Quick Start

### 1. Prerequisites

- Python 3.8+
- BuildingConnected account with API access
- Microsoft 365 account with Graph API permissions
- Sentry account (optional, for monitoring)

### 2. Installation

```bash
# Clone the repository
git clone <repository-url>
cd northstar-system-FINAL

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Setup

Create a `.env` file in the root directory:

```env
# BuildingConnected / Autodesk OAuth
AUTODESK_CLIENT_ID=your_client_id
AUTODESK_CLIENT_SECRET=your_client_secret
AUTODESK_ENCRYPTED_REFRESH_TOKEN=your_encrypted_refresh_token

# Microsoft Graph OAuth
MICROSOFT_CLIENT_ID=your_microsoft_client_id
MICROSOFT_CLIENT_SECRET=your_microsoft_client_secret
MICROSOFT_ENCRYPTED_REFRESH_TOKEN=your_microsoft_encrypted_refresh_token

# Email Configuration
DEFAULT_EMAIL_RECIPIENT=your-email@company.com

# Optional: Sentry Monitoring
SENTRY_DSN=your_sentry_dsn
ENVIRONMENT=production

# Optional: LangSmith Tracing
LANGSMITH_API_KEY=your_langsmith_key
LANGSMITH_TRACING=true
```

### 4. Authentication Setup

Run the authentication setup to configure OAuth tokens:

```bash
python auth/setup_bid_reminder.py
```

This will guide you through:
- BuildingConnected OAuth flow
- Microsoft Graph OAuth flow
- Token encryption and storage

### 5. Start the Server

```bash
python app.py
```

The server will start on `http://localhost:8000`

## API Usage

### Health Check

Check if the system is running:

```bash
curl http://localhost:8000/health
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-27T12:00:00.000000",
  "version": "1.0.0"
}
```

### Run Bid Reminder (Normal Operation)

Execute the full bid reminder workflow:

```bash
curl -X POST http://localhost:8000/run-bid-reminder
```

**Response:**
```json
{
  "workflow_successful": true,
  "result_message": "✅ Bid reminder workflow completed successfully!\n📋 Found 3 projects due in 5-10 days\n📧 Found 12 bidding invitations across all projects\n💌 ✅ Emails sent successfully",
  "error_message": null,
  "projects_found": 3,
  "email_sent": true,
  "timestamp": "2025-01-27T12:00:00.000000"
}
```

### Test Specific Project

Test the system with a specific project and timeline:

```bash
curl -X POST http://localhost:8000/run-bid-reminder \
  -H "Content-Type: application/json" \
  -d '{
    "projectId": "68530e930ae88fe3ccf7ed81",
    "daysOut": 3
  }'
```

**Response:**
```json
{
  "workflow_successful": true,
  "result_message": "✅ Bid reminder workflow completed successfully!\n📋 Found 1 projects due in 5-10 days\n📧 Found 8 bidding invitations across all projects\n💌 ✅ Emails sent successfully",
  "error_message": null,
  "projects_found": 1,
  "email_sent": true,
  "timestamp": "2025-01-27T12:00:00.000000",
  "test_project_id": "68530e930ae88fe3ccf7ed81",
  "test_days_out": 3
}
```

### Test Parameters

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `projectId` | string | Specific BuildingConnected project ID to test | `"68530e930ae88fe3ccf7ed81"` |
| `daysOut` | integer | Override days until due (1, 2, 3, or 7) | `3` |

### Copy-Paste Test Examples

**Test 1-Day Urgency (Final Reminder):**
```bash
curl -X POST http://localhost:8000/run-bid-reminder \
  -H "Content-Type: application/json" \
  -d '{"projectId": "68530e930ae88fe3ccf7ed81", "daysOut": 1}'
```

**Test 2-Day Urgency (Third Request):**
```bash
curl -X POST http://localhost:8000/run-bid-reminder \
  -H "Content-Type: application/json" \
  -d '{"projectId": "68530e930ae88fe3ccf7ed81", "daysOut": 2}'
```

**Test 3-Day Urgency (Second Request):**
```bash
curl -X POST http://localhost:8000/run-bid-reminder \
  -H "Content-Type: application/json" \
  -d '{"projectId": "68530e930ae88fe3ccf7ed81", "daysOut": 3}'
```

**Test 7-Day Initial Invitation:**
```bash
curl -X POST http://localhost:8000/run-bid-reminder \
  -H "Content-Type: application/json" \
  -d '{"projectId": "68530e930ae88fe3ccf7ed81", "daysOut": 7}'
```

## Email System

### Subject Line Progression

The system automatically escalates subject lines based on timeline:

- **7 days**: "Bid Invitation: [Package] - [Project]"
- **3 days**: "Second Request: [Package] - [Project]"
- **2 days**: "Third Request: [Package] - [Project]"
- **1 day**: "Final Reminder: [Package] - DUE TOMORROW!"

### Message Customization

Email content varies by urgency level with different:
- Greeting variations
- Introduction messages
- Timing information
- Portal access instructions
- Closing sentiments

### Email Tracking

All email attempts are logged to a SQLite database with:
- Recipient information
- Project details
- Send status (SUCCESS/FAILED)
- Timestamp
- Error details (if failed)

## System Architecture

### Workflow Components

1. **Authentication Node**: Initializes OAuth tokens for both APIs
2. **Project Check Node**: Fetches projects due in 1, 2, 3, 7 days
3. **Invitation Node**: Gets bidding invitations for each project
4. **Email Node**: Sends personalized emails to each contractor
5. **Finalize Node**: Summarizes results and logs completion
6. **Token Refresh Node**: Proactively refreshes tokens for next run

### Key Files

- `app.py` - FastAPI web server and API endpoints
- `bid_reminder_agent.py` - Core workflow logic and email generation
- `email_tracker.py` - Database operations for email logging
- `auth/` - OAuth setup and token management
- `clients/` - API clients for BuildingConnected and Microsoft Graph

## Troubleshooting

### Authentication Issues

If you see authentication errors:

```bash
# Re-run the OAuth setup
python auth/setup_bid_reminder.py
```

*Note: You have to set the encryption keys and encrypted refresh tokens to empty before running this*

### Token Refresh Errors

BuildingConnected tokens expire after 14 days of inactivity:

```bash
# Run fresh OAuth flow
python -c "import asyncio; from auth.oauth_setup import setup_autodesk_auth_flow; asyncio.run(setup_autodesk_auth_flow())"
```

### Common Error Messages

| Error | Solution |
|-------|----------|
| `Authentication failed` | Run `python auth/setup_bid_reminder.py` |
| `invalid_grant` | Re-run OAuth flow (tokens expired) |
| `No projects found` | Check date filters and project status |
| `Email send failed` | Verify Microsoft Graph permissions |

### Debug Mode

Enable detailed logging:

```bash
# Set environment variable
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=your_key

# Run with debug output
python app.py
```

## Deployment

### Railway Deployment

The system is configured for Railway deployment:

```bash
# Deploy to Railway
railway up
```

Configuration is in `railway.toml`.

### Environment Variables

Ensure all required environment variables are set in your deployment platform:

- Authentication tokens
- Email configuration
- Optional monitoring keys

## Development

### Testing

```bash
# Run test suite
cd test-suite
python -m pytest
```

### Adding New Email Variations

Edit the message functions in `bid_reminder_agent.py`:

- `_get_greeting()` - Opening greetings
- `_get_intro()` - Project introduction
- `_get_timing_info()` - Deadline information
- `_get_portal_access()` - Portal link presentation
- `_get_closing_sentiment()` - Closing messages

### Custom Timeline

To add new timeline intervals, modify:

1. `self.days_before_bid` in `BidReminderAgent.__init__()`
2. Add new conditions in email generation functions
3. Update subject line logic in `_get_subject_line()`

## Support

For issues or questions:

1. Check the troubleshooting section above
2. Review logs in the `logs/` directory
3. Check Sentry dashboard (if configured)
4. Review error details in API responses