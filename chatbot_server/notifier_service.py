from fastapi import FastAPI, HTTPException
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from datetime import datetime
from typing import Optional, Union, Dict, Any
import dill  # For function serialization
import requests
from pydantic import BaseModel, Field
import asyncio
from sqlalchemy import create_engine
import json
import loguru

from secret_keys import POSTGRES_DB_PASSWORD

class NotificationTask(BaseModel):
    trigger_time: datetime
    notification_type: str = Field(..., description="Type of notification: 'text' or 'function'")
    content: Union[str, Dict[str, Any]] = Field(..., description="Text message or serialized function with args")
    user_id: str
    chat_id: str
    metadata: Optional[Dict] = Field(default={}, description="Additional task metadata")

class NotifierService:
    def __init__(self, db_url: str, api_url: str, logger):
        """
        Initialize the notifier service.
        
        Args:
            db_url: PostgreSQL connection URL
            api_url: URL for the chatbot API
        """
        self.api_url = api_url
        self.logger = logger
        
        # Configure job stores
        jobstores = {
            'default': SQLAlchemyJobStore(url=db_url)
        }
        
        # Initialize scheduler
        self.scheduler = AsyncIOScheduler(jobstores=jobstores)
        self.scheduler.start()
        
    async def schedule_notification(self, task: NotificationTask) -> str:
        """Schedule a new notification task."""
        try:
            self.logger.debug("scheduling notification, type: {type}", type=task.notification_type)
            if task.notification_type == "text":
                job = self.scheduler.add_job(
                    self._send_text_notification,
                    'date',
                    run_date=task.trigger_time,
                    args=[task.content, task.user_id, task.chat_id],
                    kwargs=task.metadata
                )
                self.logger.info("text notification scheduled. JobID: {job_id}", job_id=job.id)
            elif task.notification_type == "function":
                # Deserialize function and args
                func_data = task.content
                serialized_func = func_data.get("function")
                args = func_data.get("args", [])
                kwargs = func_data.get("kwargs", {})
                
                # Schedule function execution
                job = self.scheduler.add_job(
                    self._execute_function,
                    'date',
                    run_date=task.trigger_time,
                    args=[serialized_func, args, kwargs, task.user_id, task.chat_id],
                    kwargs=task.metadata
                )
                self.logger.info("function execution notification scheduled. JobID: {job_id}", job_id=job.id)
            else:
                self.logger.error("Invalid notification type: {task_type}", task_type=task.notification_type)
                raise ValueError(f"Invalid notification type: {task.notification_type}")
            return job.id
            
        except Exception as e:
            self.logger.error("Failed to schedule notification: {error}", error=e)
            raise HTTPException(status_code=500, detail=f"Failed to schedule notification: {str(e)}")

    async def _send_text_notification(self, message: str, user_id: str, chat_id: str="latest", **metadata):
        """Send a text notification via the chatbot API."""
        try:
            self.logger.debug("sending text notification with message {message}", message=message)
            response = requests.post(
                f"{self.api_url}/{user_id}/{chat_id}/message",
                json={
                    "user_id": user_id,
                    "client_type": "notifier",
                    "message": message,
                    "user_metadata": metadata
                }
            )
            self.logger.debug("text notification delivery response status: {status_code}", status_code=response.status_code)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error("Failed to send notification: {e}", e=str(e))
            # Could implement retry logic here

    async def _execute_function(self, serialized_func: str, args: list, 
                              kwargs: dict, user_id: str, chat_id: str, **metadata):
        """Execute a serialized function and send results via chatbot API."""
        try:
            self.logger.debug("sending function execution notification with message: {func}", func=serialized_func)
            # Deserialize and execute function
            func = dill.loads(serialized_func)
            self.logger.debug("serialized function loaded: {func}", func=func)

            result = func(*args, **kwargs)
            self.logger.info("function execution result: {result}", result=result)

            # Send result via chatbot API
            message = f"Function execution result:\n{result}"
            await self._send_text_notification(message, user_id, chat_id, **metadata)

            return result
        except Exception as e:
            self.logger.error("Function execution failed: {e}", e=e)
            error_msg = f"Function execution failed: {str(e)}"
            await self._send_text_notification(error_msg, user_id, chat_id, **metadata)
            raise

    async def cancel_notification(self, job_id: str) -> bool:
        """Cancel a scheduled notification by job ID."""
        try:
            self.scheduler.remove_job(job_id)
            self.logger.error("notification job removal successful for ID: {job_id}", job_id=job_id)
            return True
        except Exception as e:
            self.logger.error("notification job removal failed for ID: {job_id}", job_id=job_id)
            raise HTTPException(status_code=404, detail=f"Job not found: {str(e)}")

    def list_pending_notifications(self, user_id: Optional[str] = None) -> list:
        """List all pending notifications, optionally filtered by user_id."""
        self.logger.debug("getting pending jobs for user: {u_id}", u_id=user_id)
        jobs = self.scheduler.get_jobs()
        self.logger.info("found {n} pending jobs for user", n=len(jobs))

        if user_id:
            return [
                {
                    "job_id": job.id,
                    "trigger_time": job.next_run_time,
                    "user_id": job.args[1] if len(job.args) > 1 else None
                }
                for job in jobs
                if len(job.args) > 1 and job.args[1] == user_id
            ]
        
        return [
            {
                "job_id": job.id,
                "trigger_time": job.next_run_time,
                "user_id": job.args[1] if len(job.args) > 1 else None
            }
            for job in jobs
        ]

# FastAPI app setup
app = FastAPI()
notifier = NotifierService(
    db_url=f"postgresql://chatbot_user:{POSTGRES_DB_PASSWORD}@100.78.237.8:5432/chatbot_db",
    api_url="http://100.78.237.8:8000/",
    logger = loguru.logger
)

@app.post("/schedule")
async def schedule_notification(task: NotificationTask):
    job_id = await notifier.schedule_notification(task)
    return {"job_id": job_id}

@app.delete("/cancel/{job_id}")
async def cancel_notification(job_id: str):
    success = await notifier.cancel_notification(job_id)
    return {"success": success}

@app.get("/pending")
async def list_pending(user_id: Optional[str] = None):
    return notifier.list_pending_notifications(user_id)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)