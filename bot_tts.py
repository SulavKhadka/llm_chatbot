from whisper_online import *
import sounddevice as sd
import numpy as np
from scipy import signal
import time
import requests
from uuid import uuid4
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from llm_chatbot import utils
import torch

@dataclass
class ClientRequest:
    user_id: str
    client_type: str
    message: str
    user_metadata: dict

def get_bot_response(user_message: str):
    client_request = ClientRequest(user_id="sulav", client_type="voice", message=user_message, user_metadata={})
    try:
        response = requests.post("http://0.0.0.0:8000/sulav_test/latest/message", json=client_request.__dict__, timeout=120)
        if response.status_code == 200:
            return response.text
        return f"error processing bot response, status code: {response.status_code}"
    except Exception as e:
        print(e)
        return f"error processing bot response, error: {e}"
    

class SpeechSegmenter:
    def __init__(
        self,
        silence_threshold=0.01,
        silence_duration=1.0,
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

    def is_silence_rms(self, audio_chunk):
        """Check if an audio chunk is silence based on RMS value"""
        rms = np.sqrt(np.mean(np.square(audio_chunk)))
        print(f"rms value for silence: {rms}")
        return rms < self.silence_threshold
    
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
            
            vad_confidences.append(self.vad_model(torch.from_numpy(vad_chunk), 16000).item())
        
        vad_confidences = torch.tensor(vad_confidences)
        smas = np.convolve(vad_confidences, np.ones(5), 'valid') / 5
        chunk_silence_threshold = float(smas.max())
        
        # print(f"chunk_silence_threshold: {chunk_silence_threshold} | max_conf: {vad_confidences.max()} | median: {vad_confidences.median()} | min: {vad_confidences.min()}")
        return chunk_silence_threshold < self.silence_threshold

    async def process_audio(self):
        """Process incoming audio and detect speech segments"""
        self.stream.start()
        print("Listening... (Press Ctrl+C to stop)")

        try:
            while True:
                # Get audio chunk
                audio_data, overflowed = self.stream.read(self.chunk_size)
                if overflowed:
                    print("Warning: Audio buffer overflowed")

                # Process audio
                audio_chunk = audio_data.flatten()
                current_time = time.time()

                # Check for silence
                if self.is_silence(audio_chunk) and tts_engine.is_playing is False:
                    if (
                        self.is_speaking
                        and (current_time - self.last_speech_time)
                        > self.silence_duration
                    ):
                        # End of speech segment detected
                        self.is_speaking = False
                        final_output = self.online.finish()
                        if final_output[2]:  # If there's text
                            self.all_segments.append(final_output[2])

                        user_input_segment = "".join(self.all_segments)
                        print("\nSpeech segment complete.\nUser:", user_input_segment)
                        bot_response = get_bot_response(user_input_segment)
                        print(f"ASSISTANT: {bot_response}")
                        tts_engine.stop_playback()
                        for bot_response_segment in utils.split_markdown_text(bot_response):
                            await tts_engine.stream_text(bot_response_segment)
                        
                        print("\nListening for new segment...")

                        self.all_segments = []
                        self.online.init()  # Reset for next segment
                else:
                    self.last_speech_time = current_time
                    self.is_speaking = True

                # Process with Whisper if we're in a speech segment
                if self.is_speaking:
                    self.online.insert_audio_chunk(audio_chunk)
                    output = self.online.process_iter()
                    if output[2]:  # If there's text
                        self.current_segment = output
                        self.all_segments.append(output[2])
                        print(f"\rCurrent: {output[2]}", end="", flush=True)

        except KeyboardInterrupt:
            print("\n\nStopping audio capture...")
        finally:
            self.stream.stop()
            self.stream.close()

            # Process any remaining audio
            final_output = self.online.finish()
            if final_output[2]:
                self.all_segments.append(final_output[2])

            print("\nAll captured segments:")
            for i, segment in enumerate(self.all_segments, 1):
                print(f"Segment {i}: {segment[2]}")

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
