import os
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext
from telegram.constants import ParseMode
from llm_chatbot import chatbot, utils, function_tools
import re
from secret_keys import TELEGRAM_BOT_TOKEN, POSTGRES_DB_PASSWORD
from prompts import SYS_PROMPT, TOOLS_PROMPT_SNIPPET, RESPONSE_FLOW_2
from nltk.tokenize import sent_tokenize
import xml.etree.ElementTree as ET
import hashlib
from uuid import uuid4
from PIL import Image
import numpy as np
import soundfile as sf
import ffmpeg

# Initialize the ChatBot
tools_prompt = TOOLS_PROMPT_SNIPPET.format(TOOL_LIST=function_tools.get_tool_list_prompt(function_tools.get_tools()))
chatbot_system_msg = SYS_PROMPT.format(TOOLS_PROMPT=tools_prompt, RESPONSE_FLOW=RESPONSE_FLOW_2)

# llm_bot = chatbot.ChatBot(model="meta-llama/Meta-Llama-3.1-8B-Instruct", system=chatbot_system_msg)
# llm_bot = chatbot.ChatBot(
#     model="meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", 
#     tokenizer_model="meta-llama/Meta-Llama-3.1-70B-Instruct",
#     system=chatbot_system_msg)
db_config = {    
    "dbname":"chatbot_db",
    "user":"chatbot_user",
    "password":POSTGRES_DB_PASSWORD,
    "host":"localhost",
    "port":"5432"
}
MEDIA_FOLDER = "/media" 
# Ensure the media folder exists
os.makedirs(MEDIA_FOLDER, exist_ok=True)
active_sessions = {}

def get_session(user_id):
    session = active_sessions.get(user_id, None)
    if session is None:
        session_id = str(uuid4())
        active_sessions[user_id] = {
            "chat_id": session_id,
            "llm_bot": chatbot.ChatBot(
                model="qwen/qwen-2.5-72b-instruct", 
                chat_id=session_id,
                tokenizer_model="Qwen/Qwen2.5-72B-Instruct",
                system=chatbot_system_msg,
                db_config=db_config
            ),
        }
        session = active_sessions[user_id]
    return session

def split_message(message, limit=4096):
    # Check if the message contains code blocks
    code_blocks = re.findall(r'```[\s\S]*?```', message)
    
    if code_blocks:
        # If there are code blocks, split around them
        parts = re.split(r'(```[\s\S]*?```)', message)
        result = []
        current_part = ""
        
        for part in parts:
            if part.startswith('```') and part.endswith('```'):
                # This is a code block
                if len(current_part) + len(part) > limit:
                    if current_part:
                        result.append(current_part.strip())
                    if len(part) < 4096:
                        result.append(part)
                    else:
                        result.extend([part[i:i + 4096] for i in range(0, len(part), 4096)])
                    current_part = ""
                else:
                    current_part += part
            else:
                # This is regular text, split by sentences
                if len(current_part) + len(part) < limit:
                    current_part += part + " "
                else:
                    sentences = sent_tokenize(part)
                    for sentence in sentences:
                        if len(current_part) + len(sentence) > limit:
                            result.append(current_part.strip())
                            current_part = sentence + " "
                        else:
                            current_part += sentence + " "
        
        if current_part:
            result.append(current_part.strip())
        
        return result
    else:
        # If no code blocks, just split by sentences
        sentences = sent_tokenize(message)
        result = []
        current_part = ""
        
        for sentence in sentences:
            if len(current_part) + len(sentence) > limit:
                result.append(current_part.strip())
                current_part = sentence + " "
            else:
                current_part += sentence + " "
        
        if current_part:
            result.append(current_part.strip())
        
        return result

async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text('Hi there! I am your AI assistant. How can I help you today?')

async def new_conversation(update: Update, context: CallbackContext) -> None:
    user_id = hashlib.md5(f"{update.message.from_user.full_name}_{update.message.from_user.id}".encode()).hexdigest()
    # clear session if there was one
    active_sessions.pop(user_id, None)
    # make new session
    session = get_session(user_id)
    llm_bot = session["llm_bot"]

    llm_bot.messages = []
    llm_bot.messages_token_counts = []
    llm_bot.total_messages_tokens = 0

    llm_bot.purged_messages = []
    llm_bot.purged_messages_token_count = []

    await update.message.reply_text("Conversation history has been cleared. Starting a new conversation!")

async def change_system_prompt(update: Update, context: CallbackContext) -> None:
    user_id = hashlib.md5(f"{update.message.from_user.full_name}_{update.message.from_user.id}".encode()).hexdigest()
    session = get_session(user_id)
    llm_bot = session["llm_bot"]

    new_system_prompt = ' '.join(context.args)
    llm_bot.system = {"role": "system", "content": llm_bot.system}
    await update.message.reply_text(f"System prompt has been updated to: '{new_system_prompt}'")

async def get_system_prompt(update: Update, context: CallbackContext) -> None:
    user_id = hashlib.md5(f"{update.message.from_user.full_name}_{update.message.from_user.id}".encode()).hexdigest()
    session = get_session(user_id)
    llm_bot = session["llm_bot"]

    await update.message.reply_text(f"System prompt:\n{llm_bot.system['content']}")

async def process_media(file, user_id, media_type):
    # Generate a unique filename
    file_extension = os.path.splitext(file.file_path)[1]
    filename = f"{user_id}_{uuid4()}{file_extension}"
    file_path = os.path.join(MEDIA_FOLDER, filename)

    # Download the file
    await file.download_to_drive(file_path)

    np_filename = os.path.splitext(filename)[0] + ".npy"
    np_file_path = os.path.join(MEDIA_FOLDER, np_filename)

    if media_type == 'photo':
        with Image.open(file_path) as img:
            np_image = np.array(img)
        np.save(np_file_path, np_image)
    elif media_type == 'video':
        probe = ffmpeg.probe(file_path)
        video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        width = int(video_info['width'])
        height = int(video_info['height'])

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

    # Remove the original file
    os.remove(file_path)

    return np_filename

async def handle_message_with_media(update: Update, context: CallbackContext, media_type: str) -> None:
    user_id = hashlib.md5(f"{update.message.from_user.full_name}_{update.message.from_user.id}".encode()).hexdigest()
    session = get_session(user_id)
    llm_bot = session["llm_bot"]

    if media_type == 'photo':
        file = await update.message.photo[-1].get_file()
    elif media_type == 'video':
        file = await update.message.video.get_file()
    elif media_type == 'voice':
        file = await update.message.voice.get_file()
    else:
        await update.message.reply_text("Unsupported media type.")
        return

    np_filename = await process_media(file, user_id, media_type)

    caption = update.message.caption or ""
    
    # Prepare the message for the chatbot
    bot_message = f"User sent a {media_type}. It has been saved as {np_filename}. "
    if caption:
        bot_message += f"The user also included this caption: '{caption}'"

    response = llm_bot(bot_message)
    
    reply_message = f"{media_type.capitalize()} received and saved as {np_filename}. "
    if caption:
        reply_message += f"Caption: '{caption}'\n\n"
    reply_message += response

    await update.message.reply_text(reply_message)

async def handle_photo(update: Update, context: CallbackContext) -> None:
    await handle_message_with_media(update, context, 'photo')

async def handle_video(update: Update, context: CallbackContext) -> None:
    await handle_message_with_media(update, context, 'video')

async def handle_voice(update: Update, context: CallbackContext) -> None:
    await handle_message_with_media(update, context, 'voice')

async def handle_text(update: Update, context: CallbackContext) -> None:
    user_id = hashlib.md5(f"{update.message.from_user.full_name}_{update.message.from_user.id}".encode()).hexdigest()
    session = get_session(user_id)
    llm_bot = session["llm_bot"]

    user_message = update.message.text
    response = llm_bot(user_message)
    response = utils.sanitize_inner_content(response)
    root = ET.fromstring(f"<root>{response}</root>")
    
    # Extract text from <response_to_user> tag
    user_response = root.find('.//response_to_user')
    response = user_response.text.strip() if user_response is not None else ""

    # Split the response if it's too long
    if len(response) > 4096:  # Telegram message limit
        parts = split_message(response)
        for part in parts:
            await update.message.reply_text(part)
    else:
        try:
            await update.message.reply_text(response)
        except Exception as e:
            print(e)

def main():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new_convo", new_conversation))
    application.add_handler(CommandHandler("set_system_msg", change_system_prompt))
    application.add_handler(CommandHandler("system_msg", get_system_prompt))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    application.run_polling()

if __name__ == '__main__':
    main()