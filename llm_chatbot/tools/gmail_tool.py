import os
from typing import List, Dict, Optional, Union, Any
from base64 import urlsafe_b64encode
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import inspect
from dataclasses import dataclass
import base64
from datetime import datetime
import email.utils

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


@dataclass
class GoogleEmail:
    id: str
    thread_id: str
    label_ids: List[str]
    snippet: str
    sender: str
    reciever: str
    subject: str
    sent_datetime: str
    recieved_datetime: str
    internal_date: str
    body: str
    is_html: bool = False


class GmailTool:
    """
    A simplified interface for interacting with Gmail API.
    
    This class provides methods for common Gmail operations like sending emails,
    reading messages, managing labels, and handling drafts.
    """
    
    SCOPES = [
        'https://www.googleapis.com/auth/gmail.modify',
        'https://www.googleapis.com/auth/gmail.compose',
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.labels'
    ]

    def __init__(self, credentials_path: str = 'credentials.json', token_path: str = 'token.json'):
        """
        Initialize the Gmail tool with authentication.
        
        Args:
            credentials_path: Path to the credentials.json file
            token_path: Path to store/retrieve the token.json file
        """
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.creds = self._authenticate()
        self.service = build('gmail', 'v1', credentials=self.creds)
        self.user_id = 'me'  # Special value for authenticated user

    def _get_available_methods(self) -> List[Dict[str, str]]:
        """
        Returns a list of all public methods in the class along with their docstrings.
        
        Returns:
            List of dictionaries containing method names and their documentation.
            Each dictionary has:
                - name: Method name
                - docstring: Method documentation
                - signature: Method signature
        """
        methods = []
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            # Skip private methods (those starting with _)
            if not name.startswith('_'):
                # Get the method's signature
                signature = str(inspect.signature(method))
                # Get the method's docstring, clean it up and handle None case
                docstring = inspect.getdoc(method) or "No documentation available"
                
                methods.append({
                    "name": name,
                    "docstring": docstring,
                    "signature": f"{name}{signature}",
                    "func": method
                })
        
        return sorted(methods, key=lambda x: x["name"])

    def _authenticate(self) -> Credentials:
        """Handle the OAuth2 authentication flow."""
        creds = None
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, self.SCOPES)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, self.SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())
        
        return creds

    def _decode_base64url(self, base64_content: str) -> str:
        """Decode base64url encoded string to UTF-8 text."""
        if not base64_content:
            return ""
        
        # Add padding if needed
        pad_length = len(base64_content) % 4
        if pad_length:
            base64_content += '=' * (4 - pad_length)
        
        # Replace URL-safe characters
        base64_content = base64_content.replace('-', '+').replace('_', '/')
        
        try:
            decoded_bytes = base64.b64decode(base64_content)
            return decoded_bytes.decode('utf-8')
        except Exception as e:
            print(f"Error decoding base64: {e}")
            return ""

    def _extract_email_header_value(self, headers: List[Dict[str, str]], header_name: str) -> str:
        """Extract value from email headers."""
        for header in headers:
            if header['name'].lower() == header_name.lower():
                return header['value']
        return ""

    def _parse_email_message_part(self, part: Dict[str, Any]) -> tuple[Optional[str], bool]:
        """Parse a message part and return body content and is_html flag."""
        if not part:
            return None, False

        # Get content transfer encoding
        content_transfer_encoding = None
        if 'headers' in part:
            content_transfer_encoding = self._extract_email_header_value(part['headers'], 'Content-Transfer-Encoding')

        body_data = part.get('body', {}).get('data')
        
        if part.get('mimeType') == 'text/plain':
            return self._decode_base64url(body_data), False
        elif part.get('mimeType') == 'text/html':
            return self._decode_base64url(body_data), True
        
        return None, False

    def _extract_email_message_content(self, payload: Dict[str, Any]) -> tuple[str, bool]:
        """Recursively extract message content from payload."""
        body = ""
        is_html = False

        # Handle multipart messages
        if 'parts' in payload:
            for part in payload['parts']:
                part_body, part_is_html = self._parse_email_message_part(part)
                if part_body:
                    # Prefer HTML content over plain text
                    if part_is_html:
                        return part_body, True
                    body = part_body
                    is_html = part_is_html
        else:
            # Single part message
            body, is_html = self._parse_email_message_part(payload)

        return body or "", is_html

    def _parse_gmail_message(self, message: Dict[str, Any]) -> GoogleEmail:
        """Parse Gmail API message into GoogleEmail dataclass."""
        payload = message['payload']
        headers = payload['headers']

        # Extract basic headers
        sender = self._extract_email_header_value(headers, 'From')
        receiver = self._extract_email_header_value(headers, 'To')
        subject = self._extract_email_header_value(headers, 'Subject')
        date = self._extract_email_header_value(headers, 'Date')
        received = self._extract_email_header_value(headers, 'Received')

        # Parse dates
        sent_datetime = email.utils.parsedate_to_datetime(date).isoformat() if date else ""
        received_datetime = email.utils.parsedate_to_datetime(received.split(';')[1].strip()).isoformat() if received else ""

        # Extract body content
        body, is_html = self._extract_email_message_content(payload)

        return GoogleEmail(
            id=message['id'],
            thread_id=message['threadId'],
            label_ids=message.get('labelIds', []),
            snippet=message.get('snippet', ''),
            sender=sender,
            reciever=receiver,
            subject=subject,
            sent_datetime=sent_datetime,
            recieved_datetime=received_datetime,
            internal_date=message.get('internalDate', ''),
            body=body,
            is_html=is_html
        )

    def send_email(self, to: str, subject: str, body: str, html: bool = False) -> Dict:
        """
        Send an email to specified recipient.
        
        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body content
            html: If True, send as HTML email
        
        Returns:
            Dict containing the sent message details
        """
        message = MIMEMultipart()
        message['to'] = to
        message['subject'] = subject

        body_mime = MIMEText(body, 'html' if html else 'plain')
        message.attach(body_mime)

        raw_message = urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        try:
            return self.service.users().messages().send(
                userId=self.user_id,
                body={'raw': raw_message}
            ).execute()
        except HttpError as error:
            raise Exception(f"Failed to send email: {error}")

    def get_messages(self, query: str = None, max_results: int = 10, get_body_content: bool = False) -> List[Dict]:
        """
        Get email messages matching the specified query.
        
        Args:
            query: Gmail search query (None for all messages)
            max_results: Maximum number of messages to return
            get_body_content: Boolean stating if to return the email body content (default=False) (saves tokens)
            
        Returns:
            List of message dictionaries
        """
        try:
            messages = []
            request = self.service.users().messages().list(
                userId=self.user_id,
                q=query,
                maxResults=max_results
            )
            while request is not None:
                response = request.execute()
                messages.extend(response.get('messages', []))
                
                request = self.service.users().messages().list_next(
                    request, response
                )
                
                if len(messages) >= max_results:
                    messages = messages[:max_results]
                    break
                    
            return [self.get_message(msg['id'], get_body_content=get_body_content) for msg in messages]
        except HttpError as error:
            raise Exception(f"Failed to fetch messages: {error}")

    def get_message(self, message_id: str, do_format: bool = True, get_body_content: bool = False) -> Dict:
        """
        Get a specific email message by ID.
        
        Args:
            message_id: The ID of the message to retrieve
            do_format: Boolean stating if the emails should be loaded into pydantic data model (default=True) (saves tokens)
            get_body_content: Boolean stating if to return the email body content (default=False) (saves tokens)

        Returns:
            Dictionary containing message details
        """
        try:
            specific_email = self.service.users().messages().get(
                userId=self.user_id,
                id=message_id,
                format='full'
            ).execute()
            if do_format:
                specific_email = self._parse_gmail_message(specific_email)
                specific_email.body = "[REMOVED_BY_TOOL]" if not get_body_content else specific_email.body
            return specific_email
        except HttpError as error:
            raise Exception(f"Failed to fetch message: {error}")

    def create_label(self, name: str, visibility: str = 'labelShow') -> Dict:
        """
        Create a new label in gmail.
        
        Args:
            name: Name of the label
            visibility: Visibility setting ('labelShow', 'labelShowIfUnread', 'labelHide')
            
        Returns:
            Dictionary containing the created label details
        """
        try:
            label_object = {
                'name': name,
                'labelListVisibility': visibility,
                'messageListVisibility': 'show'
            }
            return self.service.users().labels().create(
                userId=self.user_id,
                body=label_object
            ).execute()
        except HttpError as error:
            raise Exception(f"Failed to create label: {error}")

    def get_labels(self) -> List[Dict]:
        """
        Get all labels in the user's gmail mailbox.
        
        Returns:
            List of label dictionaries
        """
        try:
            results = self.service.users().labels().list(userId=self.user_id).execute()
            return results.get('labels', [])
        except HttpError as error:
            raise Exception(f"Failed to fetch labels: {error}")

    def modify_message_labels(self, message_id: str, add_labels: List[str] = None, 
                            remove_labels: List[str] = None) -> Dict:
        """
        Modify the labels of a specific message.
        
        Args:
            message_id: ID of the message to modify
            add_labels: List of label IDs to add
            remove_labels: List of label IDs to remove
            
        Returns:
            Updated message dictionary
        """
        try:
            body = {
                'addLabelIds': add_labels or [],
                'removeLabelIds': remove_labels or []
            }
            return self.service.users().messages().modify(
                userId=self.user_id,
                id=message_id,
                body=body
            ).execute()
        except HttpError as error:
            raise Exception(f"Failed to modify message labels: {error}")

    def create_draft(self, to: str, subject: str, body: str, html: bool = False) -> Dict:
        """
        Create an email draft.
        
        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body content
            html: If True, create as HTML email
            
        Returns:
            Dictionary containing the created draft details
        """
        message = MIMEMultipart()
        message['to'] = to
        message['subject'] = subject

        body_mime = MIMEText(body, 'html' if html else 'plain')
        message.attach(body_mime)

        raw_message = urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        try:
            return self.service.users().drafts().create(
                userId=self.user_id,
                body={'message': {'raw': raw_message}}
            ).execute()
        except HttpError as error:
            raise Exception(f"Failed to create draft: {error}")

    def get_profile(self) -> Dict:
        """
        Get the current user's Gmail profile.
        
        Returns:
            Dictionary containing user profile information
        """
        try:
            return self.service.users().getProfile(userId=self.user_id).execute()
        except HttpError as error:
            raise Exception(f"Failed to fetch profile: {error}")

    def trash_message(self, message_id: str) -> Dict:
        """
        Move an email message to trash.
        
        Args:
            message_id: ID of the email message to trash
            
        Returns:
            Updated message dictionary
        """
        try:
            return self.service.users().messages().trash(
                userId=self.user_id,
                id=message_id
            ).execute()
        except HttpError as error:
            raise Exception(f"Failed to trash message: {error}")

    def untrash_message(self, message_id: str) -> Dict:
        """
        Remove an email message from trash.
        
        Args:
            message_id: ID of the email message to untrash
            
        Returns:
            Updated message dictionary
        """
        try:
            return self.service.users().messages().untrash(
                userId=self.user_id,
                id=message_id
            ).execute()
        except HttpError as error:
            raise Exception(f"Failed to untrash message: {error}")