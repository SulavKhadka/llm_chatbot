import asyncio
import websockets
import queue
from dataclasses import asdict
from threading import Thread, Event
from typing import Callable, Dict, Optional, Any, AsyncIterator
from enum import Enum
import logging
import json

from bot_tts import SpeechSegmenter
from data_models import ClientType, ClientRequest, MessageResponse
from secret_keys import USER_ID

logger = logging.getLogger(__name__)

class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"

class ChatbotClient:
    def __init__(self, user_id: str, uri: str, reconnect_interval: float = 5.0):
        self.user_id = user_id
        self.uri = uri
        self.reconnect_interval = reconnect_interval
        self.bot_queue: asyncio.Queue = asyncio.Queue()
        self.user_queue: asyncio.Queue = asyncio.Queue()
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

    async def incoming_messages_listener(self) -> None:
        """Listens for incoming messages with automatic reconnection."""

        logger.info(f"starting bot websocket conn listener...")
        while not self.shutdown_event.is_set():
            try:
                if not self.websocket_conn:
                    await self._connect_to_server()
                    continue
                
                incoming_bot_message = await self.websocket_conn.recv()
                await self._process_bot_message(incoming_bot_message)
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Connection closed, attempting to reconnect...")
                self.websocket_conn = None
                await asyncio.sleep(self.reconnect_interval)
            except Exception as e:
                logger.error(f"Error in incoming message listener: {e}")
                await asyncio.sleep(1)

    async def _process_bot_message(self, message: str) -> None:
        """Processes incoming bot messages with error handling."""
        try:
            parsed_message = MessageResponse(**json.loads(message))
            client_type = parsed_message.client_type
            handler = self.bot_handlers.get(client_type)
            
            if handler:
                await handler(parsed_message)
            else:
                logger.warning(f"No handler found for client type: {client_type}")
        except json.JSONDecodeError:
            logger.error("Failed to parse bot message")
        except Exception as e:
            logger.error(f"Error processing bot message: {e}")

    async def outgoing_messages_listener(self) -> None:
        """Handles outgoing messages with backpressure."""

        logger.info(f"starting user queue listener...")
        while not self.shutdown_event.is_set():
            # logger.debug("OML_PING")
            try:
                message: ClientRequest = await self.user_queue.get()
                message.user_id = self.user_id # injecting user_id, there is gotta be a better way 
                if self.websocket_conn and self.connection_state == ConnectionState.CONNECTED:
                    await self.websocket_conn.send(json.dumps(asdict(message)))
                else:
                    # Requeue message if not connected
                    await self.user_queue.put(message)
                    await asyncio.sleep(0.1)
            except queue.Empty:
                logger.debug("user_queue: its emtpy rn")
                continue
            except Exception as e:
                logger.debug(f"Error in outgoing message listener: {e}")
                await asyncio.sleep(0.1)
        logger.debug(f"not sure what happened {self.shutdown_event.is_set()}")

    def register_handler(self, handler_type: str, handler_function: Callable) -> None:
        """Registers message handlers with type checking."""
        if not asyncio.iscoroutinefunction(handler_function):
            raise ValueError("Handler function must be async")
        
        if handler_type in [ClientType.VOICE, ClientType.TERMINAL, ClientType.CHAT]:
            self.bot_handlers[handler_type.value] = handler_function
        elif handler_type == ClientType.USER:
            self.user_handlers[handler_type.value] = handler_function
        else:
            raise ValueError(f"Unknown handler type: {handler_type}")

    async def start(self) -> None:
        """Starts the client with proper cleanup."""
        try:
            await self._connect_to_server()
            
            tasks = [
                asyncio.create_task(self.incoming_messages_listener(), name="incoming_listener"),
                asyncio.create_task(self.outgoing_messages_listener(), name="outgoing_listener")
            ]
            
            # Add user handler tasks
            for handler_name, handler in self.user_handlers.items():
                logger.info(f"Starting handler: {handler_name}")
                tasks.append(asyncio.create_task(
                    handler(self.user_queue),
                    name=f"handler_{handler_name}"
                ))
            
            # Debug logging for active tasks
            logger.info(f"Running tasks: {[task.get_name() for task in tasks]}")
            
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Error in client: {e}", exc_info=True)
        finally:
            logger.info("Cleaning up...")
            await self.cleanup()

    async def cleanup(self) -> None:
        """Performs cleanup operations."""
        self.shutdown_event.set()
        if self.websocket_conn:
            await self.websocket_conn.close()
        
        # Clear queues
        while not self.bot_queue.empty():
            self.bot_queue.get_nowait()
        while not self.user_queue.empty():
            self.user_queue.get_nowait()

if __name__ == "__main__":
    # Configure detailed logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    client = ChatbotClient(USER_ID, f"ws://localhost:8000/{USER_ID}/ws")
    
    # Voice handler
    segmenter = SpeechSegmenter(
        silence_threshold=0.013,  # Adjust based on your microphone and environment
        silence_duration=2.0,  # 2 seconds of silence to mark end of speech
        sample_rate=16000,  # Match Whisper's expected sample rate
        stt_chunk_duration=2.0,  # Process in 0.5 second chunks
        tts_ws_url="ws://0.0.0.0:8880/tts",
    )
    client.register_handler(ClientType.VOICE, segmenter.handle_bot_response)
    client.register_handler(ClientType.USER, segmenter.process_audio)

    # Run the client
    try:
        asyncio.run(client.start())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        # Ensure proper cleanup
        segmenter.stop_audio_stream()