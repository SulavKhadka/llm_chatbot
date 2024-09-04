import json
import datetime
from transformers import AutoTokenizer
import openai
from pydantic import BaseModel
from typing import List, Dict
import ast
import xml.etree.ElementTree as ET
from loguru import logger
import logfire
import sys
from uuid import uuid4

from llm_chatbot import function_tools, utils
from llm_chatbot.tools.python_sandbox import PythonSandbox
from secret_keys import TOGETHER_AI_TOKEN


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
    def __init__(self, model, chat_id, tokenizer_model="", system=""):
        global logger
        self.chat_id = chat_id
        logger = logger.bind(chat_id=self.chat_id)
        self.system = {"role": "system", "content": system}
        self.model = model
        self.tokenizer_model = tokenizer_model if tokenizer_model != "" else model
        self.tokenizer = AutoTokenizer.from_pretrained(self.tokenizer_model)
        self.max_message_tokens = 16384
        self.max_reply_msg_tokens = 1536
        self.functions = function_tools.functions

        self.purged_messages = []
        self.purged_messages_token_count = []
        self.messages = []
        self.messages_token_counts = []
        self.total_messages_tokens = 0

        self.openai_client = openai.OpenAI(
            api_key=TOGETHER_AI_TOKEN,
            base_url="https://api.together.xyz/v1"
        )

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
                if len(tool_calls) > 0:
                    logger.info({"event": "Extracted_tool_calls", "count": len(tool_calls)})
                    tool_call_responses = []
                    for tool_call in tool_calls:
                        tool_call_responses.append(self._execute_function_call(tool_call))
                    tool_response_str = '\n'.join(tool_call_responses)
                    self._add_message({"role": "tool", "content": f"<tool_call_response>\n{tool_response_str}\n</tool_call_response>"})
                    continue
                else:
                    self_recurse = False
                    response = f"{llm_thought}\n<self_response>\nno tool calls found, continuing on\n</self_response>"
            
            if parsed_response['response']['type'] == "USER_RESPONSE":
                self_recurse = False
                response = f"{llm_thought}\n<user_response>\n{parsed_response['response']['response']}\n</user_response>"

            if parsed_response['response']['type'] == "SELF_RESPONSE":
                self._add_message({"role": "assistant", "content": f"{llm_thought}\n<self_response>\n{parsed_response['response']['response']}\n</self_response>"})
                continue

            if parsed_response['response']['type'] == "PLAN":
                self._add_message({"role": "assistant", "content": f"{llm_thought}\n<plan>\n{parsed_response['response']['response']}\n</plan>"})
                continue

        logger.info({"event": "Assistant_response", "response": response})
        self._add_message({"role": "assistant", "content": response})
        return response

    def _add_message(self, message):
        self.messages.append(message)
        token_count = len(self.tokenizer.encode(str(self.messages[-1])))
        self.messages_token_counts.append(token_count)
        self.total_messages_tokens = sum(self.messages_token_counts)
        logger.debug({"event": "Added_message", "message": message, "token_count": token_count, "total_tokens": self.total_messages_tokens})

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
        for element in root.findall(".//user_response"):
            user_response += element.text
        if user_response != "":
            parsed_resp['response']['type'] = "USER_RESPONSE"
            parsed_resp['response']['response'] = user_response
            return parsed_resp 

        self_response = ""
        for element in root.findall(".//self_response"):
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
                tool_calls.append(json_data)
                logger.debug({"event": "Extracted_tool_call", "tool_call": json_data})

        logger.info({"event": "Extracted_tool_calls", "count": len(tool_calls)})
        return tool_calls

    def _execute_function_call(self, tool_call):
        logger.info({"event": "Executing_function_call", "tool_call": tool_call})
        function_name = tool_call.get("name", None)
        if function_name is not None and function_name in self.functions.keys():
            function_to_call = self.functions.get(function_name, None)
            function_args = tool_call.get("parameters", {})

            logger.debug({"event": "Function_call_details", "name": function_name, "args": function_args})
            try:
                function_response = function_to_call.call(*function_args.values())
            except Exception as e:
                function_response = f"Function call errored out. Error: {e}"
            results_dict = f'{{"name": "{function_name}", "content": {function_response}}}'
            logger.debug({"event": "Function_call_response", "response": results_dict})
            return results_dict
        else:
            logger.warning({"event": "Invalid_function_name", "name": function_name})
            return '{}'

    def execute(self):
        current_info = f'''
Current realtime info:
- Datetime: {datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
- Location: Seattle Home Server'''
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

    def get_llm_response(self, messages: List[Dict[str, str]], model_name: str) -> str | BaseModel:
        logger.debug({"event": "Sending_request_to_LLM", "model": model_name, "messages": messages})
        chat_completion = self.openai_client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=self.max_reply_msg_tokens,
            temperature=0.4
        )
        logger.debug({"event": "Received_response_from_LLM", "response": chat_completion.model_dump()})
        return chat_completion