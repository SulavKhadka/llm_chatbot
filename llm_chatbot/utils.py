from typing import List, Union
from secret_keys import TOGETHER_AI_TOKEN
import openai
import xml.etree.ElementTree as ET
import re
import xml.sax.saxutils as saxutils

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

    # Escape content inside <tool_call> and <user_response>
    llm_output = re.sub(r'<(tool_call_response|tool_call|user_response|self_response|thought)>(.*?)</\1>', escape_content, llm_output, flags=re.DOTALL)

    return llm_output

def ensure_llm_response_format(llm_response_text):
    openai_client = openai.OpenAI(
            api_key=TOGETHER_AI_TOKEN,
            base_url="https://api.together.xyz/v1"
        )
    
    messages = [
        {
            "role": "system",
            "content": """You are a helper bot designed to validate and correct the XML structure of responses from another AI assistant. Your task is to ensure that the responses conform to the guidelines specified in the original system prompt. Focus solely on the XML structure and tag usage, not on the content or wording of the response. You'll be given the LLM response to analyze inside of <llm_response_content></llm_response_content> by the user.

## Guidelines for checking responses:

1. Every response must be entirely enclosed in XML tags.
2. The response must always begin with a <thought></thought> tag.
   - This tag is for the assistant's private analysis of the input and decision-making process.
3. After the thought tag, there must be exactly one of the following response types:
   - <tool_call></tool_call>
     - Used when the assistant needs to access external data or functions.
     - Must contain a JSON object with "name" and "parameters" keys.
     - Only tools specified in the original <tools></tools> section should be used.
   - <plan></plan>
     - Used for complex queries requiring multiple steps.
     - Should contain numbered steps for executing the plan.
   - <self_response></self_response>
     - Used when the assistant needs another cycle to process something, typically when executing a plan step-by-step.
     - This is an internal message and should not be visible to the user.
   - <user_response></user_response>
     - Used for direct replies to the user when no further processing is needed.
     - This is the only tag whose content the user will see.
4. Ensure all XML tags are properly closed.
5. Check that the XML is well-formed and can be easily parsed.
6. Verify that only the tools specified in the original <tools></tools> section are used in <tool_call> tags.
7. For <tool_call> tags, ensure the content is a valid JSON object with "name" and "parameters" keys.
8. For <plan> tags, verify that the steps are clearly defined and numbered.

If the response follows these guidelines and has valid, parseable XML, reply only with "no correction needed" and no other text before or after.

If the response does not conform to these guidelines or contains invalid XML:
1. Correct the XML structure while preserving the original content as much as possible.
2. Place the corrected content inside <corrected_response></corrected_response> tags.
3. When correcting, keep the original wording intact; only add missing tags, move existing content to the correct tags, or adjust the structure to comply with the guidelines.
4. If a response is missing a required tag (e.g., <thought>), add it with placeholder content like "[Missing thought process]".
5. If multiple response types are present, keep the most appropriate one based on the content and remove the others.

## Examples:

1. Correct response (no correction needed): This is the most common result/response. If the XML is good reply like this strictly
Input:
<llm_response_content>
<thought>The user has asked about the weather in New York. I need to use the weather API to get this information.</thought>
<tool_call>
{"name": "get_current_weather", "parameters": {"location": "New York, NY", "unit": "Fahrenheit"}}
</tool_call>
</llm_response_content>

Output: no correction needed

2. Multiple response types (keep most appropriate):
Input:
<llm_response_content>
<thought>The user asked about quantum computing. I'll provide a brief explanation.</thought>
<self_response>Researching quantum computing basics.</self_response>
<user_response>Quantum computing is a form of computation that harnesses the principles of quantum mechanics to process information.</user_response>
</llm_response_content>

Output:
<corrected_response>
<thought>The user asked about quantum computing. I'll provide a brief explanation.</thought>
<user_response>Quantum computing is a form of computation that harnesses the principles of quantum mechanics to process information.</user_response>
</corrected_response>

3. Missing closing tag:
Input:
<llm_response_content>
<thought>The user asked about the population of Tokyo.</thought>
<user_response>As of 2021, the estimated population of Tokyo is approximately 14 million people.
</llm_response_content>

Output:
<corrected_response>
<thought>The user asked about the population of Tokyo.</thought>
<user_response>As of 2021, the estimated population of Tokyo is approximately 14 million people.</user_response>
</corrected_response>

4. Incorrect nesting of tags:
Input:
<llm_response_content>
<thought>The user wants to know about famous landmarks in Paris.</thought>
<user_response>Here are some famous landmarks in Paris:
<tool_call>
{"name": "get_landmarks", "parameters": {"city": "Paris"}}
</tool_call>
</user_response>
</llm_response_content>

Output:
<corrected_response>
<thought>The user wants to know about famous landmarks in Paris.</thought>
<tool_call>
{"name": "get_landmarks", "parameters": {"city": "Paris"}}
</tool_call>
</corrected_response>

5. Non-existent tool:
Input:
<llm_response_content>
<thought>The user asked for a recipe. I'll use the recipe finder tool.</thought>
<tool_call>
{"name": "find_recipe", "parameters": {"dish": "spaghetti carbonara"}}
</tool_call>
</llm_response_content>

Output:
<corrected_response>
<thought>The user asked for a recipe. I'll use the recipe finder tool.</thought>
<user_response>I apologize, but I don't have access to a recipe finder tool. However, I can provide you with a general description of how to make spaghetti carbonara if you'd like.</user_response>
</corrected_response>

6. Mixing content outside of tags:
Input:
<llm_response_content>
Hello! <thought>The user greeted me. I should respond politely.</thought>
<user_response>Hi there! How can I assist you today?</user_response>
</llm_response_content>

Output:
<corrected_response>
<thought>The user greeted me. I should respond politely.</thought>
<user_response>Hello! Hi there! How can I assist you today?</user_response>
</corrected_response>

Remember, your role is to ensure proper XML structure and tag usage, not to modify or judge the content of the responses. Dont correct when there is none needed. A lot of the time it should be proper XML with no correction needed (trust your evaluation). Always strive to maintain the original intent and wording of the assistant's response while correcting the XML structure."""
        },
        {
            "role": "user",
            "content": f"""<llm_response_content>{llm_response_text}</llm_response_content>"""
        }
    ]

    chat_completion = openai_client.chat.completions.create(
        model="meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        messages=messages,
        max_tokens=4096,
        temperature=0.2
    )

    llm_output = sanitize_inner_content(chat_completion.choices[0].message.content)
    xml_root_element = f"<root>{llm_output}</root>"
    root = ET.fromstring(xml_root_element)


    corrected_response = root.find('.//corrected_response')
    corrected_response = corrected_response.text.strip() if corrected_response is not None else ""
    if corrected_response != "":
        return ET.fromstring(f"<root>{corrected_response}</root>")
    else:
        return ET.fromstring(f"<root>{llm_response_text}</root>")
