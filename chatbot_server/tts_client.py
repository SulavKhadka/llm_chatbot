# client.py
import asyncio
import websockets
import json
import base64
import numpy as np
import sounddevice as sd
from queue import Queue, Empty
from threading import Thread
import time

class TTSClient:
    def __init__(self, server_url: str = "ws://localhost:8000/tts"):
        self.server_url = server_url
        self.audio_queue = Queue()
        self.is_playing = False
        self.current_sampling_rate = None
        self.playback_thread = None

    def start_playback(self):
        """Start the audio playback thread."""
        self.is_playing = True
        self.playback_thread = Thread(target=self._play_audio)
        self.playback_thread.start()

    def stop_playback(self):
        """Stop the audio playback thread."""
        print("stopping playback...")
        self.is_playing = False
        if self.playback_thread:
            self.playback_thread.join()

    def _play_audio(self):
        """Continuously play audio from the queue."""
        with sd.OutputStream(
            samplerate=self.current_sampling_rate,
            channels=1,
            dtype='float32'
        ) as stream:
            while self.is_playing:
                try:
                    audio_chunk = self.audio_queue.get(timeout=1.0)
                    stream.write(audio_chunk)
                except Empty:
                    self.is_playing = False
                    break
                except Exception as e:
                    print(f"Error playing audio: {e}")

    async def stream_text(self, text: str, description: str = "Jon is monotonically while speaking naturally."):
        """Send text to server and receive audio stream."""
        try:
            async with websockets.connect(self.server_url) as websocket:
                # Send text to server
                await websocket.send(json.dumps({
                    "text": text,
                    "description": description
                }))

                # Receive and process audio chunks
                while True:
                    response = json.loads(await websocket.recv())
                    
                    # Check for end-of-stream marker
                    if response.get("end", False):
                        break

                    # Process audio chunk
                    sampling_rate = response["sampling_rate"]
                    audio_data = base64.b64decode(response["audio_data"])
                    audio_chunk = np.frombuffer(audio_data, dtype=np.float32)

                    # Initialize playback if needed
                    if not self.current_sampling_rate:
                        self.current_sampling_rate = sampling_rate
                    
                    if not self.is_playing:
                        self.start_playback()

                    # Add chunk to playback queue
                    self.audio_queue.put(audio_chunk)

        except Exception as e:
            print(f"Error in streaming: {e}")

# Example usage
async def main():
    client = TTSClient()
    
    try:
        # Stream some example text
        texts = [
            "Hello! This is a test of the streaming text to speech system.",
            "We can send multiple messages,",
            "and they will be processed and played in order."
        ]
        
        for text in texts:
            await client.stream_text(text)
            await asyncio.sleep(2)  # Wait between messages
            
        # Wait for final audio to finish
        await asyncio.sleep(3)
        
    finally:
        client.stop_playback()

if __name__ == "__main__":
    asyncio.run(main())