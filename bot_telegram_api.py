import os
import hashlib
from uuid import uuid4
import requests
import asyncio
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext
from telegram.constants import ParseMode
import re
from secret_keys import TELEGRAM_BOT_TOKEN
from nltk.tokenize import sent_tokenize

API_BASE_URL = "http://localhost:8000"  # Adjust this to your API's address
MEDIA_FOLDER = "/media"
os.makedirs(MEDIA_FOLDER, exist_ok=True)

active_sessions = {}

def get_session(user_id):
    session = active_sessions.get(user_id)
    if session is None:
        response = requests.post(f"{API_BASE_URL}/chat", json={
            "model": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
            "tokenizer_model": "meta-llama/Meta-Llama-3.1-70B-Instruct"
        })
        if response.status_code == 200:
            session_data = response.json()
            active_sessions[user_id] = {"chat_id": session_data["chat_id"]}
            session = active_sessions[user_id]
        else:
            raise Exception("Failed to create a new chat session")
    return session

def split_message(message, limit=4096):
    code_blocks = re.findall(r'```[\s\S]*?```', message)
    
    if code_blocks:
        parts = re.split(r'(```[\s\S]*?```)', message)
        result = []
        current_part = ""
        
        for part in parts:
            if part.startswith('```') and part.endswith('```'):
                if len(current_part) + len(part) > limit:
                    if current_part:
                        result.append(current_part.strip())
                    result.append(part)
                    current_part = ""
                else:
                    current_part += part
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
    active_sessions.pop(user_id, None)
    session = get_session(user_id)
    await update.message.reply_text("Conversation history has been cleared. Starting a new conversation!")

async def change_system_prompt(update: Update, context: CallbackContext) -> None:
    user_id = hashlib.md5(f"{update.message.from_user.full_name}_{update.message.from_user.id}".encode()).hexdigest()
    session = get_session(user_id)
    new_system_prompt = ' '.join(context.args)
    
    response = requests.put(f"{API_BASE_URL}/chat/{session['chat_id']}/system", json={"system_message": new_system_prompt})
    if response.status_code == 200:
        await update.message.reply_text(f"System prompt has been updated to: '{new_system_prompt}'")
    else:
        await update.message.reply_text("Failed to update system prompt.")

async def get_system_prompt(update: Update, context: CallbackContext) -> None:
    user_id = hashlib.md5(f"{update.message.from_user.full_name}_{update.message.from_user.id}".encode()).hexdigest()
    session = get_session(user_id)
    
    response = requests.get(f"{API_BASE_URL}/chat/{session['chat_id']}/system")
    if response.status_code == 200:
        system_message = response.json()["system_message"]
        await update.message.reply_text(f"System prompt:\n{system_message}")
    else:
        await update.message.reply_text("Failed to retrieve system prompt.")

async def handle_message_with_media(update: Update, context: CallbackContext, media_type: str) -> None:
    user_id = hashlib.md5(f"{update.message.from_user.full_name}_{update.message.from_user.id}".encode()).hexdigest()
    session = get_session(user_id)

    if media_type == 'photo':
        file = await update.message.photo[-1].get_file()
    elif media_type == 'video':
        file = await update.message.video.get_file()
    elif media_type == 'voice':
        file = await update.message.voice.get_file()
    else:
        await update.message.reply_text("Unsupported media type.")
        return

    file_path = await file.download_to_drive()
    
    with open(file_path, 'rb') as f:
        files = {'file': f}
        response = requests.post(f"{API_BASE_URL}/chat/{session['chat_id']}/media", 
                                 files=files, 
                                 data={'media_type': media_type})
    
    os.remove(file_path)  # Remove the temporary file
    
    if response.status_code == 200:
        result = response.json()
        np_filename = result['filename']
        bot_response = result['response']
        
        caption = update.message.caption or ""
        reply_message = f"{media_type.capitalize()} received and saved as {np_filename}. "
        if caption:
            reply_message += f"Caption: '{caption}'\n\n"
        reply_message += bot_response
        
        await update.message.reply_text(reply_message)
    else:
        await update.message.reply_text("Failed to process media.")

async def handle_photo(update: Update, context: CallbackContext) -> None:
    await handle_message_with_media(update, context, 'photo')

async def handle_video(update: Update, context: CallbackContext) -> None:
    await handle_message_with_media(update, context, 'video')

async def handle_voice(update: Update, context: CallbackContext) -> None:
    await handle_message_with_media(update, context, 'voice')

async def handle_text(update: Update, context: CallbackContext) -> None:
    user_id = hashlib.md5(f"{update.message.from_user.full_name}_{update.message.from_user.id}".encode()).hexdigest()
    session = get_session(user_id)

    user_message = update.message.text
    response = requests.post(f"{API_BASE_URL}/chat/{session['chat_id']}/message", json={"content": user_message})
    
    if response.status_code == 200:
        bot_response = response.json()["response"]
        
        if len(bot_response) > 4096:  # Telegram message limit
            parts = split_message(bot_response)
            for part in parts:
                await update.message.reply_text(part)
        else:
            await update.message.reply_text(bot_response)
    else:
        await update.message.reply_text("Failed to get a response from the chatbot.")

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