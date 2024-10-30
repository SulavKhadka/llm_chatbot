from typing import Union
from dataclasses import dataclass
from fastapi import FastAPI
from llm_chatbot.chatbot import ChatBot
from llm_chatbot import utils, function_tools
from uuid import uuid4
from secret_keys import POSTGRES_DB_PASSWORD
from prompts import SYS_PROMPT, TOOLS_PROMPT_SNIPPET, RESPONSE_FLOW_2

tools_prompt = TOOLS_PROMPT_SNIPPET.format(
    TOOL_LIST=function_tools.get_tool_list_prompt(function_tools.get_tools())
)
chatbot_system_msg = SYS_PROMPT.format(
    TOOLS_PROMPT=tools_prompt, RESPONSE_FLOW=RESPONSE_FLOW_2
)
db_config = {
    "dbname": "chatbot_db",
    "user": "chatbot_user",
    "password": POSTGRES_DB_PASSWORD,
    "host": "localhost",
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

def get_session(user_id: str, model="Qwen/Qwen2.5-72B-Instruct"):
    if user_id not in active_sessions:
        active_sessions[user_id] = ChatBot(
            model = model,
            tokenizer_model= model,
            user_id = user_id,
            chat_id = str(uuid4()),
            system=chatbot_system_msg,
            db_config=db_config
        )
    return active_sessions[user_id]

@app.post("/{user_id}/message")
def process_message(user_id: str, client_request: ClientRequest):
    chatbot = get_session(user_id)
    response = chatbot(client_request)
    print(response)
    return response