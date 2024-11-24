from typing import List, Union
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

def split_markdown_text(text):
    """
    Split markdown text into clean sentences by:
    1. Replacing code blocks with placeholders
    2. Stripping markdown syntax
    3. Converting lists to plain text
    4. Splitting by sentences
    
    Args:
        text (str): Input markdown text
    Returns:
        list: Clean sentences
    """
    # Replace code blocks
    def replace_code_block(match):
        language = match.group(1) or "unknown"
        return f"Refer to {language} code in chat"
    
    # Handle triple backtick code blocks
    text = re.sub(r'```(\w+)?\n[\s\S]*?```', replace_code_block, text)
    
    # Handle inline code
    text = re.sub(r'`[^`]+`', 'Refer to code in chat', text)
    
    # Strip markdown syntax
    # Headers
    text = re.sub(r'#{1,6}\s+', '', text)
    # Bold and italic
    text = re.sub(r'\*\*.*?\*\*', lambda m: m.group(0).strip('*'), text)
    text = re.sub(r'\*.*?\*', lambda m: m.group(0).strip('*'), text)
    text = re.sub(r'__.*?__', lambda m: m.group(0).strip('_'), text)
    text = re.sub(r'_.*?_', lambda m: m.group(0).strip('_'), text)
    
    # Convert lists to plain text
    # Unordered lists
    text = re.sub(r'^\s*[-*+]\s+', '\n', text, flags=re.MULTILINE)
    # Ordered lists
    text = re.sub(r'^\s*\d+\.\s+', '\n', text, flags=re.MULTILINE)
    
    # Clean up extra whitespace and newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    
    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    # Clean up sentences
    sentences = [s.strip() for s in sentences if s.strip()]
    
    return sentences

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

def format_function_schema(schema):
    """
    Converts a function call schema into readable declaration and call syntax.
    
    Args:
        schema (dict): Function schema dictionary containing name, description, and parameters
        
    Returns:
        tuple: (declaration_syntax, call_syntax)
    """
    try:
        # Extract basic function info
        if not isinstance(schema, dict) or 'function' not in schema:
            raise ValueError("Invalid schema format")
            
        func_info = schema['function']
        func_name = func_info.get('name')
        params_info = func_info.get('parameters', {})
        
        if not func_name:
            raise ValueError("Function name not found in schema")
            
        # Get properties and required fields
        properties = params_info.get('properties', {})
        required_params = params_info.get('required', [])
        
        # Process parameters
        param_list = []
        
        # Build declaration syntax
        declaration_params = []
        for param_name, param_info in properties.items():
            # Get parameter type
            param_type = param_info.get('type', 'Any')
            param_type = param_type.capitalize()  # Convert 'string' to 'String' etc.
            
            # Check if parameter has a default value
            has_default = 'default' in param_info
            default_value = param_info.get('default')
            
            # Format the parameter string
            param_str = f"{param_name}: {param_type}"
            if has_default:
                param_str += f" = {repr(default_value)}"
            elif param_name not in required_params:
                param_str += " = None"
                
            declaration_params.append(param_str)
            
        declaration = f"def {func_name}({', '.join(declaration_params)})"
        
        # Build call syntax
        call_params = []
        for param_name, param_info in properties.items():
            param_type = param_info.get('type', 'any')
            if 'default' in param_info:
                call_params.append(f"{param_name}={repr(param_info['default'])}")
            else:
                # Use appropriate placeholder based on type
                type_placeholders = {
                    'string': '"example"',
                    'integer': '0',
                    'number': '0.0',
                    'boolean': 'False',
                    'array': '[]',
                    'object': '{}',
                }
                placeholder = type_placeholders.get(param_type.lower(), 'None')
                call_params.append(f"{param_name}={placeholder}")
                
        call = f"{func_name}({', '.join(call_params)})"
        
        return declaration, call
        
    except Exception as e:
        raise ValueError(f"Error processing schema: {str(e)}")

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