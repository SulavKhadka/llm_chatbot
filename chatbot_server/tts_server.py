# server.py
import torch
from parler_tts import ParlerTTSForConditionalGeneration, ParlerTTSStreamer
from transformers import AutoTokenizer
from fastapi import FastAPI, WebSocket
import uvicorn
import asyncio
import json
import numpy as np
import base64
from typing import Optional
from threading import Thread

class TTSProcessor:
    def __init__(
        self,
        model_name: str = "parler-tts/parler-tts-mini-v1",
        device: str = "cuda:0",
        chunk_size_seconds: float = 0.5
    ):
        self.device = device
        self.dtype = torch.bfloat16
        self.chunk_size_seconds = chunk_size_seconds
        
        # Initialize model and tokenizer
        print("Loading model and tokenizer...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = ParlerTTSForConditionalGeneration.from_pretrained(
            model_name
        ).to(device, dtype=self.dtype)
        
        # Get audio configuration
        self.sampling_rate = self.model.audio_encoder.config.sampling_rate
        self.frame_rate = self.model.audio_encoder.config.frame_rate

    async def generate_speech(self, text: str, description: str = "Jon's voice is speaking naturally."):
        """Generate speech from text and yield audio chunks."""
        play_steps = int(self.frame_rate * self.chunk_size_seconds)
        streamer = ParlerTTSStreamer(
            self.model,
            device=self.device,
            play_steps=play_steps
        )

        inputs = self.tokenizer(description, return_tensors="pt").to(self.device)
        prompt = self.tokenizer(text, return_tensors="pt").to(self.device)

        generation_kwargs = dict(
            input_ids=inputs.input_ids,
            prompt_input_ids=prompt.input_ids,
            attention_mask=inputs.attention_mask,
            prompt_attention_mask=prompt.attention_mask,
            streamer=streamer,
            do_sample=True,
            temperature=1.0,
            min_new_tokens=10,
        )

        # Start generation in a separate thread
        generation_task = Thread(target=self.model.generate, kwargs=generation_kwargs)
        generation_task.start()

        for new_audio in streamer:
            if new_audio.shape[0] == 0:
                break
            # Convert to base64 for transmission
            audio_bytes = new_audio.tobytes()
            audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            yield {
                "sampling_rate": self.sampling_rate,
                "chunk_size": new_audio.shape[0],
                "audio_data": audio_b64
            }

        # await generation_task  # Ensure generation is complete

app = FastAPI()
tts_processor = TTSProcessor()

@app.websocket("/tts")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Receive text from client
            data = await websocket.receive_json()
            text = data.get("text", "")
            description = data.get("description", "Speaking naturally.")
            
            # Generate and stream audio chunks
            async for audio_chunk in tts_processor.generate_speech(text, description):
                await websocket.send_json(audio_chunk)
                
            # Send end-of-stream marker
            await websocket.send_json({"end": True})
            
    except Exception as e:
        print(f"Error in WebSocket connection: {e}")
    # finally:
    #     await websocket.close()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8880)