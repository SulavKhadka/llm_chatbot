import json
from whisper_online import *
import sounddevice as sd
import numpy as np
from scipy import signal
import time
from chatbot_server.tts_client import TTSClient
from uuid import uuid4
import xml.etree.ElementTree as ET
from dataclasses import asdict
from llm_chatbot import utils
import torch
from data_models import ClientRequest, MessageResponse
from queue import Queue, Empty
import asyncio
import copy
import pvporcupine
from secret_keys import PORCUPINE_API_KEY

class SpeechSegmenter:
    def __init__(
        self,
        silence_threshold=0.01,
        silence_duration=1.0,
        sample_rate=16000,
        chunk_duration=1.0,
        tts_ws_url="ws://0.0.0.0:8880/tts",
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

        self.wake_word_engine = pvporcupine.create(access_key=PORCUPINE_API_KEY, keywords=['porcupine'])

        # Initialize ASR components
        self.asr = FasterWhisperASR("en", "distil-large-v3")
        self.online = OnlineASRProcessor(self.asr)

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
        self.last_speech_time = time.time()
        self.current_segment = []
        self.all_segments = []
        self.is_speaking = False

        # TTS engine
        self.tts_engine = TTSClient(tts_ws_url)

        self.audio_queue = Queue()
        self._audio_thread = None
        self._stop_audio = False
    
    def _audio_callback(self, indata, frames, time, status):
        """Callback for sounddevice to handle incoming audio"""
        if status:
            print(f"Audio callback status: {status}")
        # Put audio data in the queue
        self.audio_queue.put(indata.copy())

    def start_audio_stream(self):
        """Start the audio stream in non-blocking mode"""
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.float32,
            blocksize=self.chunk_size,
            callback=self._audio_callback
        )
        self.stream.start()

    def stop_audio_stream(self):
        """Stop the audio stream"""
        self._stop_audio = True
        if self.stream:
            self.stream.stop()
            self.stream.close()

    def is_silence(self, audio_chunk):
        """Check if an audio chunk is silence based on RMS value"""        
        vad_confidences = []
        for i in range(0, len(audio_chunk), self.vad_chunk_size):

            # some weirdness but its to make sure the vad_chunk is always some specified size.
            if i+self.vad_chunk_size > len(audio_chunk):
                vad_chunk = np.zeros(self.vad_chunk_size, dtype=np.float32)
                vad_chunk[:len(audio_chunk)-i] = audio_chunk[i:i+self.vad_chunk_size]
            else:
                vad_chunk = audio_chunk[i:i+self.vad_chunk_size]

            if self.wake_word_engine.process((vad_chunk * 32767).astype(np.int16)) >= 0:
                if not self.is_speaking:
                    new_audio_chunk = np.zeros(len(audio_chunk), dtype=np.float32)
                    new_audio_chunk[i: len(audio_chunk)] = audio_chunk[i: len(audio_chunk)]
                    audio_chunk = copy.deepcopy(new_audio_chunk)
                    self.all_segments = []

                    self.is_speaking = True
                    return False
            
            if self.is_speaking:
                vad_confidences.append(self.vad_model(torch.from_numpy(vad_chunk), 16000).item())
            else:
                vad_confidences.append(0.0)
        
        vad_confidences = torch.tensor(vad_confidences)
        smas = np.convolve(vad_confidences, np.ones(5), 'valid') / 5
        chunk_silence_threshold = float(smas.max())
        
        # print(f"chunk_silence_threshold: {chunk_silence_threshold} | max_conf: {vad_confidences.max()} | median: {vad_confidences.median()} | min: {vad_confidences.min()}")
        return chunk_silence_threshold < self.silence_threshold

    async def handle_bot_response(self, response: MessageResponse):
        print(f"ASSISTANT: {response}")
        self.tts_engine.stop_playback()
        for segment in utils.split_markdown_text(response.content):
            await self.tts_engine.stream_text(segment)

    async def process_audio(self, user_queue: Queue):
        """Process incoming audio asynchronously"""
        print("Starting audio processing...")
        self.start_audio_stream()
        
        try:
            while not self._stop_audio:
                # Get audio data from the queue without blocking the event loop
                try:
                    audio_data = await asyncio.get_event_loop().run_in_executor(
                        None, 
                        self.audio_queue.get, 
                        True, 
                        0.06  # 60ms timeout
                    )
                except Empty:
                    await asyncio.sleep(0)
                    continue

                # Process audio chunk
                audio_chunk = audio_data.flatten()
                current_time = time.time()

                # Check for silence
                if self.tts_engine.is_playing is False:
                    if self.is_silence(audio_chunk):
                        if (self.is_speaking and 
                            (current_time - self.last_speech_time) > self.silence_duration):
                            
                            # End of speech segment detected
                            self.is_speaking = False
                            final_output = self.online.finish()
                            
                            if final_output[2]:
                                self.all_segments.append(final_output[2])

                            user_input_segment = "".join(self.all_segments)
                            print(f"Speech segment complete: {user_input_segment}")
                            
                            message = ClientRequest(
                                user_id="",
                                client_type="voice",
                                message=user_input_segment,
                                user_metadata={}
                            )
                            
                            # Put message in queue
                            await user_queue.put(message)
                            print("Message sent to queue")
                            
                            self.all_segments = []
                            self.online.init()
                    else:
                        self.last_speech_time = current_time
                        self.is_speaking = True

                # Process with Whisper if in speech segment
                if self.is_speaking:
                    self.online.insert_audio_chunk(audio_chunk)
                    output = self.online.process_iter()
                    if output[2]:
                        self.current_segment = output
                        self.all_segments.append(output[2])
                        print(f"Current segment: {output[2]}")

                # Give other tasks a chance to run
                await asyncio.sleep(0)
                
        except Exception as e:
            print(f"Error in process_audio: {e}")
        finally:
            self.stop_audio_stream()
            print("Audio processing stopped")

    def get_segments(self):
        """Return all captured segments"""
        return self.all_segments

async def main():
    # Initialize with custom parameters
    segmenter = SpeechSegmenter(
        silence_threshold=0.013,  # Adjust based on your microphone and environment
        silence_duration=2.0,  # 2 seconds of silence to mark end of speech
        sample_rate=16000,  # Match Whisper's expected sample rate
        chunk_duration=2.0,  # Process in 0.5 second chunks
    )

    # Start processing
    await segmenter.process_audio()


if __name__ == "__main__":
    from chatbot_server.tts_client import TTSClient
    import asyncio

    tts_engine = TTSClient("ws://0.0.0.0:8880/tts")
    asyncio.run(main())
