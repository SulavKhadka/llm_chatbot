import os
from typing import List, Dict, Optional, Union
from base64 import urlsafe_b64encode
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import inspect

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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

    def get_messages(self, query: str = None, max_results: int = 10) -> List[Dict]:
        """
        Get email messages matching the specified query.
        
        Args:
            query: Gmail search query (None for all messages)
            max_results: Maximum number of messages to return
            
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
                    
            return [self.get_message(msg['id']) for msg in messages]
        except HttpError as error:
            raise Exception(f"Failed to fetch messages: {error}")

    def get_message(self, message_id: str) -> Dict:
        """
        Get a specific email message by ID.
        
        Args:
            message_id: The ID of the message to retrieve
            
        Returns:
            Dictionary containing message details
        """
        try:
            return self.service.users().messages().get(
                userId=self.user_id,
                id=message_id,
                format='full'
            ).execute()
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