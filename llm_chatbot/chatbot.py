from transformers import AutoTokenizer
import openai
from pydantic import BaseModel, ValidationError
from typing import List, Dict, Optional
import datetime
import json
import ast
import xml.etree.ElementTree as ET
from function_tools import functions

class ChatBot:
    def __init__(self, model, system=""):
        self.system = {"role": "system", "content": system}
        self.model = model
        self.tokenizer = AutoTokenizer.from_pretrained(model)
        self.max_message_tokens = 16384
        self.functions = functions

        self.purged_messages = []
        self.purged_messages_token_count = []
        self.messages = []
        self.messages_token_counts = []
        self.total_messages_tokens = 0

        self.openai_client = openai.OpenAI(
            base_url = "http://0.0.0.0:8000/v1",
            api_key = "hi",
        )
    
    def __call__(self, message):
        self._add_message({"role": "user", "content": message})

        self_recurse = True
        while self_recurse:
            self.rolling_memory()
            completion = self.execute()

            tool_calls = self._extract_function_calls(completion.choices[0].message.content)
            if len(tool_calls) > 0:
                tool_call_responses = []
                for tool_call in tool_calls:
                    tool_call_responses.append(self._execute_function_call(tool_call))
                tool_response_str = '\n'.join(tool_call_responses)
                self._add_message({"role": "tool", "content": f"<tool_call_response>\n{tool_response_str}\n</tool_call_response>"})
                continue
            else:
                self_recurse = False

        self._add_message({"role": "assistant", "content": completion.choices[0].message.content})
        return completion.choices[0].message.content
    
    def _add_message(self, message):
        self.messages.append(message)
        self.messages_token_counts.append(len(self.tokenizer.encode(str(self.messages[-1]))))
        self.total_messages_tokens = sum(self.messages_token_counts)
    
    def _extract_function_calls(self, response):
        xml_root_element = f"<root>{response}</root>"
        root = ET.fromstring(xml_root_element)

        tool_calls = []
        # extract JSON data
        for element in root.findall(".//tool_call"):
            json_data = None
            try:
                json_text = element.text.strip()

                try:
                    # Prioritize json.loads for better error handling
                    json_data = json.loads(json_text)
                except json.JSONDecodeError as json_err:
                    try:
                        # Fallback to ast.literal_eval if json.loads fails
                        json_data = ast.literal_eval(json_text)
                    except (SyntaxError, ValueError) as eval_err:
                        error_message = f"JSON parsing failed with both json.loads and ast.literal_eval:\n"\
                                        f"- JSON Decode Error: {json_err}\n"\
                                        f"- Fallback Syntax/Value Error: {eval_err}\n"\
                                        f"- Problematic JSON text: {json_text}"
                        print(error_message)
                        continue
            except Exception as e:
                error_message = f"Cannot strip text: {e}"
                print(error_message)

            if json_data is not None:
                tool_calls.append(json_data)
                validation_result = True
        return tool_calls

    def _execute_function_call(self, tool_call):
        print("tool_call:",tool_call)
        function_name = tool_call.get("name", None)
        if function_name is not None:
            function_to_call = self.functions.get(function_name, None)
            function_args = tool_call.get("parameters", {})

            print(f"Invoking function call {function_name} ...")
            function_response = function_to_call.call(*function_args.values())
            results_dict = f'{{"name": "{function_name}", "content": {function_response}}}'
            return results_dict
        else:
            return {}

    def execute(self):
        current_info = f'''
Current realtime info:
- Datetime: {datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
- Location: Seattle Home Server'''
        self.system['content'] += current_info
        messages = [self.system]
        messages.extend(self.messages)
        completion = self.get_llm_response(messages=messages, model_name=self.model)
        # Uncomment this to print out token usage each time, e.g.
        # {"completion_tokens": 86, "prompt_tokens": 26, "total_tokens": 112}
        return completion
    
    def rolling_memory(self):
        while self.total_messages_tokens >= self.max_message_tokens:
            # take the last turn(2 messages) out of self.messages and put it into self.purges_messages
            self.purged_messages.append(self.messages.pop(0))
            self.purged_messages_token_count.append(self.messages_token_counts.pop(0))

            self.purged_messages.append(self.messages.pop(0))
            self.purged_messages_token_count.append(self.messages_token_counts.pop(0))
            
            # print(f"prev total_toks: {self.total_messages_tokens}", end=" ")
            self.total_messages_tokens -= sum(self.purged_messages_token_count[-2:])
            # print(f"| after purge total_toks {self.total_messages_tokens}")

    def get_llm_response(self, messages: List[Dict[str, str]], model_name: str) -> str | BaseModel:
        chat_completion = self.openai_client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=1536,
            temperature=0.4
        )
        return chat_completion