from typing import Union, List, Dict, Any, Literal
from enum import Enum
from pydantic import BaseModel, Field, model_validator

class ResponseType(str, Enum):
    TOOL_USE = "tool_use"
    INTERNAL_RESPONSE = "internal_response"
    USER_RESPONSE = "response_to_user"

class ToolParameter(BaseModel):
    name: str
    parameters: Dict[str, Any]

class BaseResponseContent(BaseModel):
    type: ResponseType

class ToolUseResponse(BaseResponseContent):
    type: Literal[ResponseType.TOOL_USE]
    content: List[ToolParameter]

class TextResponse(BaseResponseContent):
    type: Literal[ResponseType.INTERNAL_RESPONSE, ResponseType.USER_RESPONSE]
    content: str

ResponseContent = Union[ToolUseResponse, TextResponse]

class AssistantResponse(BaseModel):
    thought: str = Field(description="The assistant's thought process or reasoning")
    response: ResponseContent

    @model_validator(mode='after')
    def validate_response_content(self) -> 'AssistantResponse':
        """Ensure response content matches the type"""
        if self.response.type == ResponseType.TOOL_USE:
            assert isinstance(self.response, ToolUseResponse), "Tool use responses must use ToolUseResponse model"
        else:
            assert isinstance(self.response, TextResponse), "Non-tool responses must use TextResponse model"
        return self

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "thought": "Now that I have the location, I'm gonna call get_current_weather tool to get the current weather information for New York City.",
                    "response": {
                        "type": "tool_use",
                        "content": [
                            {
                                "name": "weather_api",
                                "parameters": {"location": "New York City"}
                            }
                        ]
                    }
                },
                {
                    "thought": "I've received the weather information for New York City. I'll summarize this data in a user-friendly response.",
                    "response": {
                        "type": "response_to_user",
                        "content": "The weather in New York City today is partly cloudy with a temperature of 72°F (22°C). The humidity is at 65%, and there's a light breeze with wind speeds of 8 mph. It's a pleasant day overall!"
                    }
                }
            ]
        }

    @classmethod
    def create_tool_response(cls, thought: str, tools: List[Dict[str, Any]]) -> 'AssistantResponse':
        """Helper method to create a tool use response"""
        return cls(
            thought=thought,
            response=ToolUseResponse(
                type=ResponseType.TOOL_USE,
                content=[ToolParameter(**tool) for tool in tools]
            )
        )
    
    @classmethod
    def create_text_response(cls, thought: str, content: str, is_user_response: bool = True) -> 'AssistantResponse':
        """Helper method to create a text response"""
        response_type = ResponseType.USER_RESPONSE if is_user_response else ResponseType.INTERNAL_RESPONSE
        return cls(
            thought=thought,
            response=TextResponse(
                type=response_type,
                content=content
            )
        )


class CriticResponse(BaseModel):
    situation_analysis: str = Field(description="The cirtic's reasoning/analysis of the situation")
    thought: str = Field(description="The assistant's thought process or reasoning")
    internal_response: str = Field(description="Response formulated as an internal insight from agent on what it should do next")


class ClientType(Enum):
    CHAT = "chat"
    VOICE = "voice"
    TERMINAL = "terminal"
    USER = "user"

@dataclass
class ClientRequest:
    user_id: str
    client_type: ClientType
    message: str
    user_metadata: dict

@dataclass
class MessageResponse:
    client_type: ClientType
    content: str
    raw_response: str
