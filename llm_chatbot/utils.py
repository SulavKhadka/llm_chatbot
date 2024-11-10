from typing import List, Union
from prompts import RESPONSE_CFG_GRAMMAR
from secret_keys import TOGETHER_AI_TOKEN, OPENROUTER_API_KEY
import openai
import xml.etree.ElementTree as ET
import re
import xml.sax.saxutils as saxutils
import json, ast
import sys
import numpy as np
import pandas as pd
from collections.abc import Iterable
from numbers import Number


def get_size(obj, seen=None):
    """
    Recursively calculate the approximate memory size of a Python object in bytes.
    
    Parameters:
    -----------
    obj : any
        The object to measure
    seen : set, optional
        Set of objects already seen during recursion
        
    Returns:
    --------
    int
        Approximate size in bytes
    """
    # Handle already seen objects to prevent infinite recursion
    if seen is None:
        seen = set()
    
    # Get object's id
    obj_id = id(obj)
    
    # If we've already seen this object, don't count it again
    if obj_id in seen:
        return 0
    
    # Mark this object as seen
    seen.add(obj_id)
    
    # Base size of the object
    size = sys.getsizeof(obj)
    
    # Handle special cases
    if isinstance(obj, (str, bytes, Number, bool, type(None))):
        return size
    
    # Handle NumPy arrays
    elif isinstance(obj, np.ndarray):
        return obj.nbytes + size
    
    # Handle Pandas DataFrame
    elif isinstance(obj, pd.DataFrame):
        return obj.memory_usage(deep=True).sum() + size
    
    # Handle Pandas Series
    elif isinstance(obj, pd.Series):
        return obj.memory_usage(deep=True) + size
    
    # Handle iterables
    elif isinstance(obj, Iterable):
        try:
            # Add sizes of all contained objects
            for item in obj:
                size += get_size(item, seen)
        except TypeError:
            pass
            
    # Handle dictionaries
    elif hasattr(obj, '__dict__'):
        size += get_size(obj.__dict__, seen)
        
    return size


def unsanitize_content(sanitized_output):
    """
    Unescape the sanitized content, converting &lt; and &gt; back to < and >, etc.
    """
    return saxutils.unescape(sanitized_output)

def sanitize_inner_content(llm_output):
    """
    Use regular expressions to sanitize content inside specific XML tags.
    """
    def escape_content(match):
        tag = match.group(1)
        content = match.group(2)
        
        # Escape only the inner content of the tags
        escaped_content = saxutils.escape(content)
        return f"<{tag}>{escaped_content}</{tag}>"

    # Escape content inside <tool_use> and <response_to_user>
    llm_output = re.sub(r'<(tool_call_response|tool_use|response_to_user|self_response|thought)>(.*?)</\1>', escape_content, llm_output, flags=re.DOTALL)
    llm_output = llm_output.replace(">\n", ">").replace("\n<", "<").strip()
    return llm_output

def ensure_llm_response_format(llm_response_text, tools=None):
    openai_client = openai.OpenAI(
            api_key='hi',
            base_url="http://localhost:8555/v1"
        )
    
    messages = [
        {
            "role": "system",
            "content": """You are an expert at validating and correcting the XML structure of responses from another LLM. Your task is to ensure that the responses conform to the guidelines specified in the original system prompt. Focus solely on the XML structure and tag usage, not on the content or wording of the response. You'll be given the LLM response to analyze inside of <llm_response_content></llm_response_content> by the user.

## Guidelines for checking response content:

1. Every response must be a valid parseable XML with no exceptions.
2. The response must always begin with a <thought></thought> tag.
3. After the thought tag, there must be exactly one of the following response types:
   - <tool_use></tool_use>
     - Used when the assistant needs to access external data or functions.
     - Must contain a list of JSON objects with "name" and "parameters" keys.
     - Only functions specified in the original <tools></tools> section should be used.
   - <self_response></self_response>
     - Used when the assistant needs another cycle to process something.
     - This is an internal message and will not be visible to the user.
   - <response_to_user></response_to_user>
     - Used for direct replies to the user when no further processing is needed.
     - This is the only tag whose content the user will see.
4. Ensure all XML tags are properly opened and closed.
5. Check that the XML is well-formed and can be parsed.
6. Verify that only the tools specified in the original <tools></tools> section are used in <tool_use> tags.
7. For <tool_use> tags, ensure the content is a valid list of JSON objects with "name" and "parameters" keys.

If the response follows these guidelines and has valid, parseable XML, reply only with "no correction needed" and no other text before or after.

If the response does not conform to these guidelines or contains invalid XML:
1. Correct the XML structure while preserving the original content as is besides the XML tags
2. When correcting, keep the original wording intact; only edit the tags, move existing content to the correct tags, or adjust the structure to comply with the guidelines to create valid XML.
3. If a response is missing a required tag (i.e. <thought>), add it with placeholder content like "[Missing thought process]".
4. If multiple response types are present, keep the most appropriate one based on the content and remove the others.

## Examples:

1. Correct response (no correction needed): This is the most common result/response. If the XML is good reply like this strictly
Input:
<llm_response_content>
<thought>The user has asked about the weather in New York. I need to use the weather API to get this information.</thought>
<tool_use>
[{"name": "get_current_weather", "parameters": {"location": "New York, NY", "unit": "Fahrenheit"}}]
</tool_use>
</llm_response_content>

Output: no correction needed

2. Multiple response types (can only have one, keep most appropriate):
Input:
<llm_response_content>
<thought>The user asked about quantum computing. I'll provide a brief explanation.</thought>
<self_response>Researching quantum computing basics.</self_response>
<response_to_user>Quantum computing is a form of computation that harnesses the principles of quantum mechanics to process information.</response_to_user>
</llm_response_content>

Output:
<thought>The user asked about quantum computing. I'll provide a brief explanation.</thought>
<response_to_user>Quantum computing is a form of computation that harnesses the principles of quantum mechanics to process information.</response_to_user>

3. Missing closing tag:
Input:
<llm_response_content>
<thought>
I'll use the `run_python_code` tool to execute the provided Python code.
</thought>
<tool_use>
[{"name": "run_python_code","parameters": {"code": "import random\n\ndef generate_and_average():\n    numbers = [random.randint(1, 100) for _ in range(5)]\n    average = sum(numbers) / len(numbers)\n    return numbers, average\n\n# Run the function 5 times\nresults = [generate_and_average() for _ in range(5)]\nfor i, (numbers, average) in enumerate(results):\n    print(f'Run {i + 1}: Numbers = {numbers}, Average = {average}')"}}]
</llm_response_content>

Output:
<thought>
I'll use the `run_python_code` tool to execute the provided Python code.
</thought>
<tool_use>
[{"name": "run_python_code","parameters": {"code": "import random\n\ndef generate_and_average():\n    numbers = [random.randint(1, 100) for _ in range(5)]\n    average = sum(numbers) / len(numbers)\n    return numbers, average\n\n# Run the function 5 times\nresults = [generate_and_average() for _ in range(5)]\nfor i, (numbers, average) in enumerate(results):\n    print(f'Run {i + 1}: Numbers = {numbers}, Average = {average}')"}}]
</tool_use>

4. Incorrect nesting of tags plus tool call JSON problems:
Input:
<llm_response_content>
<thought>The user wants to know about famous landmarks in Paris.</thought>
<response_to_user>Here are some famous landmarks in Paris:
<tool_use>
["name": "get_landmarks", "parameters": {"city": "Paris"}}]
</tool_use>
</response_to_user>
</llm_response_content>

Output:
<thought>The user wants to know about famous landmarks in Paris.</thought>
<tool_use>
[{"name": "get_landmarks", "parameters": {"city": "Paris"}}]
</tool_use>

5. Mixing content outside of tags:
Input:
<llm_response_content>
Hello! <thought>The user greeted me. I should respond politely.</thought>
<response_to_user>Hi there! How can I assist you today?</response_to_user>
</llm_response_content>

Output:
<thought>The user greeted me. I should respond politely.</thought>
<response_to_user>Hello! Hi there! How can I assist you today?</response_to_user>
""" + f"""\nFor the input you are about to recieve here is the list of tools available to the agent that generated the llm_response_text.
<tools>
{tools}
</tools>

Remember, your task is to ensure every payload has proper XML structure and tag usage, correcting structure as needed while always perfectly copying the content of the responses. No action needed when XML is valid, evaluate carefully using the examples given above as a guide. Always keep the original content, intent, and wording of the assistant's response while correcting only the XML structure. A frequent correction is missing XML tag pairs opening or closing, just a tip."""
        },
        {
            "role": "user",
            "content": f"""<llm_response_content>{llm_response_text}</llm_response_content>"""
        }
    ]

    try:
        chat_completion = openai_client.chat.completions.create(
            model="Qwen/Qwen2.5-3B-Instruct",
            messages=messages,
            max_tokens=1536,
            temperature=0.4,
            frequency_penalty=0.4,
            extra_body= {
                "min_p": 0.2,
                "top_k": 35,
                "guided_grammar": RESPONSE_CFG_GRAMMAR
            }
        )
    except Exception as e:
        if e['code'] == 'model_not_available':
            pass
        else:
            raise
    print({"event": "Received_response_from_LLM", "response": chat_completion.model_dump()})



    # sanitized_llm_output = sanitize_inner_content(chat_completion.choices[0].message.content)
    # xml_root_element = f"""<root>{sanitized_llm_output}</root>"""
    # try:
    #     root = ET.fromstring(xml_root_element)
    # except ET.ParseError as e:
    #     return ET.fromstring("<root></root>")

    # if root.find(".//thought") is not None and (
    #     root.find(".//self_response") is not None
    #     or root.find(".//response_to_user") is not None
    #     or root.find(".//tool_use") is not None
    # ):
    #     return root
    # else:
    #     return ET.fromstring(f"<root>{llm_response_text}</root>")
    
def tool_caller(tools: List, transcript: List[str]):
    openai_client = openai.OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1"
    )
    
    prompt = f'''<|begin_of_text|><|start_header_id|>system<|end_header_id|>

## Task
Given the following list of tools and a transcript of the conversation so far, your task is to determine if there are any relevant tool calls for the current conversation turn. Return an empty list when no action is needed or the query cant be fulfilled by the available tools. There is almost always more than one way to do something and often a clever combination of different tools is needed to accomplish the goal. Your job is to present all the tools that could be relevant for use by the assistant in the current turn of conversation. You must provide as many relevant tool options as possible to the assistant.

## Available Tool List:
{tools}

### Output Response JSON Structure Requirements
- All responses must be well-formed JSON
- Carefully every step about being compliant with the JSON spec so its parseable
- Tool Call format given below for the list of relevant tool calls

### Tool Call Format
```json
[{{
    "name": "function_name",
    "description": "very brief but detailed description from the docstring of the tool.
    "parameters": {{
        "param1": valueType,
        "param2": valueType
    }}
}}]
```

### Tool Usage Guidelines
- Only use explicitly provided tools
- Always return an empty tool call list if no tool is even loosely relevant for the conversation turn
- Think about all the tools and the ways their outputs can be combined, fed into, and analyzed to accomplish the goal at hand
- Include all required parameters for every tool suggestion
- think step by step about all combinations and possibilites(both obvious and creative) of tools that can be used.<|eot_id|><|start_header_id|>user<|end_header_id|>## Current Transcript:
{transcript}<|eot_id|><|start_header_id|>assistant<|end_header_id|>[{{'''

    chat_completion = openai_client.completions.create(
        model="meta-llama/llama-3.1-70b-instruct",
        prompt=prompt,
        max_tokens=4096,
        temperature=0.1
    )
    print(chat_completion)
    response_json = "[{" + chat_completion.choices[0].text

    tool_calls = []
    try:
        tool_calls = json.loads(response_json)
    except json.JSONDecodeError as json_err:
        try:
            tool_calls = ast.literal_eval(response_json)
        except (SyntaxError, ValueError) as eval_err:
            print({"event": "JSON_parsing_failed", "json_decode_error": str(json_err), "fallback_error": str(eval_err), "problematic_json_text": response_json})
    
    print({"event": "Extracted_tool_calls", "count": len(tool_calls)})
    return tool_calls
    # sanitized_response_text = sanitize_inner_content("<thought>" + chat_completion.choices[0].text)
    # xml_root_element = f"""<root>{sanitized_response_text}</root>"""
    
    # try:
    #     root = ET.fromstring(xml_root_element)
    # except ET.ParseError:
    #     root = ensure_llm_response_format(chat_completion.choices[0].text)

    # tool_calls = []
    # for element in root.findall(".//tool_use"):
    #     json_data = None
    #     try:
    #         json_text = element.text.strip()
    #         try:
    #             json_data = json.loads(json_text)
    #         except json.JSONDecodeError as json_err:
    #             try:
    #                 json_data = ast.literal_eval(json_text)
    #             except (SyntaxError, ValueError) as eval_err:
    #                 # logger.error({"event": "JSON_parsing_failed", "json_decode_error": str(json_err), "fallback_error": str(eval_err), "problematic_json_text": json_text})
    #                 continue
    #     except Exception as e:
    #         # logger.error({"event": "Cannot_strip_text", "error": str(e)})
    #         pass

    #     if json_data is not None:
    #         if isinstance(json_data, list):
    #             tool_calls.extend(json_data)
    #         else:
    #             tool_calls.append(json_data)
    #         print({"event": "Extracted_tool_call", "tool_call": json_data})

    # print({"event": "Extracted_tool_calls", "count": len(tool_calls)})
    # return tool_calls