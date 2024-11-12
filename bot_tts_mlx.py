import asyncio
import sys
import warnings
from typing import List, Optional, Tuple, Union, Generator

import sounddevice as sd
import numpy as np
import time
import requests
from uuid import uuid4
import xml.etree.ElementTree as ET
from dataclasses import dataclass
import torch

from mlx_whisper.transcribe_stream import transcribe_stream  # Import the streaming transcription function
from mlx_whisper.load_models import load_model
from mlx_whisper.tokenizer import get_tokenizer
from mlx_whisper.decoding import DecodingOptions
from mlx_whisper.audio import (
    HOP_LENGTH,
    N_FRAMES,
    SAMPLE_RATE,
    N_SAMPLES,
    pad_or_trim,
    log_mel_spectrogram,
)
from llm_chatbot.tts_client import TTSClient

@dataclass
class ClientRequest:
    user_id: str
    client_type: str
    message: str
    user_metadata: dict

def get_bot_response(user_message: str):
    client_request = ClientRequest(user_id="sulav", client_type="voice", message=user_message, user_metadata={})
    try:
        response = requests.post("http://100.78.237.8:8000/sulav_test/latest/message", json=client_request.__dict__, timeout=120)
        if response.status_code == 200:
            return response.text
        return f"error processing bot response, status code: {response.status_code}"
    except Exception as e:
        print(e)
        return f"error processing bot response, error: {e}"
    

class SpeechSegmenter:
    def __init__(
        self,
        silence_threshold=0.005,
        silence_duration=1.5,
        sample_rate=16000,
        chunk_duration=1.0,
    ):
        """
        Initialize speech segmenter with silence detection

        Args:
            silence_threshold: RMS threshold below which audio is considered silence
            silence_duration: Duration of silence (in seconds) to mark end of speech
            sample_rate: Audio sample rate in Hz
            chunk_duration: Duration of each audio chunk in seconds
        """
        self.silence_threshold = silence_threshold
        self.silence_duration = silence_duration
        self.sample_rate = sample_rate
        self.chunk_duration = chunk_duration

        # Initialize VAD model
        self.vad_model, self.vad_utils = torch.hub.load(repo_or_dir='snakers4/silero-vad',
                              model='silero_vad',
                              force_reload=True)
        self.vad_chunk_size = 512 if self.sample_rate == 16000 else 256

        # Initialize ASR model
        self.model_path = "mlx-community/whisper-large-v3-turbo"  # Replace with your model path
        self.model = load_model(self.model_path)
        self.tokenizer = get_tokenizer(
            self.model.is_multilingual,
            num_languages=self.model.num_languages,
            language="en",
            task="transcribe",
        )
        self.decode_options = {
            "language": "en",
            "task": "transcribe",
            "fp16": True,
        }

        # Setup audio stream
        self.chunk_size = int(sample_rate * chunk_duration)
        print(sd.query_devices())
        self.stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype=np.float32,
            blocksize=self.chunk_size,
        )

        # State tracking
        self.last_silence_time = time.time()
        self.current_segment = []
        self.all_segments = []
        self.is_speaking = False

    def is_silence_rms(self, audio_chunk):
        """Check if an audio chunk is silence based on RMS value"""
        rms = np.sqrt(np.mean(np.square(audio_chunk)))
        print(f"rms value for silence: {rms}")
        return rms < self.silence_threshold
    
    def is_silence(self, audio_chunk):
        """Check if an audio chunk is silence based on RMS value"""
        
        def int2float(sound):
            abs_max = np.abs(sound).max()
            sound = sound.astype('float32')
            if abs_max > 0:
                sound *= 1/32768
            sound = sound.squeeze()  # depends on the use case
            return sound
        
        vad_confidences = []
        for i in range(0, len(audio_chunk), self.vad_chunk_size):
            # some weirdness but its to make sure the vad_chunk is always some specified size.
            vad_chunk = np.zeros(self.vad_chunk_size, dtype=np.float32)
            vad_chunk[:(min(self.sample_rate, i+self.vad_chunk_size) - i)] = audio_chunk[i:i+self.vad_chunk_size]
            
            vad_confidences.append(self.vad_model(torch.from_numpy(vad_chunk), 16000).item())
        vad_confidences = torch.tensor(vad_confidences)
        chunk_silence_threshold = float(vad_confidences.mean())
        print(f"chunk_silence_threshold: {chunk_silence_threshold} | max_conf: {vad_confidences.max()} | median: {vad_confidences.median()} | min: {vad_confidences.min()}")
        return chunk_silence_threshold < 0.1

    async def process_audio(self):
        """Process incoming audio and detect speech segments"""
        self.stream.start()
        print("Listening... (Press Ctrl+C to stop)")

        # Initialize variables for the transcription
        audio_buffer = np.array([], dtype=np.float32)
        silence_start = None
        speech_start = None
        tts_stream = TTSClient()

        try:
            while True:
                # Get audio chunk
                audio_data, overflowed = self.stream.read(self.chunk_size)
                if overflowed:
                    print("Warning: Audio buffer overflowed")

                # Flatten audio data
                audio_chunk = audio_data.flatten()
                current_time = time.time()

                # Append to the audio buffer
                audio_buffer = np.concatenate((audio_buffer, audio_chunk))

                # Check for silence
                if self.is_silence(audio_chunk):
                    if self.is_speaking:
                        if silence_start is None:
                            silence_start = current_time
                        elif (current_time - silence_start)  > self.silence_duration:
                            # End of speech segment detected
                            self.is_speaking = False
                            silence_start = None

                            # Create an audio chunk generator
                            def audio_chunk_generator():
                                yield audio_buffer

                            # Process the buffered audio with transcribe_stream
                            transcription = ""
                            for segment in transcribe_stream(audio_chunk_generator(), **self.decode_options):
                                transcription += segment["text"]
                                print(f"\rTranscribing: {transcription}", end="", flush=True)

                            print("\nSpeech segment complete.\nUser:", transcription)
                            bot_response = get_bot_response(transcription)
                            print(f"ASSISTANT: {bot_response}")

                            tts_stream.stop_playback()
                            await tts_stream.stream_text(bot_response)
                            print("\nListening for new segment...")

                            # Reset the audio buffer
                            audio_buffer = np.array([], dtype=np.float32)
                            self.all_segments = []
                    else:
                        silence_start = current_time
                else:
                    # Reset silence timer
                    silence_start = None
                    if not self.is_speaking:
                        self.is_speaking = True
                        speech_start = current_time
                    self.last_silence_time = current_time

        except KeyboardInterrupt:
            print("\n\nStopping audio capture...")
        finally:
            self.stream.stop()
            self.stream.close()

            # Process any remaining audio
            if len(audio_buffer) > 0:
                # Create an audio chunk generator
                def audio_chunk_generator():
                    yield audio_buffer

                # Process the buffered audio with transcribe_stream
                transcription = ""
                for segment in transcribe_stream(audio_chunk_generator(), **self.decode_options):
                    transcription += segment["text"]
                    print(f"\rTranscribing: {transcription}", end="", flush=True)

                print("\nFinal speech segment complete.\nUser:", transcription)

    def get_segments(self):
        """Return all captured segments"""
        return self.all_segments


async def main():
    # Initialize with custom parameters
    segmenter = SpeechSegmenter(
        silence_threshold=0.013,  # Adjust based on your microphone and environment
        silence_duration=2.0,  # 2 seconds of silence to mark end of speech
        sample_rate=16000,  # Match Whisper's expected sample rate
        chunk_duration=1.0,  # Process in 1 second chunks
    )

    # Start processing
    await segmenter.process_audio()


if __name__ == "__main__":
    asyncio.run(main())
