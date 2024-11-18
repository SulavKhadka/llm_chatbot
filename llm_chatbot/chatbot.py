import asyncio
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
from uuid import uuid4
import requests
from outlines import models, generate
from outlines.models.openai import OpenAIConfig

from llm_chatbot import function_tools, utils
from llm_chatbot.rag_db import VectorSearch
from llm_chatbot.tools.python_sandbox import PythonSandbox
from llm_chatbot.chatbot_data_models import AssistantResponse, ResponseType, ToolParameter
from secret_keys import TOGETHER_AI_TOKEN, POSTGRES_DB_PASSWORD, OPENROUTER_API_KEY, USER_INFO
from prompts import CHAT_NOTES_PROMPT, CHAT_SESSION_NOTES_PROMPT, BOT_RESPONSE_FORMATTER_PROMPT, CONTEXT_FILTERED_TOOL_RESULT_PROMPT, RESPONSE_CFG_GRAMMAR

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
    def __init__(self, model, user_id, chat_id, tokenizer_model="", system="", db_config=None):

        self.max_message_tokens = 32768
        self.max_reply_msg_tokens = 4096
        self.max_recurse_depth = 6
        self.functions = function_tools.get_tools()
        # base_urls = [ "https://openrouter.ai/api/v1", "https://api.together.xyz/v1", "https://api.groq.com/openai/v1", "https://api.hyperbolic.xyz/v1"]
        self.openai_client = openai.AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )
        self.open_router_extra_body = None
        # {"provider": {
        #         "order": [
        #             "Together"
        #         ]
        #     }
        # }

        if db_config is None:
            db_config = {
                "dbname":"chatbot_db",
                "user":"chatbot_user",
                "password": POSTGRES_DB_PASSWORD,
                "host": "100.78.237.8",
                "port": "5432"
            }

        self.conversation_rag = VectorSearch(
            db_config=db_config,
            dimensions=256,
            use_binary=False,
            table_name=f"conversation_rag_{chat_id.replace("-", "_")}"
        )

        self.tool_rag = VectorSearch(
            db_config=db_config,
            dimensions= 512,
            use_binary=False,
            table_name=f"tool_rag_{chat_id.replace("-", "_")}"
        )
        
        global logger
        self.user_id = user_id
        self.chat_id = chat_id
        logger.bind(chat_id=self.chat_id)
        logger.configure(extra={"chat_id": self.chat_id})

        # Database connection
        self.initialize_db(**db_config)
        self.conn = psycopg2.connect(**db_config)
        self.cur = self.conn.cursor()

        # Load chat session metadata
        self.cur.execute("""
            SELECT model, tokenizer_model, system_message, user_id
            FROM chat_sessions 
            WHERE chat_id = %s
        """, (chat_id,))
        session_data = self.cur.fetchone()
        if not session_data:
            logger.debug("chat_id not found {chat_id}", chat_id=chat_id)
            logger.info("chat_id: {chat_id} not found. Creating new one under the provided chat_id", chat_id=chat_id)
            self._create_session(model, self.chat_id, tokenizer_model, system)
        else:
            self._load_session(self.chat_id, session_data)

        self.outlines_client = models.openai(self.openai_client, OpenAIConfig("self.model"))

    async def __call__(self, message, role="user", client_type="chat"):
        role = "user" if role is None else role
        message = f"[device_type: '{client_type}'] {message}"
        # TODO: adjust structure to take in if its a notification or alert from a tool and the notifier
        logger.info("Received_user_message {message}", message=message)
        self._add_message({"role": role, "content": message})
        try:
            response = await self._agent_loop()
            response = response['content']
        except Exception as e:
            logger.error("agent loop failed {error}", error=e)
            response = f"Agent failed to process data, Error: {e}"
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
                user_id UUID NOT NULL,
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

        # Create the Trigger Function
        cur.execute("""
            CREATE OR REPLACE FUNCTION update_chat_sessions_timestamp()
            RETURNS TRIGGER AS $$
            BEGIN
                -- Update only the `updated_at` column in the corresponding `chat_sessions` record
                UPDATE chat_sessions
                SET updated_at = CURRENT_TIMESTAMP
                WHERE chat_id = NEW.chat_id;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
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

        tables_to_trigger = ['chat_notes', 'chat_messages', 'function_calls']  # Add other tables as needed

        for table in tables_to_trigger:
            trigger_name = f"trigger_update_chat_sessions_timestamp_{table}"
            check_query = f"""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 
                        FROM pg_trigger 
                        WHERE tgname = '{trigger_name}'
                    ) THEN
                        CREATE TRIGGER {trigger_name}
                        AFTER INSERT ON {table}
                        FOR EACH ROW
                        EXECUTE FUNCTION update_chat_sessions_timestamp();
                    END IF;
                END $$;
            """
            cur.execute(check_query)

        # Commit changes and close connection
        conn.commit()
        cur.close()
        conn.close()

        logger.info("Database '{dbname}' and tables have been initialized successfully.", dbname=dbname)

    def _load_chat_messages_rag(self):
        """
        Loads chat messages from the database and bulk inserts them into the conversation_rag index.
        Messages are formatted as '[timestamp] role: content' for searchability.
        """
        # Query to get all messages for this chat session
        self.cur.execute("""
            SELECT chat_messages.*
            FROM chat_messages
            JOIN chat_sessions on chat_messages.chat_id = chat_sessions.chat_id
            WHERE chat_sessions.user_id = %s
            ORDER BY created_at, id
        """, (self.user_id,))
        
        # Format messages for RAG insertion, excluding system messages
        rag_entries = []
        for row in self.cur.fetchall():
            if row[2] != "system":  # Skip system messages
                timestamp = row[7].strftime("%Y-%m-%d %H:%M:%S")
                formatted_message = f"[{timestamp}] {row[2]}: {row[3]}"
                rag_entries.append((formatted_message, None))  # None for metadata as per VectorSearch.bulk_insert
        
        # Bulk insert into conversation_rag if we have entries
        if len(rag_entries) > 0:
            self.conversation_rag.bulk_insert(rag_entries)
            logger.info("Loaded {count} messages into conversation RAG", count=len(rag_entries))
        else:
            logger.debug("No messages to load into conversation RAG")

    def _load_tools_rag(self):
        tools = []
    
        for tool_name in self.functions.keys():
            if tool_name != 'overview':
                tool_fn = self.functions[tool_name]
                tools.append((f"{tool_name}: {tool_fn['schema']['function']['description']}\nparameters_schema: {tool_fn['schema']['function']['parameters']}\n\nTool Group Description: {tool_fn['tool_desc']}\n", None))
        self.tool_rag.bulk_insert(tools)
    
    async def _agent_loop(self):
        self_recurse = True
        recursion_counter = 0
        processing_tool_call = []
        while self_recurse and recursion_counter < self.max_recurse_depth:
            logger.debug("agent loop recursion depth: {count}", count=recursion_counter)
            
            transcript_snippet = [f"{m['role']}: {m['content']}" for m in self.messages[-3:] if m.get('role', 'system') != 'system']
            tool_suggestions = self.tool_rag.query("\n".join(transcript_snippet), top_k=15, min_p=0.2)
            logger.debug("tool_caller_tool_suggestions(top {top_k}) {message}", top_k=15, message=tool_suggestions)

            previous_chat_context = self.conversation_rag.query("\n".join(transcript_snippet), top_k=15, min_p=0.2)
            logger.debug("previous_chat_context {context}", context=previous_chat_context)
            
            self.rolling_memory()
            try:
                parsed_response: AssistantResponse = await self.execute(tool_suggestions[:5], previous_chat_context[:5])
            except Exception as e:
                logger.debug("failed parsing assistant response {error}", error=e)
                parsed_response: AssistantResponse = AssistantResponse.model_validate_json(json.dumps({
                        "thought": "looks like there was an error in my execution while processing user response",
                        "response": {
                            "type": ResponseType.INTERNAL_RESPONSE,
                            "content": f"internal error happened in agent loop. Error: {e}"
                        }
                    })
                )
            
            recursion_counter += 1
            llm_thought = f"<thought>{parsed_response.thought}</thought>"

            if parsed_response.response.type == ResponseType.TOOL_USE:
                tool_calls = parsed_response.response.content
                if isinstance(parsed_response.response.content, str):
                    tool_calls = json.loads(parsed_response.response.content)
                self._add_message({"role": "assistant", "content": f"{llm_thought}\n<tool_use>\n{[tooly.model_dump() for tooly in parsed_response.response.content]}\n</tool_use>"})
                
                if len(tool_calls) > 0:
                    logger.info("Extracted tool calls count: {count}", count=len(tool_calls))
                    tool_call_responses = []
                    for tool_call in tool_calls:
                        try:
                            fn_response = await self._execute_function_call(tool_call)
                            tool_call_responses.append(fn_response)
                        except Exception as e:
                            tool_call_responses.append(f"command: {tool_call} failed. Error: {e}")
                    response = {"role": "tool", "content": f"<tool_call_response>\n{tool_call_responses}\n</tool_call_response>"}
                    processing_tool_call.append(response)
                else:
                    response = f"{llm_thought}\n<internal_response>no tool calls found, continuing on</internal_response>"
            
            if parsed_response.response.type == ResponseType.USER_RESPONSE:
                self_recurse = False
                response = {"role": "assistant", "content": f"{llm_thought}\n<response_to_user>{parsed_response.response.content}</response_to_user>"}

                # tool response cleanup from possible inner cycles and tool calls
                # TODO: token counting is more complex now, somewhere else too, gotta comb the codebase
                # if len(processing_tool_call) > 0:
                #     for tool_call_resp in processing_tool_call:
                #         for i in range(len(self.messages)-1, 0, -1):
                #             if self.messages[i]['role'] == 'tool' and tool_call_resp['content'] == self.messages[i]['content']:
                #                 logger.debug("deleting tool_call_response instance message: {msg} to get tool response clear of the active conversation context", msg=self.messages[i])
                #                 self.messages.pop(i)
                #                 break
                processing_tool_call = []

            if parsed_response.response.type  == ResponseType.INTERNAL_RESPONSE:
                response = {"role": "assistant", "content": f"{llm_thought}\n<internal_response>{parsed_response.response.content}</internal_response>"}

            self._add_message(response)
            logger.info("Assistant_response {response}", response=response)

        return response

    def _create_session(self, model, chat_id, tokenizer_model, system):
        self.chat_id = chat_id
        self.system = {"role": "system", "content": system}
        self.model = model
        self.tokenizer_model = tokenizer_model if tokenizer_model != "" else model
        self.tokenizer = AutoTokenizer.from_pretrained(self.tokenizer_model)
        self.purged_messages = []
        self.purged_messages_token_count = []
        self.messages = []
        self.messages_token_counts = []
        self.total_messages_tokens = 0

        self.cur.execute("""
            INSERT INTO chat_sessions (chat_id, user_id, model, tokenizer_model, system_message)
            VALUES (%s, %s, %s, %s, %s)
        """, (self.chat_id, self.user_id, self.model, self.tokenizer_model, self.system["content"]))
        self.conn.commit()

        self._load_tools_rag()
        self._load_chat_messages_rag()
        
        # Add initial system message
        self._add_message(self.system)
        logger.info({
            "event": "ChatBot_initialized",
            "model": self.model,
            "session_type": "new",
            "chat_id": str(self.chat_id)
        })
        logger.debug("Initial_system_message {sys_msg}", sys_msg=self.system)
    
    def _load_session(self, chat_id: str, session_data: List):
        """
        Reconstructs the complete chat session state from the database using the chat_id.
        Must be called right after ChatBot.__init__() to load an existing session.
        
        Args:
            chat_id (str): UUID of the chat session to load
        """

        # Reset any existing state
        self.purged_messages = []
        self.purged_messages_token_count = []
        self.messages = []
        self.messages_token_counts = []
        self.total_messages_tokens = 0
        
        # Update instance variables with session data
        self.model = session_data[0]
        self.tokenizer_model = session_data[1]
        self.system = {"role": "system", "content": session_data[2]}
        
        # Reinitialize tokenizer with correct model
        if self.tokenizer_model:
            self.tokenizer = AutoTokenizer.from_pretrained(self.tokenizer_model)
        
        # Load all messages in chronological order
        self.cur.execute("""
            SELECT role, content, token_count, is_purged, created_at 
            FROM chat_messages 
            WHERE chat_id = %s 
            ORDER BY created_at, id
        """, (chat_id,))
        messages = self.cur.fetchall()
        
        # Reconstruct messages and token counts
        for role, content, token_count, is_purged, _ in messages:
            message = {"role": role, "content": content}
            
            if is_purged:
                self.purged_messages.append(message)
                self.purged_messages_token_count.append(token_count)
            else:
                self.messages.append(message)
                self.messages_token_counts.append(token_count)
                self.total_messages_tokens += token_count
        
        # Load latest chat notes
        self.cur.execute("""
            SELECT notes, chat_summary, metadata 
            FROM chat_notes 
            WHERE chat_id = %s 
            ORDER BY id DESC 
            LIMIT 1
        """, (chat_id,))
        notes_data = self.cur.fetchone()
        
        # No need to store notes in instance variables as they're only used 
        # when explicitly requested via _get_chat_notes() or _get_session_notes()
        
        logger.info({
            "event": "Session_loaded",
            "chat_id": chat_id,
            "active_messages": len(self.messages),
            "purged_messages": len(self.purged_messages),
            "total_tokens": self.total_messages_tokens
        })
        logger.debug("Session_state {active_messages} {purged_messages}",
            active_messages=self.messages,
            purged_messages=self.purged_messages
        )
        logger.info("ChatBot_initialized with {model}", model=self.model)

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
        logger.debug("Added_message: {message}, token_count {token_count}, total_tokens {total_tokens} self.total_messages_tokens", message=message, token_count=token_count, total_tokens=self.total_messages_tokens)
        return message_id

    async def _get_bot_response_json(self, response_text: str):
        logger.debug("response_text_to_json: {response_text}", response_text=response_text)
        response_formatter_messages = [
            {"role": "system", "content": BOT_RESPONSE_FORMATTER_PROMPT},
            {"role": "user", "content": response_text}
        ]
        response = await self.get_llm_response(
            messages=response_formatter_messages,
            model_name="google/gemini-flash-1.5-8b",
            extra_body={
                "response_format": {
                    "type": "json_object",
                }
            },
        )
        logger.debug("response_text_to_json {reformatted_text}", reformatted_text=response.choices[0].message.content)
        ass_resp = AssistantResponse.model_validate_json(response.choices[0].message.content)
        return ass_resp

    async def _parse_results(self, response_text: str):
        assistant_response = await self._get_bot_response_json(response_text)
        logger.debug("assistant_response_json {response_json}", response_json=assistant_response.model_dump())
        return assistant_response

    def _extract_function_calls(self, xml_response):
        logger.debug("Extracting_function_calls {response}", response=xml_response)

        tool_calls = []
        for element in xml_response.findall(".//tool_use"):
            json_data = None
            try:
                json_text = element.text.strip()
                try:
                    json_data = ast.literal_eval(json_text)
                except json.JSONDecodeError as json_err:
                    try:
                        json_data = ast.literal_eval(json_text)
                    except (SyntaxError, ValueError) as eval_err:
                        logger.error("JSON_parsing_failed {json_decode_error} {fallback_error} {problematic_json_text}", json_decode_error=str(json_err), fallback_error=str(eval_err), problematic_json_text=json_text)
                        continue
            except Exception as e:
                logger.error("Cannot_strip_text {error}", error=str(e))

            if json_data is not None:
                if isinstance(json_data, list):
                    tool_calls.extend(json_data)
                else:
                    tool_calls.append(json_data)
                logger.debug("Extracted_tool_call {tool_call}", tool_call=json_data)

        logger.info("Extracted_tool_calls {count}", count=len(tool_calls))
        return tool_calls

    async def _get_context_filtered_tool_results(self, tool_call: ToolParameter, tool_result):
        context_messages = [m for m in self.messages[-2:] if m.get('role', 'system') != 'system']
        logger.debug("context_filtered_tool_result {tool_call_result} {conversation_context}", tool_call_result=tool_result, conversation_context=context_messages)
        response_formatter_messages = [
            {"role": "system", "content": CONTEXT_FILTERED_TOOL_RESULT_PROMPT},
            {"role": "user", "content": f"<conversation_context>{context_messages}</conversation_context>\n<tool_result>{tool_result}</tool_result>"}
        ]
        response = await self.get_llm_response(
            messages=response_formatter_messages,
            model_name="google/gemini-flash-1.5-8b",
            extra_body={"response_format": {"type": "json_object"}}
        )
        logger.debug("context_filtered_tool_result {reformatted_tool_result}", reformatted_tool_result=response.choices[0].message.content)

        return response.choices[0].message.content.replace("\n", " ").replace("\t", "")

    async def _execute_function_call(self, tool_call: ToolParameter):
        logger.info("Executing_function_call {tool_call}", tool_call=tool_call)
        if tool_call.name is not None and tool_call.name in self.functions.keys():
            function_to_call = self.functions.get(tool_call.name, {}).get('function', None)

            logger.debug("Function_call_details {name} {args}", name=tool_call.name, args=tool_call.parameters)
            try:
                function_response = function_to_call.func(**tool_call.parameters)
                logger.info("filtering function call response {name} {result}", name=tool_call.name, result=function_response)
                function_response = await self._get_context_filtered_tool_results(tool_call, function_response)
                logger.debug("filtered function call response {name} {result}", name=tool_call.name, result=function_response)
            except Exception as e:
                function_response = f"Function call errored out. Error: {e}"
            results_dict = {"name": tool_call.name, "content": function_response}
            logger.debug("Function_call_response {response}", response=results_dict)
            
            # Log function call in database
            self.cur.execute("""
                INSERT INTO function_calls (chat_id, function_name, parameters, response)
                VALUES (%s, %s, %s, %s)
            """, (self.chat_id, tool_call.name, Json(tool_call.parameters), str(function_response)))
            self.conn.commit()
            return results_dict
        else:
            logger.warning("Invalid_function_name {name}", name=tool_call.name)
            return f'{{"name": "{tool_call.name}", "content": Invalid function name. Either None or not in the list of supported functions.}}'

    async def _get_chat_notes(self, message_id: str):

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
        completion = await self.get_llm_response(messages, model_name=self.model)

        logger.debug("parsing_chat_notes_llm_response {response_text}", response_text=completion)
        response_text = utils.sanitize_inner_content(completion.choices[0].message.content)
        xml_root_element = f"<root>{response_text}</root>"
        
        try:
            root = ET.fromstring(xml_root_element)
        except ET.ParseError as e:
            logger.error("failed_chat_summary_parsing {error}", error=e)
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

    async def _get_session_notes(self, message_id: str):
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
        completion = await self.get_llm_response(messages, model_name=self.model)

        logger.debug("parsing_session_end_notes_llm_response {response_text}", response_text=completion)
        response_text = utils.sanitize_inner_content(completion.choices[0].message.content)
        xml_root_element = f"<root>{response_text}</root>"
        
        try:
            root = ET.fromstring(xml_root_element)
        except ET.ParseError as e:
            logger.error("failed_session_final_notes_parsing {error}", e)
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
        # self._get_session_notes(f"{self.chat_id}_final_session_notes")
        # Close database connection when the object is destroyed
        self.cur.close()
        self.conn.close()

    async def execute(self, tool_suggestions, previous_chat_context, retries: int = 3):
        # prefs = "\t-".join([i for i in USER_INFO['preferences']])
        
        while retries > 0:
            current_info = f'''
## Current Realtime Info
Datetime: {datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")}

## Available Tools Overview
{self.functions.get('overview', 'Overview not found.')}

## Tool Suggestions
{tool_suggestions}

## User Information
Name: {USER_INFO['username']}
Home Address: {USER_INFO['home_address']}
Preferences:
    - Measurement unit: {USER_INFO['units']}
    - {"\n\t- ".join([i for i in USER_INFO['preferences']])}

## Previous Chat Context Snippets
{previous_chat_context}

## End
    '''
            regex = re.compile(r'## Current Realtime Info.*?## End\n', re.DOTALL)
            # self.system['content'] += current_info
            if regex.search(self.system['content']):
                self.system['content'] = regex.sub(current_info, self.system['content'])
            else:
                self.system['content'] = self.system['content'] + '\n' + current_info
        
            
            messages = [self.system]
            messages.extend(self.messages)
            logger.info("Executing_LLM_call {message_count}", message_count=len(messages))
            completion = await self.get_llm_response(messages=messages, model_name=self.model)
            logger.debug("LLM_response {response}", response=completion.model_dump())
            logger.info("Token_usage {usage}", usage=completion.usage.model_dump())

            try:
                parsed_response = await self._parse_results(completion.choices[0].message.content)
                return parsed_response
            except Exception as e:
                logger.error("bot response failed {error}", error=e)
            retries -= 1
        
        return AssistantResponse.model_validate_json('''{
            "thought": "[NOT AVAILBALE. THIS IS AN INJECTED MESSAGE BECAUSE OF INTERNAL LLM CALLING FAILURE]",
            "response": {
                "type": ResponseType.INTERNAL_RESPONSE,
                "content": f"internal error happened trying to call llm. Error: {e}"
            }'''
        )

    def rolling_memory(self):
        initial_token_count = self.total_messages_tokens
        while self.total_messages_tokens + self.max_reply_msg_tokens >= self.max_message_tokens:
            purged_message = self.messages.pop(0)
            purged_token_count = self.messages_token_counts.pop(0)

            self.purged_messages.append(purged_message)
            self.purged_messages_token_count.append(purged_token_count)

            self.total_messages_tokens -= purged_token_count
            logger.debug("Purged_message {message}", message=purged_message)

        if initial_token_count != self.total_messages_tokens:
            logger.info({
                "event": "Rolling_memory",
                "token_count_before": initial_token_count,
                "token_count_after": self.total_messages_tokens
            })
            logger.debug("Current_message_history {messages}", messages=self.messages)
            logger.debug("Purged_message_history {purged_messages}", messages=self.purged_messages)
        try:
            for purged_message in self.purged_messages:
                self.cur.execute("""
                    UPDATE chat_messages
                    SET is_purged = TRUE
                    WHERE chat_id = %s AND role = %s AND content = %s
                """, (self.chat_id, purged_message['role'], purged_message['content']))
            self.conn.commit()
        except Exception as e:
            logger.error("db update exception {error}", error=e)
            raise

    async def get_llm_response(self, messages: List[Dict[str, str]], model_name: str, extra_body: Optional[dict] = None) -> ChatCompletion | BaseModel:
        logger.debug("Sending_request_to_LLM {api_provider} {model} {messages}", api_provider=self.openai_client.base_url, model=model_name, messages=messages)
        if "openrouter" in self.openai_client.base_url.host:
            extra_body = extra_body if extra_body is not None else self.open_router_extra_body
        try:
            chat_completion = await self.openai_client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=self.max_reply_msg_tokens,
                temperature=0.1,
                extra_body= extra_body,
            )
        except Exception as e:
            if e['code'] == 'model_not_available':
                logger.error("model not found as requested: {model_name}", model_name=model_name)
                raise(e)
            else:
                logger.error("failed to get llm response. Error: {ex}", ex=e)
                raise(e)
        logger.debug("Received_response_from_LLM {completion}", completion=chat_completion.model_dump())
        return chat_completion