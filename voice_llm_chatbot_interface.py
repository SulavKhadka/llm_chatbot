from whisper_online import *
import sounddevice as sd
import numpy as np
from scipy import signal
import time

from uuid import uuid4
from secret_keys import POSTGRES_DB_PASSWORD
from prompts import SYS_PROMPT, TOOLS_PROMPT_SNIPPET, RESPONSE_FLOW_2
from llm_chatbot import chatbot, utils, function_tools
import xml.etree.ElementTree as ET

# Initialize the ChatBot
tools_prompt = TOOLS_PROMPT_SNIPPET.format(TOOL_LIST=function_tools.get_tool_list_prompt(function_tools.get_tools()))
chatbot_system_msg = SYS_PROMPT.format(TOOLS_PROMPT=tools_prompt, RESPONSE_FLOW=RESPONSE_FLOW_2)
db_config = {    
    "dbname":"chatbot_db",
    "user":"chatbot_user",
    "password":POSTGRES_DB_PASSWORD,
    "host":"localhost",
    "port":"5432"
}


llm_bot = chatbot.ChatBot(
                model="qwen/qwen-2.5-72b-instruct", 
                chat_id=str(uuid4()),
                tokenizer_model="Qwen/Qwen2.5-72B-Instruct",
                system=chatbot_system_msg,
                db_config=db_config
            )


def get_bot_response(user_message: str):
    response = llm_bot(user_message)
    response = utils.sanitize_inner_content(response)
    root = ET.fromstring(f"<root>{response}</root>")
    
    # Extract text from <response_to_user> tag
    response_to_user = root.find('.//response_to_user')
    return response_to_user.text


class SpeechSegmenter:
    def __init__(self, silence_threshold=0.01, silence_duration=1.0, sample_rate=16000, chunk_duration=1.0):
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
        self.asr = FasterWhisperASR("en", "large-v2")
        self.online = OnlineASRProcessor(self.asr)
        
        # Setup audio stream
        self.chunk_size = int(sample_rate * chunk_duration)
        self.stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype=np.float32,
            blocksize=self.chunk_size
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
                    if self.is_speaking and (current_time - self.last_speech_time) > self.silence_duration:
                        # End of speech segment detected
                        self.is_speaking = False
                        final_output = self.online.finish()
                        if final_output[2]:  # If there's text
                            self.all_segments.append(final_output)

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
                        print(f"\rCurrent: {output[2]}", end='', flush=True)
                
        except KeyboardInterrupt:
            print("\n\nStopping audio capture...")
        finally:
            self.stream.stop()
            self.stream.close()
            
            # Process any remaining audio
            final_output = self.online.finish()
            if final_output[2]:
                self.all_segments.append(final_output)
            
            print("\nAll captured segments:")
            for i, segment in enumerate(self.all_segments, 1):
                print(f"Segment {i}: {segment[2]}")
    
    def get_segments(self):
        """Return all captured segments"""
        return self.all_segments

def main():
    # Initialize with custom parameters
    segmenter = SpeechSegmenter(
        silence_threshold=0.01,  # Adjust based on your microphone and environment
        silence_duration=2.0,    # 2 seconds of silence to mark end of speech
        sample_rate=16000,       # Match Whisper's expected sample rate
        chunk_duration=0.5       # Process in 0.5 second chunks
    )
    
    # Start processing
    segmenter.process_audio()

if __name__ == "__main__":
    from RealtimeTTS import TextToAudioStream, CoquiEngine
    tts_engine = CoquiEngine(model_name="tts_models/multilingual/multi-dataset/xtts_v2", speed=1.5, stream_chunk_size=40, overlap_wav_len=2048, thread_count=12) # replace with your TTS engine
    tts_stream = TextToAudioStream(tts_engine)
    main()