from whisper_online import *
import sounddevice as sd
import numpy as np
from scipy import signal
import time
import requests
from uuid import uuid4
import xml.etree.ElementTree as ET
from dataclasses import dataclass

@dataclass
class ClientRequest:
    user_id: str
    client_type: str
    message: str
    user_metadata: dict

def get_bot_response(user_message: str):
    client_request = ClientRequest(user_id="sulav", client_type="voice", message=user_message, user_metadata={})
    try:
        response = requests.post("http://100.85.29.33:8000/sulav_test/latest/message", json=client_request.__dict__, timeout=120)
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

    def is_silence(self, audio_chunk):
        """Check if an audio chunk is silence based on RMS value"""
        rms = np.sqrt(np.mean(np.square(audio_chunk)))
        if rms < self.silence_threshold:
            return True
        return rms < self.silence_threshold

    def process_audio(self):
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
                if self.is_silence(audio_chunk):
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
                        tts_stream.feed(bot_response)
                        tts_stream.play_async()
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


def main():
    # Initialize with custom parameters
    segmenter = SpeechSegmenter(
        silence_threshold=0.013,  # Adjust based on your microphone and environment
        silence_duration=2.0,  # 2 seconds of silence to mark end of speech
        sample_rate=16000,  # Match Whisper's expected sample rate
        chunk_duration=1.0,  # Process in 0.5 second chunks
    )

    # Start processing
    segmenter.process_audio()


if __name__ == "__main__":
    from RealtimeTTS import TextToAudioStream, CoquiEngine

    tts_engine = CoquiEngine(
        model_name="tts_models/multilingual/multi-dataset/xtts_v2",
        full_sentences=True,
        speed=1.2,
        stream_chunk_size=80,
        overlap_wav_len=2048,
        thread_count=12,
        sentence_silence_duration=0.4,
        comma_silence_duration=0.22,
    )  # replace with your TTS engine
    tts_stream = TextToAudioStream(tts_engine)
    main()
