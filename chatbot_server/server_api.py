from typing import Union, Dict
from dataclasses import dataclass, asdict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.requests import Request
from uuid import uuid4
import xml.etree.ElementTree as ET
from secret_keys import POSTGRES_DB_PASSWORD
from prompts import SYS_PROMPT_V3, SYS_PROMPT_MD_TOP, SYS_PROMPT_MD_BOTTOM
import psycopg2
from datetime import datetime, timedelta
import pytz
import logging
import json
from llm_chatbot.chatbot import ChatBot
from llm_chatbot import utils, function_tools
from chatbot_server.data_models import ClientRequest, MessageResponse

logger = logging.getLogger(__name__)

# tools_prompt = TOOLS_PROMPT_SNIPPET.format(
#     TOOL_LIST=function_tools.get_tool_list_prompt(function_tools.get_tools())
# )
# chatbot_system_msg = SYS_PROMPT.format(
#     TOOLS_PROMPT=tools_prompt, RESPONSE_FLOW=RESPONSE_FLOW_2
# )
chatbot_system_msg = SYS_PROMPT_MD_TOP + SYS_PROMPT_MD_BOTTOM
db_config = {
    "dbname": "chatbot_db",
    "user": "chatbot_user",
    "password": POSTGRES_DB_PASSWORD,
    "host": "forge",
    "port": "5432",
}

app = FastAPI()

active_sessions: dict[str, ChatBot] = {}

def get_active_user_sessions(user_id: str):
    db_conn = psycopg2.connect(**db_config)
    cur = db_conn.cursor()
    cur.execute("""
        SELECT chat_id FROM chat_sessions WHERE user_id = %s
    """, (user_id,))
    return cur.fetchall()

def get_latest_chat_session(user_id: str):
    db_conn = psycopg2.connect(**db_config)
    cur = db_conn.cursor()
    try:
        cur.execute("""
            SELECT chat_id, created_at 
            FROM chat_sessions 
            WHERE user_id = %s 
            ORDER BY created_at DESC 
            LIMIT 1
        """, (user_id,))
        result = cur.fetchone()
        return result if result else (None, None)
    finally:
        cur.close()
        db_conn.close()

def get_session(user_id: str, chat_id="latest", model="Qwen/Qwen2.5-72B-Instruct"):
    # Define maximum session age (e.g., 24 hours)
    MAX_SESSION_AGE = timedelta(hours=24)
    
    if chat_id == "latest":
        # Get the latest session from database
        latest_chat_id, created_at = get_latest_chat_session(user_id)
        
        # Check if we have a recent valid session
        if latest_chat_id and created_at:
            # Convert current time to UTC timezone-aware datetime
            current_time = datetime.now(tz=created_at.tzinfo)
            # Make sure created_at is timezone-aware (assuming it's in UTC)
            if created_at.tzinfo is None:
                created_at = pytz.UTC.localize(created_at)
            
            session_age = current_time - created_at
            if session_age <= MAX_SESSION_AGE:
                chat_id = latest_chat_id
        else:
            chat_id = None
    
    # If we have a specific chat_id or valid latest session, try to load from active_sessions
    if chat_id and user_id in active_sessions and active_sessions[user_id].chat_id == chat_id:
        print(f"returning existing session for {user_id}")
        return active_sessions[user_id]
    
    print(f"creating new session for {user_id}")
    # Create new session
    active_sessions[user_id] = ChatBot(
        model="perplexity/llama-3.1-sonar-large-128k-chat",
        tokenizer_model="meta-llama/Llama-3.1-70B-Instruct",
        user_id=user_id,
        chat_id=str(uuid4()) if chat_id is None else chat_id,
        system=SYS_PROMPT_V3,
        db_config=db_config
    )
    return active_sessions[user_id]

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.info(f"Client connected: {user_id}")

    def disconnect(self, user_id: str):
        self.active_connections.pop(user_id, None)
        logger.info(f"Client disconnected: {user_id}")

    async def send_message(self, user_id: str, message: dict):
        if websocket := self.active_connections.get(user_id):
            try:
                await websocket.send_json(message)
                logger.debug("sent message successfully")
            except Exception as e:
                logger.error(f"Error sending message to {user_id}: {e}")
                print(f"disconnecting {user_id} due to error")
                self.disconnect(user_id)

manager = ConnectionManager()

# Add WebSocket endpoint
@app.websocket("/{user_id}/ws")
async def websocket_endpoint(websocket: WebSocket, user_id: str, force_new_session: bool = False):
    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_json()
            client_request = ClientRequest(**data)
            
            # Get or create chatbot session
            chatbot = get_session(
                user_id = client_request.user_id,
                chat_id = None if force_new_session else "latest"
            )
            
            # Process message
            response = await chatbot(client_request.message, client_type=client_request.client_type)
            sanitized_response = utils.sanitize_inner_content(response)
            root = ET.fromstring(f"<root>{sanitized_response}</root>")
            
            # Extract user response
            user_response = root.find('.//response_to_user')
            response_text = user_response.text.strip() if user_response is not None else ""
            
            # Send response back through WebSocket
            await manager.send_message(
                user_id,
                asdict(MessageResponse(
                    client_type=client_request.client_type,
                    content=response_text,
                    raw_response=sanitized_response
                ))
            )
    except WebSocketDisconnect:
        logger.info("websocket disconnected!")
        manager.disconnect(user_id)
    except Exception as e:
        logger.error(f"Error in WebSocket connection for {user_id}: {e}")
        manager.disconnect(user_id)

# Modify existing endpoint to support WebSocket notifications
@app.post("/{user_id}/{session_id}/message")
async def process_message(user_id: str, session_id: str, client_request: ClientRequest):
    # Get or create chatbot session
    chatbot = get_session(user_id=user_id)
    response = chatbot(client_request.message)
    sanitized_response = utils.sanitize_inner_content(response)
    root = ET.fromstring(f"<root>{sanitized_response}</root>")
    
    # Extract user response
    user_response = root.find('.//response_to_user')
    response_text = user_response.text.strip() if user_response is not None else ""
    
    # If client is connected via WebSocket, send notification
    if user_id in manager.active_connections:
        await manager.send_message(
            user_id,
            MessageResponse(
                client_type=client_request.client_type,
                content=response_text,
                raw_response=sanitized_response
            )
        )
    
    return response_text
