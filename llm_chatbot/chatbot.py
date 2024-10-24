import json
import datetime
from transformers import AutoTokenizer
import openai
from pydantic import BaseModel
from typing import List, Dict, Optional
import ast
import xml.etree.ElementTree as ET
from loguru import logger
import logfire
import sys
import psycopg2
from psycopg2.extras import Json
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import re
from openai.types.chat.chat_completion import ChatCompletion

from llm_chatbot import function_tools, utils
from llm_chatbot.tools.python_sandbox import PythonSandbox
from secret_keys import HYPERBOLIC_API_KEY, POSTGRES_DB_PASSWORD, OPENROUTER_API_KEY
from prompts import CHAT_NOTES_PROMPT, CHAT_SESSION_NOTES_PROMPT


# Configure logfire
logfire.configure(scrubbing=False)
# Configure loguru
logger.remove()  # Remove default handler
logger.configure(handlers=[logfire.loguru_handler()])
logger.add(
    sys.stderr,
    format="{message}",
    filter=lambda record: record["level"].name == "INFO",
    serialize=True
)
logger.add(
    "chatbot_full.log",
    format="{message}",
    filter=lambda record: record["level"].name in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    serialize=True
)

class ChatBot:
    def __init__(self, model, chat_id, tokenizer_model="", system="", db_config=None):
        self.chat_id = chat_id
        self.system = {"role": "system", "content": system}
        self.model = model
        self.tokenizer_model = tokenizer_model if tokenizer_model != "" else model
        self.tokenizer = AutoTokenizer.from_pretrained(self.tokenizer_model)
        self.max_message_tokens = 32768
        self.max_reply_msg_tokens = 4096
        self.functions = function_tools.get_tools()

        self.purged_messages = []
        self.purged_messages_token_count = []
        self.messages = []
        self.messages_token_counts = []
        self.total_messages_tokens = 0

        # base_urls = [ "https://openrouter.ai/api/v1", "https://api.together.xyz/v1", "https://api.groq.com/openai/v1", "https://api.hyperbolic.xyz/v1"]
        self.openai_client = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )
        self.open_router_extra_body = {"provider": {
                "order": [
                    "Together"
                ]
            }
        }

        # self.openai_client = openai.OpenAI(
        #     base_url="http://0.0.0.0:8000/v1",
        #     api_key="token123",
        # )

        if db_config is None:
            db_config = {
                "dbname":"chatbot_db",
                "user":"chatbot_user",
                "password": POSTGRES_DB_PASSWORD,
                "host": "localhost",
                "port": "5432"
            }
        
        global logger
        logger = logger.bind(chat_id=self.chat_id)

        # Initialize database if it doesn't exist
        self.initialize_db(**db_config)
        
        # Database connection
        self.conn = psycopg2.connect(**db_config)
        self.cur = self.conn.cursor()
        
        # Insert new chat session
        self.cur.execute("""
            INSERT INTO chat_sessions (chat_id, model, tokenizer_model, system_message)
            VALUES (%s, %s, %s, %s)
        """, (self.chat_id, self.model, self.tokenizer_model, system))
        self.conn.commit()

        self._add_message(self.system)
        logger.info({"event": "ChatBot_initialized", "model": model})
        logger.debug({"event": "Initial_system_message", "system_message": self.system})

    def __call__(self, message):
        logger.info({"event": "Received_user_message", "message": message})
        self._add_message({"role": "user", "content": message})

        self_recurse = True
        while self_recurse:
            self.rolling_memory()
            completion = self.execute()

            parsed_response = self._parse_results(completion.choices[0].message.content)
            
            llm_thought = f"<thought>\n{parsed_response['thought']}\n</thought>"

            if parsed_response['response']['type'] == "TOOL_CALL":
                tool_calls = parsed_response['response']['response']
                self._add_message({"role": "assistant", "content": f"{llm_thought}\n<tool_call>\n{parsed_response['response']['response']}\n</tool_call>"})
                if len(tool_calls) > 0:
                    logger.info({"event": "Extracted_tool_calls", "count": len(tool_calls)})
                    tool_call_responses = []
                    for tool_call in tool_calls:
                        fn_response = self._execute_function_call(tool_call)
                        tool_call_responses.append(fn_response)
                    tool_response_str = '\n'.join(tool_call_responses)
                    self._add_message({"role": "tool", "content": f"<tool_call_response>\n{tool_response_str}\n</tool_call_response>"})
                    continue
                else:
                    self_recurse = False
                    response = f"{llm_thought}\n<internal_response>\nno tool calls found, continuing on\n</internal_response>"
            
            if parsed_response['response']['type'] == "USER_RESPONSE":
                self_recurse = False
                response = f"{llm_thought}\n<response_to_user>\n{parsed_response['response']['response']}\n</response_to_user>"

            if parsed_response['response']['type'] == "SELF_RESPONSE":
                self._add_message({"role": "assistant", "content": f"{llm_thought}\n<internal_response>\n{parsed_response['response']['response']}\n</internal_response>"})
                continue

            if parsed_response['response']['type'] == "PLAN":
                self._add_message({"role": "assistant", "content": f"{llm_thought}\n<plan>\n{parsed_response['response']['response']}\n</plan>"})
                continue

        logger.info({"event": "Assistant_response", "response": response})
        message_id = self._add_message({"role": "assistant", "content": response})
        # self._get_chat_notes(message_id=message_id)
        return response

    @classmethod
    def initialize_db(cls, dbname: str, user: str, password: str, host: str = 'localhost', port: str = '5432'):
        cls._initialize_database(dbname, user, password, host, port)

    def _initialize_database(dbname: str, user: str, password: str, host: str = 'localhost', port: str = '5432'):
        """
        Initialize the database and create necessary tables if they don't exist.
        
        :param dbname: Name of the database
        :param user: Database user
        :param password: Database password
        :param host: Database host (default: 'localhost')
        :param port: Database port (default: '5432')
        """
        # Connect to PostgreSQL server
        conn = psycopg2.connect(dbname='postgres', user=user, password=password, host=host, port=port)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        # Create database if it doesn't exist
        cur.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{dbname}'")
        exists = cur.fetchone()
        if not exists:
            cur.execute(f"CREATE DATABASE {dbname}")
        
        cur.close()
        conn.close()

        # Connect to the newly created or existing database
        conn = psycopg2.connect(dbname=dbname, user=user, password=password, host=host, port=port)
        cur = conn.cursor()

        # Create tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                chat_id UUID PRIMARY KEY,
                model VARCHAR(255) NOT NULL,
                tokenizer_model VARCHAR(255),
                system_message TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id SERIAL PRIMARY KEY,
                chat_id UUID REFERENCES chat_sessions(chat_id),
                role VARCHAR(50) NOT NULL,
                content TEXT NOT NULL,
                token_count INTEGER NOT NULL,
                is_purged BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS function_calls (
                id SERIAL PRIMARY KEY,
                chat_id UUID REFERENCES chat_sessions(chat_id),
                function_name VARCHAR(255) NOT NULL,
                parameters JSONB,
                response TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_notes (
                id SERIAL PRIMARY KEY,
                message_id SERIAL REFERENCES chat_messages(id),
                chat_id UUID REFERENCES chat_sessions(chat_id),
                notes TEXT,
                chat_summary TEXT,
                metadata JSONB
            )
        """)

        # Create indexes
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_id ON chat_messages(chat_id)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_function_calls_chat_id ON function_calls(chat_id)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_notes_chat_id ON chat_notes(chat_id)
        """)

        # Commit changes and close connection
        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"Database '{dbname}' and tables have been initialized successfully.")

    def _add_message(self, message):
        self.messages.append(message)
        token_count = len(self.tokenizer.encode(str(self.messages[-1])))
        self.messages_token_counts.append(token_count)
        self.total_messages_tokens = sum(self.messages_token_counts)
        
        self.cur.execute("""
            INSERT INTO chat_messages (chat_id, role, content, token_count)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (self.chat_id, message['role'], message['content'], token_count))
        message_id = self.cur.fetchone()[0]
        self.conn.commit()
        logger.debug({"event": "Added_message", "message": message, "token_count": token_count, "total_tokens": self.total_messages_tokens})
        return message_id

    def _parse_results(self, response_text: str):
        logger.debug({"event": "Parsing_llm_response", "response_text": response_text})
        response_text = utils.sanitize_inner_content(response_text)
        xml_root_element = f"<root>{response_text}</root>"
        
        try:
            root = ET.fromstring(xml_root_element)
        except ET.ParseError:
            root = utils.ensure_llm_response_format(response_text)

        parsed_resp = {
            "thought": "",
            "response": {
                "type": "",
                "response": ""
            }
        }

        thoughts = []
        for element in root.findall(".//thought"):
            thoughts.append(element.text)
        parsed_resp['thought'] = "\n".join(thoughts).strip()

        user_response = ""
        for element in root.findall(".//response_to_user"):
            user_response += element.text
        if user_response != "":
            parsed_resp['response']['type'] = "USER_RESPONSE"
            parsed_resp['response']['response'] = user_response.strip()
            return parsed_resp 

        self_response = ""
        for element in root.findall(".//internal_response"):
            self_response += element.text
        if self_response != "":
            parsed_resp['response']['type'] = "SELF_RESPONSE"
            parsed_resp['response']['response'] = self_response
            return parsed_resp 
        
        plan = []
        for element in root.findall(".//plan"):
            thoughts.append(element.text)
        if plan != []:
            parsed_resp['response']['type'] = "PLAN"
            parsed_resp['response']['response'] = plan
            return parsed_resp 
        
        tool_calls = self._extract_function_calls(response_text)
        if tool_calls != []:
            parsed_resp['response']['type'] = "TOOL_CALL"
            parsed_resp['response']['response'] = tool_calls
            return parsed_resp 
        
        parsed_resp['response']['type'] = "USER_RESPONSE"
        parsed_resp['response']['response'] = response_text
        return parsed_resp 

    def _extract_function_calls(self, response):
        logger.debug({"event": "Extracting_function_calls", "response": response})
        if '<tool_call>' not in response:
            logger.debug({"event": "No_tool_calls_found"})
            return []

        xml_root_element = f"<root>{response}</root>"
        root = ET.fromstring(xml_root_element)

        tool_calls = []
        for element in root.findall(".//tool_call"):
            json_data = None
            try:
                json_text = element.text.strip()
                try:
                    json_data = json.loads(json_text)
                except json.JSONDecodeError as json_err:
                    try:
                        json_data = ast.literal_eval(json_text)
                    except (SyntaxError, ValueError) as eval_err:
                        logger.error({"event": "JSON_parsing_failed", "json_decode_error": str(json_err), "fallback_error": str(eval_err), "problematic_json_text": json_text})
                        continue
            except Exception as e:
                logger.error({"event": "Cannot_strip_text", "error": str(e)})

            if json_data is not None:
                if isinstance(json_data, list):
                    tool_calls.extend(json_data)
                else:
                    tool_calls.append(json_data)
                logger.debug({"event": "Extracted_tool_call", "tool_call": json_data})

        logger.info({"event": "Extracted_tool_calls", "count": len(tool_calls)})
        return tool_calls

    def _execute_function_call(self, tool_call):
        logger.info({"event": "Executing_function_call", "tool_call": tool_call})
        function_name = tool_call.get("name", None)
        if function_name is not None and function_name in self.functions.keys():
            function_to_call = self.functions.get(function_name, {}).get('function', None)
            function_args = tool_call.get("parameters", {})

            logger.debug({"event": "Function_call_details", "name": function_name, "args": function_args})
            try:
                function_response = function_to_call.func(*function_args.values())
            except Exception as e:
                function_response = f"Function call errored out. Error: {e}"
            results_dict = f'{{"name": "{function_name}", "content": {function_response}}}'
            logger.debug({"event": "Function_call_response", "response": results_dict})
            
            # Log function call in database
            self.cur.execute("""
                INSERT INTO function_calls (chat_id, function_name, parameters, response)
                VALUES (%s, %s, %s, %s)
            """, (self.chat_id, function_name, Json(function_args), str(function_response)))
            self.conn.commit()
            return results_dict
        else:
            logger.warning({"event": "Invalid_function_name", "name": function_name})
            return '{}'

    def _get_chat_notes(self, message_id: str):

        self.cur.execute("""
                    SELECT notes FROM public.chat_notes
                    WHERE chat_id=%s
                    ORDER BY id DESC LIMIT 1
                """, (self.chat_id,))
        previous_notes = self.cur.fetchone()
        previous_notes = previous_notes[0] if previous_notes is not None else ""

        chat_transcript = ""
        for turn in self.messages:
            if turn.get('type', '') == "function_call":
                pass
                # print(f"{turn['type']}: {turn['name']}: {turn['parameters']}: {turn['response']}")
            else:
                if turn['role'].lower() != "system":
                    chat_transcript += f"{turn['role'].upper()}:\n{turn['content']}\n"
        messages = [
            {"role": "system", "content": CHAT_NOTES_PROMPT},
            {"role": "user", "content": f"extract information from the following conversation:\n<previous_notes>{previous_notes}</previous_notes>\n\n<conversation_transcript>{chat_transcript}</conversation_transcript>"}
        ]
        completion = self.get_llm_response(messages, model_name=self.model)

        logger.debug({"event": "parsing_chat_notes_llm_response", "response_text": completion})
        response_text = utils.sanitize_inner_content(completion.choices[0].message.content)
        xml_root_element = f"<root>{response_text}</root>"
        
        try:
            root = ET.fromstring(xml_root_element)
        except ET.ParseError as e:
            logger.error({"event": "failed_chat_summary_parsing", "error": e})
            raise(e)

        parsed_resp = {
            "notes": ""
        }
        
        notes = []
        for element in root.find(".//important_notes"):
            if element.tag == "note":
                notes.append(element.text)
        parsed_resp['notes'] = (previous_notes + "\n" + "\n".join(notes).strip()).strip()

        notes_id = self.cur.execute("""
            INSERT INTO chat_notes (message_id, chat_id, notes, chat_summary, metadata)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (message_id, self.chat_id, parsed_resp['notes'], "", Json({"model": self.model, "provider": str(self.openai_client.base_url)})))
        self.conn.commit()

    def _get_session_notes(self, message_id: str):
        self.cur.execute("""
                    SELECT notes FROM public.chat_notes
                    WHERE chat_id=%s
                    ORDER BY id DESC LIMIT 1
                """, (self.chat_id,))
        latest_session_notes = self.cur.fetchone()
        latest_session_notes = latest_session_notes[0] if latest_session_notes is not None else ""

        messages = [
            {"role": "system", "content": CHAT_SESSION_NOTES_PROMPT},
            {"role": "user", "content": f"<chat_session_notes>{latest_session_notes}</chat_session_notes>"}
        ]
        completion = self.get_llm_response(messages, model_name=self.model)

        logger.debug({"event": "parsing_session_end_notes_llm_response", "response_text": completion})
        response_text = utils.sanitize_inner_content(completion.choices[0].message.content)
        xml_root_element = f"<root>{response_text}</root>"
        
        try:
            root = ET.fromstring(xml_root_element)
        except ET.ParseError as e:
            logger.error({"event": "failed_session_final_notes_parsing", "error": e})
            raise(e)

        parsed_resp = {
            "notes": ""
        }
        
        notes = []
        for element in root.find(".//important_notes"):
            if element.tag == "note":
                notes.append(element.text)
        parsed_resp['notes'] = (latest_session_notes + "\n" + "\n".join(notes).strip()).strip()

        notes_id = self.cur.execute("""
            INSERT INTO chat_notes (message_id, chat_id, notes, chat_summary, metadata)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (message_id, self.chat_id, parsed_resp['notes'], "", Json({"model": self.model, "provider": str(self.openai_client.base_url)})))
        self.conn.commit()

    def __del__(self):
        self._get_session_notes(f"{self.chat_id}_final_session_notes")
        # Close database connection when the object is destroyed
        self.cur.close()
        self.conn.close()

    def execute(self):
        self.system['content'] = re.sub(pattern='<current_realtime_info>\n.*\n</current_realtime_info>', repl='', string=self.system['content'])
        current_info = f'''
<current_realtime_info>
- Datetime: {datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
</current_realtime_info>'''
        self.system['content'] += current_info
        
        messages = [self.system]
        messages.extend(self.messages)
        logger.info({"event": "Executing_LLM_call", "message_count": len(messages)})
        completion = self.get_llm_response(messages=messages, model_name=self.model)
        logger.debug({"event": "LLM_response", "response": completion.model_dump()})
        logger.info({"event": "Token_usage", "usage": completion.usage.model_dump()})
        return completion

    def rolling_memory(self):
        initial_token_count = self.total_messages_tokens
        while self.total_messages_tokens + self.max_reply_msg_tokens >= self.max_message_tokens:
            purged_message = self.messages.pop(0)
            purged_token_count = self.messages_token_counts.pop(0)

            self.purged_messages.append(purged_message)
            self.purged_messages_token_count.append(purged_token_count)

            self.total_messages_tokens -= purged_token_count
            logger.debug({"event": "Purged_message", "message": purged_message})

        if initial_token_count != self.total_messages_tokens:
            logger.info({
                "event": "Rolling_memory",
                "token_count_before": initial_token_count,
                "token_count_after": self.total_messages_tokens
            })
            logger.debug({"event": "Current_message_history", "messages": self.messages})
            logger.debug({"event": "Purged_message_history", "purged_messages": self.purged_messages})
        
        for purged_message in self.purged_messages:
            self.cur.execute("""
                UPDATE chat_messages
                SET is_purged = TRUE
                WHERE chat_id = %s AND role = %s AND content = %s
            """, (self.chat_id, purged_message['role'], purged_message['content']))
        self.conn.commit()

    def get_llm_response(self, messages: List[Dict[str, str]], model_name: str, extra_body: Optional[dict] = None) -> ChatCompletion | BaseModel:
        logger.debug({"event": "Sending_request_to_LLM", "api_provider": self.openai_client.base_url, "model": model_name, "messages": messages})
        if "openrouter" in self.openai_client.base_url:
            extra_body = extra_body if extra_body is not None else self.open_router_extra_body
        
        chat_completion = self.openai_client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=self.max_reply_msg_tokens,
            temperature=0.4,
            extra_body= extra_body
        )
        logger.debug({"event": "Received_response_from_LLM", "response": chat_completion.model_dump()})
        return chat_completion