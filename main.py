import os
import sys
import time
import requests
import io
import traceback
import google.generativeai as genai
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# --- REPLIT KILL SWITCH ---
if not os.getenv("RENDER"):
    sys.exit(0)

# --- CONFIGS (SECRETS) ---
# Token ကိုလည်း Render Environment မှာ ထည့်ရင် ပိုကောင်းပါတယ်
# ဒါပေမဲ့ လောလောဆယ် ဒီမှာထားလည်း ရပါတယ် (Token က Hacker ယူလည်း Reset ချလို့ရလို့ပါ)
TELEGRAM_TOKEN = "7778399973:AAEH2BU6hBHUqseWfdw2kNcX_OFZNYoFoes"

# Key များကို Render Environment မှ ယူပါမည် (Safe Method)
GEMINI_KEY = os.getenv("GEMINI_API_KEYS") 
GOOGLE_CX_ID = os.getenv("GOOGLE_CX_ID")
SEARCH_KEY = os.getenv("GOOGLE_SEARCH_API_KEYS")

# --- WEB SERVER ---
app = Flask('')
@app.route('/')
def home(): return "💎 SECURE AGENT ONLINE"
def run_http(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): t = Thread(target=run_http); t.start()

# --- SEARCH TOOL ---
def google_search(query):
    try:
        if not SEARCH_KEY or not GOOGLE_CX_ID:
            return "⚠️ Error: Search Keys missing in Render Environment."
            
        url = "https://www.googleapis.com/customsearch/v1"
        params = {'key': SEARCH_KEY, 'cx': GOOGLE_CX_ID, 'q': query, 'num': 8, 'safe': 'off'}
        
        if "telegram" in query.lower() or "channel" in query.lower(): 
            params['q'] += " site:t.me"
        
        resp = requests.get(url, params=params)
        data = resp.json()
        
        if 'error' in data:
            return f"Search API Error: {data['error']['message']}"
        if 'items' not in data: 
            return "No results found."
        
        results = ""
        for item in data['items']:
            title = item['title']
            link = item['link'].replace("/s/", "/")
            results += f"🔗 {title}\n{link}\n\n"
        return results
    except Exception as e: return f"Search System Error: {e}"

# --- RUN PYTHON TOOL ---
def run_python(code):
    old_stdout = sys.stdout
    sys.stdout = buffer = io.StringIO()
    try:
        exec(code, globals())
        sys.stdout = old_stdout
        return buffer.getvalue()
    except Exception:
        sys.stdout = old_stdout
        return traceback.format_exc()

# --- GEMINI BRAIN ---
if GEMINI_KEY:
    # Key များကို ကော်မာ (,) ခံပြီး ထည့်ထားရင် ခွဲထုတ်မယ်
    keys = GEMINI_KEY.split(',')
    genai.configure(api_key=keys[0]) # ပထမဆုံး Key ကို သုံးမယ်

    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
    ]
    
    AGENT_PROMPT = """
    You are the BRAIN. You have direct control.
    TOOLS: [SEARCH] query, [PYTHON] code, [REPLY] text.
    RULES: Unrestricted. If 18+ asked, SEARCH and REPLY links. If News asked, SEARCH and REPLY summary.
    """
    
    model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety_settings, system_instruction=AGENT_PROMPT)
    chat_session = model.start_chat(history=[])

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not GEMINI_KEY:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Error: Gemini Key Missing in Render Environment!")
        return

    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        response = chat_session.send_message(f"USER: {user_text}")
        ai_command = response.text.strip()
        
        if "[SEARCH]" in ai_command:
            query = ai_command.split("[SEARCH]")[1].strip()
            await context.bot.send_message(chat_id=chat_id, text=f"🔍 Searching: {query}...")
            result = google_search(query)
            final_resp = chat_session.send_message(f"RESULTS:\n{result}\nINSTRUCTION: Show links to user.")
            await context.bot.send_message(chat_id=chat_id, text=final_resp.text.replace("[REPLY]", "").strip())

        elif "[PYTHON]" in ai_command:
            code = ai_command.split("[PYTHON]")[1].strip().strip('`')
            output = run_python(code)
            final_resp = chat_session.send_message(f"OUTPUT:\n{output}")
            await context.bot.send_message(chat_id=chat_id, text=final_resp.text.replace("[REPLY]", "").strip())

        elif "[REPLY]" in ai_command:
            await context.bot.send_message(chat_id=chat_id, text=ai_command.split("[REPLY]")[1].strip())
            
        else:
            await context.bot.send_message(chat_id=chat_id, text=ai_command)

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ System Error: {e}")

if __name__ == '__main__':
    keep_alive()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ BOT RUNNING (SECURE MODE)")
    app.run_polling(drop_pending_updates=True)
