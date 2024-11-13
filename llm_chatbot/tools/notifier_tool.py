import requests
from typing import Dict, List, Optional, Union
import json
import inspect
from datetime import datetime
from pydantic import BaseModel, Field
import loguru

class NotificationTask(BaseModel):
    """Data model for notification tasks."""
    trigger_time: datetime
    notification_type: str = Field(..., description="Type of notification: 'text' or 'function'")
    content: Union[str, Dict] = Field(..., description="Text message or serialized function with args")
    user_id: str
    chat_id: str
    metadata: Optional[Dict] = Field(default={}, description="Additional task metadata")

class NotifierTool:
    """Tool for scheduling and managing notifications through the Notifier Service."""
    
    def __init__(self, api_url: str = "http://localhost:8001", logger=None):
        """
        Initialize the Notifier Tool.
        
        Args:
            api_url: Base URL of the Notifier Service API
            logger: Logger instance (defaults to loguru.logger)
        """
        self.api_url = api_url.rstrip('/')
        self.logger = logger or loguru.logger

    def _get_available_methods(self) -> List[Dict[str, str]]:
        """Get list of available methods with documentation."""
        methods = []
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            if not name.startswith('_'):
                signature = str(inspect.signature(method))
                docstring = inspect.getdoc(method) or "No documentation available"
                
                methods.append({
                    "name": name,
                    "docstring": docstring,
                    "signature": f"{name}{signature}",
                    "func": method
                })
        return sorted(methods, key=lambda x: x["name"])

    def schedule_reminder(self, message: str, trigger_time: Union[str, datetime], user_id: str, chat_id: str = "latest") -> str:
        """Schedule a text reminder to be sent at a specific time."""
        try:
            self.logger.debug("Scheduling reminder for user {user_id}, message: {message}", 
                            user_id=user_id, message=message)

            # Convert string to datetime if needed
            if isinstance(trigger_time, str):
                self.logger.debug("Converting trigger_time from string: {time}", time=trigger_time)
                trigger_time = datetime.fromisoformat(trigger_time)

            task = NotificationTask(
                trigger_time=trigger_time,
                notification_type="text",
                content=message,
                user_id=user_id,
                chat_id=chat_id
            )

            self.logger.debug("Sending schedule request to notifier service: {task}", 
                            task=task.model_dump())
            
            response = requests.post(
                f"{self.api_url}/schedule",
                json=task.model_dump()
            )
            self.logger.debug("Schedule request response status: {status_code}", 
                            status_code=response.status_code)
            
            response.raise_for_status()
            response_data = response.json()
            
            self.logger.info("Successfully scheduled reminder {job_id} for user {user_id}", 
                           job_id=response_data["job_id"], user_id=user_id)
            
            return json.dumps({
                "status": "success",
                "job_id": response_data["job_id"],
                "scheduled_time": trigger_time.isoformat(),
                "message": message
            })
            
        except Exception as e:
            self.logger.error("Failed to schedule reminder: {error}", error=str(e))
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    def cancel_reminder(self, job_id: str) -> str:
        """Cancel a previously scheduled reminder."""
        try:
            self.logger.debug("Attempting to cancel reminder {job_id}", job_id=job_id)
            
            response = requests.delete(f"{self.api_url}/cancel/{job_id}")
            self.logger.debug("Cancel request response status: {status_code}", 
                            status_code=response.status_code)
            
            response.raise_for_status()
            
            self.logger.info("Successfully cancelled reminder {job_id}", job_id=job_id)
            return json.dumps({
                "status": "success",
                "message": f"Reminder {job_id} cancelled successfully"
            })
            
        except requests.exceptions.HTTPError as e:
            self.logger.error("Failed to cancel reminder {job_id}: not found. {error}", 
                            job_id=job_id, error=str(e))
            return json.dumps({
                "status": "error",
                "message": f"Reminder not found: {str(e)}"
            })
        except Exception as e:
            self.logger.error("Error cancelling reminder {job_id}: {error}", 
                            job_id=job_id, error=str(e))
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    def list_reminders(self, user_id: Optional[str] = None) -> str:
        """List all pending reminders, optionally filtered by user."""
        try:
            self.logger.debug("Listing reminders for user: {user_id}", 
                            user_id=user_id or "all users")
            
            params = {"user_id": user_id} if user_id else None
            response = requests.get(f"{self.api_url}/pending", params=params)
            self.logger.debug("List reminders response status: {status_code}", 
                            status_code=response.status_code)
            
            response.raise_for_status()
            reminders = response.json()
            
            self.logger.info("Found {count} pending reminders for {user}", 
                           count=len(reminders), 
                           user=user_id if user_id else "all users")
            
            return json.dumps({
                "status": "success",
                "count": len(reminders),
                "reminders": reminders
            })
            
        except Exception as e:
            self.logger.error("Error listing reminders: {error}", error=str(e))
            return json.dumps({
                "status": "error",
                "message": str(e)
            })