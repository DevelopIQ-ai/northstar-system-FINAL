"""
Deterministic Microsoft Graph API client for email operations
Ported from TypeScript implementation for direct API access
"""

from typing import Optional, Dict, Any, List
from enum import Enum

import httpx
from pydantic import BaseModel, Field

from auth.auth_helpers import MSGraphTokenManager, EmailValidator


class EmailImportance(str, Enum):
    """Email importance levels"""
    LOW = "low"
    NORMAL = "normal" 
    HIGH = "high"


class EmailRecipient(BaseModel):
    """Email recipient model"""
    emailAddress: Dict[str, str]


class EmailBody(BaseModel):
    """Email body model"""
    contentType: str = Field(description="'text' or 'html'")
    content: str


class EmailMessage(BaseModel):
    """Email message model for Graph API"""
    subject: str
    body: EmailBody
    toRecipients: List[EmailRecipient]
    ccRecipients: Optional[List[EmailRecipient]] = None
    bccRecipients: Optional[List[EmailRecipient]] = None
    importance: EmailImportance = EmailImportance.NORMAL


class SendEmailRequest(BaseModel):
    """Send email request model"""
    message: EmailMessage
    saveToSentItems: bool = True


class SendEmailResponse(BaseModel):
    """Send email response model"""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


class GraphAPIError(Exception):
    """Microsoft Graph API error"""
    def __init__(self, status_code: int, message: str, response_text: str = ""):
        self.status_code = status_code
        self.message = message
        self.response_text = response_text
        super().__init__(f"Graph API Error {status_code}: {message}")


class MSGraphClient:
    """Deterministic Microsoft Graph API client"""
    
    def __init__(self, token_manager: MSGraphTokenManager):
        self.token_manager = token_manager
        self.base_url = "https://graph.microsoft.com/v1.0"
        
    async def _make_request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Make authenticated request to Graph API"""
        access_token = await self.token_manager.get_access_token()
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        url = f"{self.base_url}/{path.lstrip('/')}"
        
        async with httpx.AsyncClient() as client:
            if method.upper() == 'GET':
                response = await client.get(url, headers=headers, params=params)
            elif method.upper() == 'POST':
                response = await client.post(url, headers=headers, json=data)
            elif method.upper() == 'PATCH':
                response = await client.patch(url, headers=headers, json=data)
            elif method.upper() == 'DELETE':
                response = await client.delete(url, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
        
        # Handle authentication errors
        if response.status_code == 401:
            raise GraphAPIError(401, "Authentication required - token may be expired")
        
        # Handle other errors
        if not response.is_success:
            error_text = response.text
            try:
                error_json = response.json()
                error_message = error_json.get('error', {}).get('message', error_text)
            except:
                error_message = error_text
            
            raise GraphAPIError(response.status_code, error_message, error_text)
        
        # Handle empty responses
        if not response.text.strip():
            return {}
        
        return response.json()
    
    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        importance: EmailImportance = EmailImportance.NORMAL,
        save_to_sent_items: bool = True
    ) -> SendEmailResponse:
        """
        Send email deterministically
        
        Args:
            to: Comma-separated recipient email addresses
            subject: Email subject
            body: Email body content (HTML or plain text)
            cc: Optional CC recipients (comma-separated)
            bcc: Optional BCC recipients (comma-separated)
            importance: Email importance level
            save_to_sent_items: Whether to save to Sent Items
            
        Returns:
            SendEmailResponse with success status and details
        """
        try:
            # Validate and format recipients
            to_recipients = EmailValidator.format_recipients(to, 'to')
            cc_recipients = EmailValidator.format_recipients(cc or '', 'cc') if cc else []
            bcc_recipients = EmailValidator.format_recipients(bcc or '', 'bcc') if bcc else []
            
            # Detect content type
            content_type = 'html' if '<html' in body.lower() else 'text'
            
            # Build email message
            email_message = EmailMessage(
                subject=subject,
                body=EmailBody(contentType=content_type, content=body),
                toRecipients=[EmailRecipient(**recipient) for recipient in to_recipients],
                ccRecipients=[EmailRecipient(**recipient) for recipient in cc_recipients] if cc_recipients else None,
                bccRecipients=[EmailRecipient(**recipient) for recipient in bcc_recipients] if bcc_recipients else None,
                importance=importance
            )
            
            # Build request
            send_request = SendEmailRequest(
                message=email_message,
                saveToSentItems=save_to_sent_items
            )
            
            # Make API call
            await self._make_request('POST', 'me/sendMail', send_request.model_dump(exclude_none=True))
            
            return SendEmailResponse(
                success=True,
                message_id=None  # Graph API doesn't return message ID for sent emails
            )
            
        except GraphAPIError as e:
            return SendEmailResponse(
                success=False,
                error=f"Graph API Error {e.status_code}: {e.message}"
            )
        except ValueError as e:
            return SendEmailResponse(
                success=False, 
                error=f"Validation Error: {str(e)}"
            )
        except Exception as e:
            return SendEmailResponse(
                success=False,
                error=f"Unexpected Error: {str(e)}"
            )
    
    async def list_emails(
        self,
        folder: str = "inbox",
        count: int = 10,
        select_fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """List emails from specified folder"""
        if select_fields is None:
            select_fields = ["id", "subject", "from", "receivedDateTime", "hasAttachments"]
        
        params = {
            "$top": str(min(count, 50)),  # Max 50
            "$select": ",".join(select_fields),
            "$orderby": "receivedDateTime desc"
        }
        
        return await self._make_request('GET', f'me/mailFolders/{folder}/messages', params=params)
    
    async def read_email(self, email_id: str) -> Dict[str, Any]:
        """Read full email content by ID"""
        return await self._make_request('GET', f'me/messages/{email_id}')
    
    async def search_emails(
        self,
        query: Optional[str] = None,
        folder: str = "inbox", 
        count: int = 10,
        sender: Optional[str] = None,
        subject_filter: Optional[str] = None,
        has_attachments: Optional[bool] = None,
        unread_only: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Search emails with filters"""
        params = {
            "$top": str(min(count, 25)),  # Max 25 for search
            "$orderby": "receivedDateTime desc"
        }
        
        # Build filter conditions
        filters = []
        if sender:
            filters.append(f"from/emailAddress/address eq '{sender}'")
        if subject_filter:
            filters.append(f"contains(subject,'{subject_filter}')")
        if has_attachments is not None:
            filters.append(f"hasAttachments eq {str(has_attachments).lower()}")
        if unread_only:
            filters.append("isRead eq false")
        
        if filters:
            params["$filter"] = " and ".join(filters)
        
        if query:
            params["$search"] = f'"{query}"'
        
        return await self._make_request('GET', f'me/mailFolders/{folder}/messages', params=params)