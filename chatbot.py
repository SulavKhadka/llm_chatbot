from transformers import AutoTokenizer
import openai
from pydantic import BaseModel, ValidationError
from typing import List, Dict, Optional
import datetime

class ChatBot:
    def __init__(self, model, system=""):
        self.system = {"role": "system", "content": system}
        self.model = model
        self.tokenizer = AutoTokenizer.from_pretrained(model)
        self.max_message_tokens = 16384

        self.purged_messages = []
        self.purged_messages_token_count = []
        self.messages = []
        self.messages_token_counts = []
        self.total_messages_tokens = 0

        # if self.system:
        #     self.messages.append({"role": "system", "content": system})

        self.openai_client = openai.OpenAI(
            base_url = "http://localhost:8000/v1",
            api_key = "hi",
        )
    
    def __call__(self, message):
        self.messages.append({"role": "user", "content": message})
        self.rolling_memory()
        completion = self.execute()
        self.messages_token_counts.append(len(self.tokenizer.encode(str(self.messages[-1]))))
        
        self.messages.append({"role": "assistant", "content": completion.choices[0].message.content})
        self.messages_token_counts.append(len(self.tokenizer.encode(str(self.messages[-1]))))
        
        self.total_messages_tokens = sum(self.messages_token_counts)
        return completion.choices[0].message.content
    
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