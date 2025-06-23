# Authentication Test Suite

Comprehensive authentication testing for 8am pre-flight checks before running the bid reminder workflow.

## Test Suites

### 1. `auth-health-check.py` (Existing)
Basic authentication health validation:
- Environment variables
- Token manager creation
- Token decryption/refresh
- API client creation
- Basic endpoint validation

### 2. `auth-gaps-tests.py` (New)
Enhanced gap testing for edge cases:
- Token refresh simulation with Autodesk rotation
- Permission scope validation
- Token decryption integrity checks
- Network failure scenario testing
- Concurrent authentication handling
- Token tampering detection

### 3. `auth-8am-preflight.py` (New - RECOMMENDED)
Complete end-to-end pre-flight check combining:
- All health checks
- All gap tests  
- Workflow-specific readiness validation
- Email sending capability testing
- Project data availability verification

## Usage

### Daily 8am Pre-flight Check (Recommended)
```bash
python test-suite/auth-8am-preflight.py
```

Exit codes:
- `0`: ✅ Ready for workflow execution
- `1`: ❌ Critical issues - DO NOT run workflow  
- `2`: ⚠️  Warnings - Monitor during execution
- `3`: 💥 Test suite crashed

### Individual Test Suites
```bash
# Basic health check
python test-suite/tests-auth.py

# Enhanced gap testing
python test-suite/auth-gaps-tests.py
```

## Automation Integration

### Cron Job Example
```bash
# Run daily at 8am
0 8 * * * cd /path/to/northstar-agent && python test-suite/auth-8am-preflight.py && python bid_reminder_agent.py
```

### GitHub Actions Example
```yaml
name: Daily Bid Reminder
on:
  schedule:
    - cron: '0 8 * * *'
jobs:
  pre-flight-and-run:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Run 8am Pre-flight Check
      run: python test-suite/auth-8am-preflight.py
    - name: Run Bid Reminder Workflow
      if: success()
      run: python bid_reminder_agent.py
```

## Output Files

All test suites generate detailed JSON reports in `test-suite/`:
- `auth-health-report-YYYYMMDD_HHMMSS.json`
- `auth-gaps-report-YYYYMMDD_HHMMSS.json`  
- `auth-8am-preflight-YYYYMMDD_HHMMSS.json`

## Key Features

### Authentication Gap Coverage
✅ **Token Refresh Simulation**
- Microsoft Graph token refresh validation
- Autodesk token rotation behavior testing
- Forced refresh scenarios

✅ **Permission Scope Validation** 
- Mail.Read/Mail.Send permissions for Microsoft Graph
- data:read/user-profile:read permissions for BuildingConnected
- Real API permission testing

✅ **Token Decryption Integrity**
- AES-CBC encryption format validation
- Hex format verification
- Consistency checks
- Tampering detection

✅ **Network Resilience**
- Timeout handling
- DNS failure scenarios
- HTTP error code handling
- Endpoint connectivity verification

✅ **Workflow Readiness**
- Email recipient validation
- Project data availability (5-10 day range)
- End-to-end email sending capability
- Token expiration buffer checks
- Optimal execution timing validation
- Environment completeness verification

## Troubleshooting

### Common Issues

**Autodesk Token Expired**
```
❌ BuildingConnected API Error 500: Token refresh failed: 400 - 
{"error":"invalid_grant","error_description":"The refresh token is invalid or expired."}
```
**Solution:** Run `python auth/setup_bid_reminder.py` to reconfigure authentication

**Missing Email Recipient**
```
❌ DEFAULT_EMAIL_RECIPIENT environment variable not set
```
**Solution:** Add `DEFAULT_EMAIL_RECIPIENT=your-email@domain.com` to `.env`

**Permission Denied**
```
❌ Mail.Send permission denied
```
**Solution:** Review OAuth application permissions in Azure/Autodesk consoles

## Logs

Test execution logs are saved to:
- `test-suite/auth-health-check.log`
- `test-suite/auth-gaps-check.log`
- `test-suite/auth-8am-preflight.log`