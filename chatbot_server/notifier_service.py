import datetime
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Union, Any
from loguru import logger
import logfire
import sys
import requests
from secret_keys import POSTGRES_DB_PASSWORD
from enum import Enum

class ClientType(Enum):
    CHAT = "chat"
    VOICE = "voice"
    TERMINAL = "terminal"
    USER = "user"

# --- Notifier Service Imports ---
from fastapi import FastAPI, HTTPException
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from datetime import datetime
import dill  # For function serialization

# --- Notifier Service Models ---
class NotificationTask(BaseModel):
    trigger_time: datetime
    notification_type: str = Field(
        ..., description="Type of notification: 'text' or 'function'"
    )
    content: Union[str, Dict[str, Any]] = Field(
        ..., description="Text message or serialized function with args"
    )
    user_id: str
    chat_id: str
    metadata: Optional[Dict] = Field(
        default={}, description="Additional task metadata"
    )

# --- Logging Configuration ---
# Configure logfire
logfire.configure(scrubbing=False)

# Configure loguru
logger.remove()  # Remove default handler

# Add handler for INFO level logs to stderr
logger.add(
    sys.stderr,
    format="{message}",
    filter=lambda record: record["level"].name == "INFO",
    serialize=True,
)

# Enable APScheduler's internal logging
aps_logger = logger.bind(module="apscheduler")
aps_logger.add(
    "apscheduler.log",
    format="{time} {level} {message}",
    level="DEBUG",
    rotation="10 MB",
    compression="zip",
)

# Add handler for detailed logs to a file
logger.add(
    "notifier_full.log",
    format="{message}",
    filter=lambda record: record["level"].name
    in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    serialize=True,
)

# --- Module-Level Job Functions ---
async def send_text_notification(
    api_url: str,
    message: str,
    user_id: str,
    chat_id: str = "latest",
    metadata: Dict[str, Any] = None,
):
    if metadata is None:
        metadata = {}
    try:
        logger.debug(
            "Sending text notification to user_id={}, chat_id={}, message={}",
            user_id,
            chat_id,
            message,
        )
        response = requests.post(
            f"{api_url}/{user_id}/{chat_id}/message",
            json={
                "user_id": user_id,
                "client_type": ClientType.VOICE.value,
                "message": message,
                "user_metadata": metadata,
            },
        )
        logger.debug(
            "Text notification delivery response status: {}",
            response.status_code,
        )
        response.raise_for_status()
        logger.info(
            "Text notification sent successfully for user_id={}, chat_id={}, job_response={}",
            user_id,
            chat_id,
            response.json(),
        )
        return response.json()
    except Exception as e:
        logger.error("Failed to send text notification: {}", e)
        # Implement retry logic or other error handling as needed


async def execute_function_notification(
    api_url: str,
    serialized_func: bytes,
    args: list,
    kwargs: dict,
    user_id: str,
    chat_id: str,
    metadata: Dict[str, Any] = None,
):
    if metadata is None:
        metadata = {}
    try:
        logger.debug(
            "Executing serialized function for user_id={}, chat_id={}",
            user_id,
            chat_id,
        )
        # Deserialize the function
        func = dill.loads(serialized_func)
        logger.debug("Deserialized function: {}", func)

        # Execute the function
        result = func(*args, **kwargs)
        logger.info(
            "Function executed successfully for user_id={}, chat_id={}, result={}",
            user_id,
            chat_id,
            result,
        )

        # Send the result via chatbot API
        message = f"Function execution result:\n{result}"
        await send_text_notification(api_url, message, user_id, chat_id, metadata)

        return result
    except Exception as e:
        logger.error("Function execution failed for user_id={}, chat_id={}: {}", user_id, chat_id, e)
        error_msg = f"Function execution failed: {str(e)}"
        await send_text_notification(api_url, error_msg, user_id, chat_id, metadata)
        raise

# --- Notifier Service Class ---
class NotifierService:
    def __init__(self, db_url: str, api_url: str):
        """
        Initialize the notifier service.

        Args:
            db_url: PostgreSQL connection URL
            api_url: URL for the chatbot API
        """
        self.api_url = api_url

        # Configure job stores
        jobstores = {
            "default": SQLAlchemyJobStore(url=db_url)
        }

        # Initialize scheduler
        self.scheduler = AsyncIOScheduler(jobstores=jobstores)
        self.scheduler.start()
        logger.info("NotifierService initialized with db_url={} and api_url={}", db_url, api_url)

    async def schedule_notification(self, task: NotificationTask) -> str:
        """Schedule a new notification task."""
        try:
            logger.debug("Scheduling notification, type={}", task.notification_type)
            if task.notification_type == "text":
                job = self.scheduler.add_job(
                    send_text_notification,
                    "date",
                    next_run_time=task.trigger_time,
                    args=[
                        self.api_url,
                        task.content,
                        task.user_id,
                        task.chat_id,
                    ],
                    kwargs=task.metadata,
                )
                logger.info(
                    "Text notification scheduled successfully. JobID={}",
                    job.id,
                )
            elif task.notification_type == "function":
                # Deserialize function and args
                func_data = task.content
                serialized_func = func_data.get("function")
                args = func_data.get("args", [])
                kwargs = func_data.get("kwargs", {})

                # Ensure serialized_func is bytes. If it's a string, encode it.
                if isinstance(serialized_func, str):
                    serialized_func = serialized_func.encode("latin1")  # Adjust encoding as needed

                # Schedule function execution
                job = self.scheduler.add_job(
                    execute_function_notification,
                    "date",
                    run_date=task.trigger_time,
                    args=[
                        self.api_url,
                        serialized_func,
                        args,
                        kwargs,
                        task.user_id,
                        task.chat_id,
                    ],
                    kwargs=task.metadata,
                )
                logger.info(
                    "Function execution notification scheduled successfully. JobID={}",
                    job.id,
                )
            else:
                logger.error("Invalid notification type: {}", task.notification_type)
                raise ValueError(f"Invalid notification type: {task.notification_type}")
            return job.id

        except HTTPException as http_exc:
            logger.error("HTTPException while scheduling notification: {}", http_exc.detail)
            raise http_exc
        except Exception as e:
            logger.error("Failed to schedule notification: {}", e)
            raise HTTPException(status_code=500, detail=f"Failed to schedule notification: {str(e)}")

    async def cancel_notification(self, job_id: str) -> bool:
        """Cancel a scheduled notification by job ID."""
        try:
            self.scheduler.remove_job(job_id)
            logger.info("Notification job removed successfully for JobID={}", job_id)
            return True
        except Exception as e:
            logger.error("Failed to remove notification job for JobID={}: {}", job_id, e)
            raise HTTPException(status_code=404, detail=f"Job not found: {str(e)}")

    def list_pending_notifications(self, user_id: Optional[str] = None) -> list:
        """List all pending notifications, optionally filtered by user_id."""
        try:
            logger.debug("Fetching pending jobs for user_id={}", user_id)
            jobs = self.scheduler.get_jobs()
            logger.info("Found {} pending jobs", len(jobs))

            pending = []
            for job in jobs:
                job_user_id = job.args[2] if len(job.args) > 2 else None  # Adjusted index
                if user_id is None or job_user_id == user_id:
                    pending.append(
                        {
                            "job_id": job.id,
                            "trigger_time": job.next_run_time,
                            "user_id": job_user_id,
                        }
                    )
            logger.debug("Listing {} pending notifications", len(pending))
            return pending
        except Exception as e:
            logger.error("Error listing pending notifications: {}", e)
            raise HTTPException(status_code=500, detail=f"Error listing pending notifications: {str(e)}")

# --- FastAPI App Setup ---
app = FastAPI()
notifier: Optional[NotifierService] = None

@app.on_event("startup")
async def startup_event():
    global notifier
    db_url = f"postgresql://chatbot_user:{POSTGRES_DB_PASSWORD}@100.78.237.8:5432/chatbot_db"
    api_url = "http://100.78.237.8:8000/"
    notifier = NotifierService(db_url=db_url, api_url=api_url)
    if notifier.scheduler.state == 0:
        notifier.scheduler.start()
    logger.info("APScheduler started and notifier service is ready.")

@app.on_event("shutdown")
async def shutdown_event():
    if notifier:
        notifier.scheduler.shutdown()
        logger.info("APScheduler shut down successfully.")

@app.post("/schedule")
async def schedule_notification(task: NotificationTask):
    logger.info("Received request to schedule notification: {}", task)
    job_id = await notifier.schedule_notification(task)
    logger.info("Notification scheduled with JobID={}", job_id)
    return {"job_id": job_id}

@app.delete("/cancel/{job_id}")
async def cancel_notification(job_id: str):
    logger.info("Received request to cancel notification with JobID={}", job_id)
    success = await notifier.cancel_notification(job_id)
    logger.info("Cancellation of JobID={} successful", job_id)
    return {"success": success}

@app.get("/pending")
async def list_pending(user_id: Optional[str] = None):
    logger.info("Received request to list pending notifications for user_id={}", user_id)
    pending = notifier.list_pending_notifications(user_id)
    logger.info("Returning {} pending notifications", len(pending))
    return pending

# --- Uvicorn Entry Point ---
if __name__ == "__main__":
    import uvicorn

    logger.info("Starting NotifierService FastAPI on host=0.0.0.0, port=8001")
    uvicorn.run(app, host="0.0.0.0", port=8001)
