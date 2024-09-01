from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext
from telegram.constants import ParseMode
from llm_chatbot import chatbot, utils, function_tools
import re
from secret_keys import TELEGRAM_BOT_TOKEN
from prompts import SYS_PROMPT
from nltk.tokenize import sent_tokenize
import xml.etree.ElementTree as ET

# Initialize the ChatBot
chatbot_system_msg = SYS_PROMPT

# llm_bot = chatbot.ChatBot(model="meta-llama/Meta-Llama-3.1-8B-Instruct", system=chatbot_system_msg)
llm_bot = chatbot.ChatBot(
    model="meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", 
    tokenizer_model="meta-llama/Meta-Llama-3.1-70B-Instruct",
    system=chatbot_system_msg)

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
                    result.append(part)
                    current_part = ""
                else:
                    current_part += part
            else:
                # This is regular text, split by sentences
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
    llm_bot.messages = []
    llm_bot.messages_token_counts = []
    llm_bot.total_messages_tokens = 0

    llm_bot.purged_messages = []
    llm_bot.purged_messages_token_count = []

    await update.message.reply_text("Conversation history has been cleared. Starting a new conversation!")

async def change_system_prompt(update: Update, context: CallbackContext) -> None:
    new_system_prompt = ' '.join(context.args)
    llm_bot.system = {"role": "system", "content": llm_bot.system}
    await update.message.reply_text(f"System prompt has been updated to: '{new_system_prompt}'")

async def get_system_prompt(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(f"System prompt:\n{llm_bot.system['content']}")

async def handle_message(update: Update, context: CallbackContext) -> None:
    user_message = update.message.text
    response = llm_bot(user_message)
    response = utils.sanitize_inner_content(response)
    root = ET.fromstring(f"<root>{response}</root>")
    
    # Extract text from <user_response> tag
    user_response = root.find('.//user_response')
    response = user_response.text.strip() if user_response is not None else ""

    # Split the response if it's too long
    if len(response) > 4096:  # Telegram message limit
        parts = split_message(response)
        for part in parts:
            await update.message.reply_text(part, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)

def main():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new_convo", new_conversation))
    application.add_handler(CommandHandler("set_system_msg", change_system_prompt))
    application.add_handler(CommandHandler("system_msg", get_system_prompt))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    application.run_polling()

if __name__ == '__main__':
    main()
