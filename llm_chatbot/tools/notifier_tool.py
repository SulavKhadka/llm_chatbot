import requests
from typing import Dict, List, Optional, Union
import json
import inspect
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
import loguru
import re
from chatbot_data_models import ToolStatus, ToolMethodStatus, ToolState


class NotificationTask(BaseModel):
    """Data model for notification tasks."""
    trigger_time: str
    notification_type: str = Field(..., description="Type of notification: 'text' or 'function'")
    content: Union[str, Dict] = Field(..., description="Text message or serialized function with args")
    user_id: str
    chat_id: str
    metadata: Optional[Dict] = Field(default={}, description="Additional task metadata")


class NotifierTool:
    """Tool for scheduling and managing time-based notifications and reminders.
    Useful for timers, alarms, reminders, etc. Its a flexible tool with a lot of ability if wielded with a sharp, creative, open mind.
    A notification gets sent to the chatbot(you) under the user_id that schedules it at the specified time given."""
    
    def __init__(self, api_url: str = "http://localhost:8001", logger=None):
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
    
    def _get_tool_status(self) -> Dict[str, bool]:
        
        tool_status = ToolStatus(
            status=ToolState.UNOPERATIONAL,
            methods={}
        )
        
        for tool_method in self._get_available_methods():
            method_health = ToolMethodStatus(
                status = ToolState.UNOPERATIONAL,
                error = ""
            )

            job_id = None
            message = "health check ping: schedule_reminder"
            trigger_time = (datetime.now() + timedelta(minutes=30)).isoformat()
            user_id = "health_check_user_NotifierTool"
            try:
                if tool_method['name'] == "schedule_reminder":
                        response = self.schedule_reminder(message=message, trigger_time=trigger_time, user_id=user_id)
                        job_id = response.get('job_id', None)
                
                elif tool_method['name'] == "cancel_reminder":
                        if job_id is None:
                            job_resp = self.schedule_reminder(message=message, trigger_time=trigger_time, user_id=user_id)
                            if job_resp.get('success', False):
                                job_id = job_resp['job_id']
                        response = self.cancel_reminder(job_id=job_id)

                elif tool_method['name'] == "list_reminders":
                        response = self.list_reminders(user_id=user_id)
                
                method_health.status = response.get('success', False)
                if method_health.status is False:
                    method_health.error = response.get('message', '')

            except Exception as e:
                method_health.status = False
                method_health.error = e
            
            tool_status.methods[tool_method['name']] = method_health
        
        num_healthy_tool_methods = sum([m.status for m in tool_status.methods.values()])
        if num_healthy_tool_methods <= 0:
            tool_status.status = ToolState.UNOPERATIONAL
        elif num_healthy_tool_methods < len(tool_status.methods):
            tool_status.status = ToolState.PARTIALLY_OPERATIONAL
        elif num_healthy_tool_methods == len(tool_status.methods):
            tool_status.status = ToolState.FULLY_OPERATIONAL
        
        return tool_status


    def _parse_time_input(self, time_input: str) -> datetime:
        """Convert time input to datetime object.
        
        Handles:
        - ISO datetime ("2024-01-01T10:00:00")
        - Duration format ("dd:hh:mm:ss")
        """
        # Try parsing as ISO format first
        try:
            return datetime.fromisoformat(time_input)
        except ValueError:
            pass

        # Try parsing as duration format (dd:hh:mm:ss)
        pattern = r'^(\d+:)?(\d+:)?(\d+:)?(\d+)$'
        if not re.match(pattern, time_input):
            raise ValueError(
                "Time must be either ISO datetime (2024-01-01T10:00:00) or "
                "duration (dd:hh:mm:ss)"
            )

        parts = [int(p) for p in time_input.split(':')]
        parts = [0] * (4 - len(parts)) + parts  # Pad with zeros from left
        days, hours, minutes, seconds = parts

        self.logger.debug(
            "Parsed duration - days: {d}, hours: {h}, mins: {m}, secs: {s}", 
            d=days, h=hours, m=minutes, s=seconds
        )

        return datetime.now() + timedelta(
            days=days,
            hours=hours,
            minutes=minutes,
            seconds=seconds
        )

    def schedule_reminder(self, message: str, trigger_time: str, user_id: str, chat_id: str = "latest") -> str:
        """Schedule a message reminder for a future time.

        Args:
            message: Text message to send
            trigger_time: When to send - ISO datetime ("2024-01-01T10:00:00") or duration ("dd:hh:mm:ss")
            user_id: Target user ID
            chat_id: Chat session ID (default: "latest")

        Returns:
            str: JSON response with fields:
            - success: True or False
            - job_id: Scheduled reminder ID (on success)
            - scheduled_time: ISO datetime for reminder
            - message: Success confirmation or error details
        """
        try:
            self.logger.debug("Scheduling reminder - time: {t}, user: {u}", t=trigger_time, u=user_id)

            parsed_time = self._parse_time_input(trigger_time)
            self.logger.debug("Parsed trigger time: {time}", time=parsed_time.isoformat())

            task = NotificationTask(
                trigger_time=parsed_time.isoformat(),
                notification_type="text",
                content=message,
                user_id=user_id,
                chat_id=chat_id
            )

            response = requests.post(
                f"{self.api_url}/schedule",
                json=task.model_dump()
            )
            self.logger.debug("Schedule request status: {code}", code=response.status_code)
            
            response.raise_for_status()
            response_data = response.json()
            
            self.logger.info("Scheduled reminder {id} for {time}", 
                           id=response_data["job_id"], 
                           time=parsed_time.isoformat())
            
            return {
                "success": True,
                "job_id": response_data["job_id"],
                "scheduled_time": parsed_time.isoformat(),
                "message": message
            }
            
        except Exception as e:
            self.logger.error("Schedule failed: {error}", error=str(e))
            return {
                "success": False,
                "message": str(e)
            }

    def cancel_reminder(self, job_id: str) -> str:
        """Cancel a scheduled reminder using its ID.

        Args:
            job_id: ID of reminder to cancel

        Returns:
            str: JSON response with fields:
            - success: True or False
            - message: Confirmation or error details
        """
        try:
            self.logger.debug("Cancelling reminder {id}", id=job_id)
            
            response = requests.delete(f"{self.api_url}/cancel/{job_id}")
            self.logger.debug("Cancel request status: {code}", code=response.status_code)
            
            response.raise_for_status()
            
            self.logger.info("Cancelled reminder {id}", id=job_id)
            return {
                "success": True,
                "message": f"Reminder {job_id} cancelled successfully"
            }
            
        except requests.exceptions.HTTPError as e:
            self.logger.error("Cancel failed - reminder {id} not found: {e}", id=job_id, e=str(e))
            return {
                "success": False,
                "message": f"Reminder not found: {str(e)}"
            }
        except Exception as e:
            self.logger.error("Cancel failed: {error}", error=str(e))
            return {
                "success": False,
                "message": str(e)
            }

    def list_reminders(self, user_id: Optional[str] = None) -> str:
        """List pending reminders for a user or all users.

        Args:
            user_id: Optional - filter reminders for specific user

        Returns:
            str: JSON response with fields:
            - success: True or False
            - count: Number of reminders found
            - reminders: List of reminder details (on success)
            - message: Error details (on failure)
        """
        try:
            self.logger.debug("Listing reminders for {user}", user=user_id or "all users")
            
            params = {"user_id": user_id} if user_id else None
            response = requests.get(f"{self.api_url}/pending", params=params)
            self.logger.debug("List request status: {code}", code=response.status_code)
            
            response.raise_for_status()
            reminders = response.json()
            
            self.logger.info("Found {n} reminders for {u}", 
                           n=len(reminders), 
                           u=user_id if user_id else "all users")
            
            return {
                "success": True,
                "count": len(reminders),
                "reminders": reminders
            }
            
        except Exception as e:
            self.logger.error("List failed: {error}", error=str(e))
            return {
                "success": False,
                "message": str(e)
            }