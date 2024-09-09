from fastapi import FastAPI, HTTPException, File, UploadFile
from pydantic import BaseModel
from uuid import uuid4
from typing import Dict, Any, Optional, List
from llm_chatbot.chatbot import ChatBot
from llm_chatbot import function_tools
import os
import numpy as np
from PIL import Image
import soundfile as sf
import ffmpeg
from prompts import SYS_PROMPT, TOOLS_PROMPT_SNIPPET, RESPONSE_FLOW_2

app = FastAPI()

# Initialize ChatBot configurations
tools_prompt = TOOLS_PROMPT_SNIPPET.format(TOOL_LIST=function_tools.get_tool_list_prompt(function_tools.get_tools()))
chatbot_system_msg = SYS_PROMPT.format(TOOLS_PROMPT=tools_prompt, RESPONSE_FLOW=RESPONSE_FLOW_2)

# In-memory storage for active ChatBot instances
chatbots: Dict[str, ChatBot] = {}

MEDIA_FOLDER = "/media"
os.makedirs(MEDIA_FOLDER, exist_ok=True)

class ChatSession(BaseModel):
    model: str
    tokenizer_model: Optional[str] = ""
    system: Optional[str] = chatbot_system_msg

class Message(BaseModel):
    content: str

class ChatResponse(BaseModel):
    chat_id: str
    response: str

@app.post("/chat", response_model=ChatResponse)
async def create_chat(chat_session: ChatSession):
    chat_id = str(uuid4())
    chatbots[chat_id] = ChatBot(
        model=chat_session.model,
        chat_id=chat_id,
        tokenizer_model=chat_session.tokenizer_model,
        system=chat_session.system
    )
    response = chatbots[chat_id]("Hello! This is the start of our conversation.")
    return ChatResponse(chat_id=chat_id, response=response)

@app.post("/chat/{chat_id}/message", response_model=ChatResponse)
async def send_message(chat_id: str, message: Message):
    if chat_id not in chatbots:
        raise HTTPException(status_code=404, detail="Chat session not found")
    response = chatbots[chat_id](message.content)
    return ChatResponse(chat_id=chat_id, response=response)

@app.get("/chat/{chat_id}/history")
async def get_chat_history(chat_id: str):
    if chat_id not in chatbots:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return {"chat_id": chat_id, "history": chatbots[chat_id].messages}

@app.delete("/chat/{chat_id}")
async def delete_chat(chat_id: str):
    if chat_id not in chatbots:
        raise HTTPException(status_code=404, detail="Chat session not found")
    del chatbots[chat_id]
    return {"message": f"Chat session {chat_id} has been deleted"}

@app.put("/chat/{chat_id}/system")
async def update_system_message(chat_id: str, system_message: str):
    if chat_id not in chatbots:
        raise HTTPException(status_code=404, detail="Chat session not found")
    chatbots[chat_id].system["content"] = system_message
    return {"message": f"System message for chat session {chat_id} has been updated"}

@app.get("/chat/{chat_id}/system")
async def get_system_message(chat_id: str):
    if chat_id not in chatbots:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return {"system_message": chatbots[chat_id].system["content"]}

@app.post("/chat/{chat_id}/media")
async def process_media(chat_id: str, file: UploadFile, media_type: str):
    if chat_id not in chatbots:
        raise HTTPException(status_code=404, detail="Chat session not found")
    
    filename = f"{chat_id}_{uuid4()}{os.path.splitext(file.filename)[1]}"
    file_path = os.path.join(MEDIA_FOLDER, filename)
    
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())
    
    np_filename = os.path.splitext(filename)[0] + ".npy"
    np_file_path = os.path.join(MEDIA_FOLDER, np_filename)
    
    if media_type == 'photo':
        with Image.open(file_path) as img:
            np_image = np.array(img)
        np.save(np_file_path, np_image)
    elif media_type == 'video':
        probe = ffmpeg.probe(file_path)
        video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        width, height = int(video_info['width']), int(video_info['height'])
        out, _ = (
            ffmpeg
            .input(file_path)
            .output('pipe:', format='rawvideo', pix_fmt='rgb24')
            .run(capture_stdout=True)
        )
        video = np.frombuffer(out, np.uint8).reshape([-1, height, width, 3])
        np.save(np_file_path, video)
    elif media_type == 'voice':
        data, samplerate = sf.read(file_path)
        np.save(np_file_path, data)
    else:
        raise HTTPException(status_code=400, detail="Unsupported media type")
    
    os.remove(file_path)
    
    bot_message = f"User sent a {media_type}. It has been saved as {np_filename}."
    response = chatbots[chat_id](bot_message)
    
    return {"filename": np_filename, "response": response}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)