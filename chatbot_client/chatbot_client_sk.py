import asyncio
import websockets
import queue
from dataclasses import dataclass
from threading import Thread, Event
from typing import Callable, Dict, Optional, Any, AsyncIterator
from enum import Enum
import logging

from chatbot_client.data_models import ClientRequest, ClientType
from bot_tts import SpeechSegmenter

logger = logging.getLogger(__name__)

class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"

class ChatbotClient:
    def __init__(self, uri: str, reconnect_interval: float = 5.0):
        self.uri = uri
        self.reconnect_interval = reconnect_interval
        self.bot_queue: queue.Queue = queue.Queue()
        self.user_queue: queue.Queue = queue.Queue()
        self.websocket_conn: Optional[websockets.WebSocketClientProtocol] = None
        self.connection_state = ConnectionState.DISCONNECTED
        self.shutdown_event = Event()
        
        self.bot_handlers: Dict[str, Callable] = {}
        self.user_handlers: Dict[str, Callable] = {}
    
    async def _connect_to_server(self) -> None:
        """Establishes WebSocket connection with retry logic."""
        while not self.shutdown_event.is_set():
            try:
                self.connection_state = ConnectionState.CONNECTING
                self.websocket_conn = await websockets.connect(self.uri)
                self.connection_state = ConnectionState.CONNECTED
                logger.info("Successfully connected to WebSocket server")
                return
            except Exception as e:
                logger.error(f"Failed to connect to server: {e}")
                self.connection_state = ConnectionState.RECONNECTING
                await asyncio.sleep(self.reconnect_interval)

    async def incoming_messages_listener(self):
        while True:
            try:
                incoming_bot_message = await self.websocket_conn.recv()
                self.bot_queue.put(incoming_bot_message)
            except websockets.exceptions.ConnectionClosed as e:
                print(f"Failed to receive message: Connection closed: {e}")
                break

    async def outgoing_messages_listener(self):
        while True:
            outgoing_user_message = self.user_queue.get()
            if outgoing_user_message:
                try:
                    await self.websocket_conn.send(outgoing_user_message)
                except websockets.exceptions.ConnectionClosed as e:
                    print(f"Failed to send message: Connection closed: {e}")
                    raise e

    async def bot_message_handler(self):
        """Handles messages from the bot. The handlers written for it should be a one way function as this doesnt react to the function response"""
        while True:
            bot_message = self.bot_queue.get()
            if bot_message:
                print(f"Bot message: {bot_message}")
                handler_function = self.bot_handlers.get(ClientRequest.client_type)
                if handler_function:
                    try:
                        await handler_function(bot_message)
                    except Exception as e:
                        print(f"Error in bot message handler: {e}")
                else:
                    print(f"No handler function found for bot message client type: {bot_message.client_type}")
    
    async def user_message_handler(self):
        """Handles messages from the user. Should accept queue as an argument"""
        # run the handlers in the background
        for user_handler in self.user_handlers.values():
            asyncio.create_task(user_handler(self.user_queue))
        
        # wait for all the user handlers to finish
        await asyncio.gather(*self.user_handlers.values())

    def register_handler(self, client_type: ClientType, handler_function: Callable):
        if client_type == ClientType.VOICE:
            self.bot_handlers[client_type] = handler_function
        elif client_type == ClientType.CHAT:
            self.user_handlers[client_type] = handler_function

    async def start(self):
        # initialise websocket connection to server
        await self._connect_to_server()
        
        # run the handlers in a separate thread
        self.bot_message_handler_thread = Thread(target=self.bot_message_handler, daemon=True)
        self.bot_message_handler_thread.start()
        
        # run the user handler functions in a separate thread
        self.user_message_handler_thread = Thread(target=self.user_message_handler, daemon=True)
        self.user_message_handler_thread.start()

        # split recv to an async while loop and send to an async while loop
        # they send out or listen to messages from two queues (bot_queue, user_queue)
        await asyncio.gather(self.incoming_messages_listener(), self.outgoing_messages_listener())

        # wait for the threads to finish
        self.bot_message_handler_thread.join()
        self.user_message_handler_thread.join()




if __name__ == "__main__":
    client = ChatbotClient("ws://localhost:8000/ws")

    # Voice handler
    segmenter = SpeechSegmenter(
        silence_threshold=0.013,  # Adjust based on your microphone and environment
        silence_duration=2.0,  # 2 seconds of silence to mark end of speech
        sample_rate=16000,  # Match Whisper's expected sample rate
        chunk_duration=2.0,  # Process in 0.5 second chunks
        tts_ws_url="ws://0.0.0.0:8880/tts",
    )
    client.register_handler(ClientType.VOICE, segmenter.process_audio)

    client.start()