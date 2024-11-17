from dataclasses import dataclass
from enum import Enum

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