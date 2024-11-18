from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Union
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
import os
import inspect

class GoogleCalendarTool:
    """A tool for managing Google Calendar operations with a simplified interface."""
    
    SCOPES = ['https://www.googleapis.com/auth/calendar']
    
    def __init__(self, credentials_path: str = 'credentials.json', token_path: str = 'token.json'):
        """
        Initialize the Google Calendar Tool.
        
        Args:
            credentials_path: Path to the credentials.json file
            token_path: Path to save/load the token.json file
        """
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.creds = self._get_credentials()
        self.service = build('calendar', 'v3', credentials=self.creds)

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

    def _get_credentials(self) -> Credentials:
        """Handle OAuth2 authentication flow."""
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

    def create_event(self, 
                    summary: str,
                    start_time: Union[str, datetime],
                    end_time: Union[str, datetime],
                    description: str = None,
                    location: str = None,
                    attendees: List[str] = None,
                    timezone: str = 'UTC',
                    is_all_day: bool = False) -> Dict:
        """
        Create a new calendar event.
        
        Args:
            summary: Event title
            start_time: Start time (datetime object or ISO format string)
            end_time: End time (datetime object or ISO format string)
            description: Event description
            location: Event location
            attendees: List of attendee email addresses
            timezone: Timezone (IANA format)
            is_all_day: Whether this is an all-day event
            
        Returns:
            Created event object
        """
        event = {
            'summary': summary,
            'location': location,
            'description': description,
        }
        
        # Handle datetime formatting
        if is_all_day:
            if isinstance(start_time, datetime):
                start_time = start_time.date().isoformat()
            if isinstance(end_time, datetime):
                end_time = end_time.date().isoformat()
            event['start'] = {'date': start_time}
            event['end'] = {'date': end_time}
        else:
            if isinstance(start_time, datetime):
                start_time = start_time.isoformat()
            if isinstance(end_time, datetime):
                end_time = end_time.isoformat()
            event['start'] = {'dateTime': start_time, 'timeZone': timezone}
            event['end'] = {'dateTime': end_time, 'timeZone': timezone}
            
        if attendees:
            event['attendees'] = [{'email': email} for email in attendees]
            
        return self.service.events().insert(calendarId='primary', body=event).execute()

    def get_upcoming_events(self, 
                          max_results: int = 10, 
                          calendar_id: str = 'primary',
                          time_min: str = None) -> List[Dict]:
        """
        Get upcoming events from the calendar.
        
        Args:
            max_results: Maximum number of events to return
            calendar_id: Calendar ID to fetch events from
            time_min: Start time to look for events (defaults to now) (ISO 8601 format string)
            
        Returns:
            List of event objects
        """
        if time_min is None:
            time_min = datetime.now(timezone.utc)
        elif isinstance(time_min, str):
            time_min = datetime.fromisoformat(time_min).astimezone(timezone.utc)
            assert isinstance(time_min, datetime)
            
        events_result = self.service.events().list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        return events_result.get('items', [])

    def update_event(self,
                    event_id: str,
                    summary: str = None,
                    start_time: Union[str, datetime] = None,
                    end_time: Union[str, datetime] = None,
                    description: str = None,
                    location: str = None,
                    attendees: List[str] = None,
                    timezone: str = None) -> Dict:
        """
        Update an existing calendar event.
        
        Args:
            event_id: ID of the event to update
            summary: Event title
            start_time: Start time (datetime object or ISO 8601 format string)
            end_time: End time (datetime object or ISO 8601 format string)
            description: Event description
            location: Event location
            attendees: List of attendee email addresses
            timezone: Timezone (IANA format)
            is_all_day: Whether this is an all-day event
            
        Returns:
            Updated event object
        """
        # Get existing event
        event = self.service.events().get(calendarId='primary', eventId=event_id).execute()
        
        # Update fields if provided
        if summary:
            event['summary'] = summary
        if description:
            event['description'] = description
        if location:
            event['location'] = location
            
        if start_time:
            if isinstance(start_time, datetime):
                start_time = start_time.isoformat()
            if 'date' in event['start']:
                event['start'] = {'date': start_time.split('T')[0]}
            else:
                event['start']['dateTime'] = start_time
                if timezone:
                    event['start']['timeZone'] = timezone
                    
        if end_time:
            if isinstance(end_time, datetime):
                end_time = end_time.isoformat()
            if 'date' in event['end']:
                event['end'] = {'date': end_time.split('T')[0]}
            else:
                event['end']['dateTime'] = end_time
                if timezone:
                    event['end']['timeZone'] = timezone
                    
        if attendees:
            event['attendees'] = [{'email': email} for email in attendees]
            
        return self.service.events().update(
            calendarId='primary',
            eventId=event_id,
            body=event
        ).execute()

    def delete_event(self, event_id: str, calendar_id: str = 'primary') -> None:
        """
        Delete a calendar event.
        
        Args:
            event_id: ID of the event to delete
            calendar_id: Calendar ID containing the event
        """
        self.service.events().delete(calendarId=calendar_id, eventId=event_id).execute()

    def get_calendars(self) -> List[Dict]:
        """
        Get list of calendars available to the user.
        
        Returns:
            List of calendar objects
        """
        calendar_list = self.service.calendarList().list().execute()
        return calendar_list.get('items', [])

    def create_calendar(self, summary: str, description: str = None, timezone: str = 'UTC') -> Dict:
        """
        Create a new calendar.
        
        Args:
            summary: Calendar name
            description: Calendar description
            timezone: Calendar timezone
            
        Returns:
            Created calendar object
        """
        calendar = {
            'summary': summary,
            'timeZone': timezone
        }
        if description:
            calendar['description'] = description
            
        return self.service.calendars().insert(body=calendar).execute()

    def get_free_busy(self, 
                     time_min: str,
                     time_max: str,
                     calendar_ids: List[str] = None) -> Dict:
        """
        Get free/busy information for calendars.
        
        Args:
            time_min: Start time to check (ISO 8601 format string)
            time_max: End time to check (ISO 8601 format string)
            calendar_ids: List of calendar IDs to check (defaults to primary)
            
        Returns:
            Free/busy information for the specified calendars
        """
        if calendar_ids is None:
            calendar_ids = ['primary']
            
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": calendar_id} for calendar_id in calendar_ids]
        }
        
        return self.service.freebusy().query(body=body).execute()