from typing import Union
from dataclasses import dataclass, asdict
from fastapi import FastAPI
from llm_chatbot.chatbot import ChatBot
from llm_chatbot import utils, function_tools
from uuid import uuid4
import xml.etree.ElementTree as ET
from secret_keys import POSTGRES_DB_PASSWORD
from prompts import SYS_PROMPT_V3, SYS_PROMPT_MD_TOP, SYS_PROMPT_MD_BOTTOM

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

@dataclass
class ClientRequest:
    user_id: str
    client_type: str
    message: str
    user_metadata: dict

active_sessions: dict[str, ChatBot] = {}

def get_session(user_id: str, chat_id=None, model="Qwen/Qwen2.5-72B-Instruct"):
    if user_id not in active_sessions:
        active_sessions[user_id] = ChatBot(
            model = "perplexity/llama-3.1-sonar-large-128k-chat",
            tokenizer_model= "meta-llama/Llama-3.1-70B-Instruct",
            user_id = user_id,
            chat_id = str(uuid4()) if chat_id is None else chat_id,
            system=SYS_PROMPT_V3,
            db_config=db_config
        )
    return active_sessions[user_id]

@app.post("/{user_id}/{session_id}/message")
def process_message(user_id: str, session_id: str, client_request: ClientRequest, only_user_response: bool = True):
    if session_id.lower() == "latest":
        chatbot = get_session(user_id=user_id)
    else:
        chatbot = get_session(user_id=user_id, chat_id=session_id)
    
    print(client_request.message)
    if client_request.client_type == "notifier":
        response = chatbot(str(asdict(client_request)), role="tool")
    response = chatbot(client_request.message)
    print(response)
    sanitized_response = utils.sanitize_inner_content(response)
    root = ET.fromstring(f"<root>{sanitized_response}</root>")

    if (only_user_response is False):
        return utils.unsanitize_content(sanitized_response)
    
    # Extract text from <response_to_user> tag
    response_to_user = root.find(".//response_to_user")
    return utils.unsanitize_content(response_to_user.text)
