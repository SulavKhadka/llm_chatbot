import logging
import logfire
import json
from transformers import AutoTokenizer
import openai
from pydantic import BaseModel, ValidationError
from typing import List, Dict, Optional
import datetime
import ast
import xml.etree.ElementTree as ET
from llm_chatbot import function_tools

logfire.configure(scrubbing=False) 

class ChatBot:
    def __init__(self, model, system=""):
        self.system = {"role": "system", "content": system}
        self.model = model
        self.tokenizer = AutoTokenizer.from_pretrained(model)
        self.max_message_tokens = 16384
        self.max_reply_msg_tokens = 1536
        self.functions = function_tools.functions

        self.purged_messages = []
        self.purged_messages_token_count = []
        self.messages = []
        self.messages_token_counts = []
        self.total_messages_tokens = 0

        self.openai_client = openai.OpenAI(
            base_url = "http://0.0.0.0:8000/v1",
            api_key = "hi",
        )

        # Set up logging
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        
        # Create file handler which logs even debug messages
        fh = logging.FileHandler('chatbot_full.log')
        fh.setLevel(logging.DEBUG)
        
        # Create console handler with a higher log level
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        
        # Create formatter and add it to the handlers
        file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(file_formatter)
        ch.setFormatter(console_formatter)
        
        # Add the handlers to the logger
        self.logger.addHandler(fh)
        self.logger.addHandler(ch)
        self.logger.addHandler(logfire.LogfireLoggingHandler())

        self.logger.info(f"ChatBot initialized with model: {model}")
        self.logger.debug(f"Initial system message: {self.system}")

    def __call__(self, message):
        self.logger.info(f"Received user message: {message}")
        self._add_message({"role": "user", "content": message})

        self_recurse = True
        while self_recurse:
            self.rolling_memory()
            completion = self.execute()

            tool_calls = self._extract_function_calls(completion.choices[0].message.content)
            if len(tool_calls) > 0:
                self.logger.info(f"Extracted {len(tool_calls)} tool calls")
                tool_call_responses = []
                for tool_call in tool_calls:
                    tool_call_responses.append(self._execute_function_call(tool_call))
                tool_response_str = '\n'.join(tool_call_responses)
                self._add_message({"role": "tool", "content": f"<tool_call_response>\n{tool_response_str}\n</tool_call_response>"})
                continue
            else:
                self_recurse = False

        response = completion.choices[0].message.content
        self.logger.info(f"Assistant response: {response}")
        self._add_message({"role": "assistant", "content": response})
        return response

    def _add_message(self, message):
        self.messages.append(message)
        token_count = len(self.tokenizer.encode(str(self.messages[-1])))
        self.messages_token_counts.append(token_count)
        self.total_messages_tokens = sum(self.messages_token_counts)
        self.logger.debug(f"Added message: {message}")
        self.logger.debug(f"Message token count: {token_count}, Total tokens: {self.total_messages_tokens}")

    def _extract_function_calls(self, response):
        self.logger.debug(f"Extracting function calls from response: {response}")
        if '<tool_call>' not in response:
            self.logger.debug("No tool calls found in response")
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
                        error_message = f"JSON parsing failed with both json.loads and ast.literal_eval:\n"\
                                        f"- JSON Decode Error: {json_err}\n"\
                                        f"- Fallback Syntax/Value Error: {eval_err}\n"\
                                        f"- Problematic JSON text: {json_text}"
                        self.logger.error(error_message)
                        continue
            except Exception as e:
                error_message = f"Cannot strip text: {e}"
                self.logger.error(error_message)

            if json_data is not None:
                tool_calls.append(json_data)
                self.logger.debug(f"Extracted tool call: {json_data}")

        self.logger.info(f"Extracted {len(tool_calls)} tool calls")
        return tool_calls

    def _execute_function_call(self, tool_call):
        self.logger.info(f"Executing function call: {tool_call}")
        function_name = tool_call.get("name", None)
        if function_name is not None:
            function_to_call = self.functions.get(function_name, None)
            function_args = tool_call.get("parameters", {})

            self.logger.debug(f"Function call details - Name: {function_name}, Args: {function_args}")
            function_response = function_to_call.call(*function_args.values())
            results_dict = f'{{"name": "{function_name}", "content": {function_response}}}'
            self.logger.debug(f"Function call response: {results_dict}")
            return results_dict
        else:
            self.logger.warning("Function call executed with no function name")
            return {}

    def execute(self):
        current_info = f'''
Current realtime info:
- Datetime: {datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
- Location: Seattle Home Server'''
        self.system['content'] += current_info
        messages = [self.system]
        messages.extend(self.messages)
        self.logger.info(f"Executing LLM call with {len(messages)} messages")
        completion = self.get_llm_response(messages=messages, model_name=self.model)
        self.logger.debug(f"LLM response: {completion.model_dump()}")
        self.logger.info(f"Token usage: {completion.usage}")
        return completion

    def rolling_memory(self):
        initial_token_count = self.total_messages_tokens
        while self.total_messages_tokens + self.max_reply_msg_tokens >= self.max_message_tokens:
            purged_message = self.messages.pop(0)
            purged_token_count = self.messages_token_counts.pop(0)

            self.purged_messages.append(purged_message)
            self.purged_messages_token_count.append(purged_token_count)

            self.total_messages_tokens -= purged_token_count
            self.logger.debug(f"Purged message: {purged_message}")

        if initial_token_count != self.total_messages_tokens:
            self.logger.info(f"Rolling memory: Purged messages. Token count before: {initial_token_count}, after: {self.total_messages_tokens}")
            self.logger.debug(f"Current message history: {self.messages}")
            self.logger.debug(f"Purged message history: {self.purged_messages}")

    def get_llm_response(self, messages: List[Dict[str, str]], model_name: str) -> str | BaseModel:
        self.logger.debug(f"Sending request to LLM. Model: {model_name}, Messages: {messages}")
        chat_completion = self.openai_client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=self.max_reply_msg_tokens,
            temperature=0.4
        )
        self.logger.debug(f"Received response from LLM: {chat_completion.model_dump()}")
        return chat_completion