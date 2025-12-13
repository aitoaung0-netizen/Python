import os
import logging
import requests
import re
import time
import io
import random
import sqlite3
import json
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import google.generativeai as genai
from gtts import gTTS
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from datetime import datetime

# --- SAFE CREATION TOOLS ---
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

# --- 1. WEB SERVER (Render Keep-Alive) ---
app = Flask('')
@app.route('/')
def home(): return "🤖 FINAL BOT IS RUNNING!"
def run_http(): app.run(host='0.0.0.0', port=8080)
def keep_alive():
    t = Thread(target=run_http)
    t.start()

# --- 2. CONFIGS (HARDCODED) ---

# Boss ပေးထားတဲ့ Token (Code ထဲမှာ တိုက်ရိုက်ထည့်ထားပါသည်)
TELEGRAM_TOKEN = "7778399973:AAFSMO3iMBhxb0CG6OOd09lJ7AgBH6CqT_o"

# Boss ပေးထားတဲ့ Admin ID
ADMIN_ID = 6780671216

# ကျန်တဲ့ Key တွေကိုတော့ Environment ထဲက ယူပါမယ် (Render မှာ ထည့်ထားဖို့ လိုပါတယ်)
GOOGLE_CX_ID = os.getenv("GOOGLE_CX_ID")
GEMINI_KEYS = os.getenv("GEMINI_API_KEYS").split(',') if os.getenv("GEMINI_API_KEYS") else []
SEARCH_KEYS = os.getenv("GOOGLE_SEARCH_API_KEYS").split(',') if os.getenv("GOOGLE_SEARCH_API_KEYS") else []

# --- 3. DATABASE (MEMORY) ---
conn = sqlite3.connect('bot_memory.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS chat_logs (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)''')
c.execute('''CREATE TABLE IF NOT EXISTS media_logs (user_id INTEGER, type TEXT, description TEXT, timestamp DATETIME)''')
conn.commit()

def save_chat(user_id, role, content):
    try:
        c.execute("INSERT INTO chat_logs VALUES (?, ?, ?, ?)", (user_id, role, content, datetime.now()))
        conn.commit()
    except: pass

def save_media(user_id, media_type, description):
    try:
        c.execute("INSERT INTO media_logs VALUES (?, ?, ?, ?)", (user_id, media_type, description, datetime.now()))
        conn.commit()
    except: pass

def get_recent_context(user_id, limit=5):
    try:
        c.execute("SELECT role, content FROM chat_logs WHERE user_id=? ORDER BY timestamp DESC LIMIT ?", (user_id, limit))
        chats = c.fetchall()[::-1]
        c.execute("SELECT type, description FROM media_logs WHERE user_id=? ORDER BY timestamp DESC LIMIT 1", (user_id,))
        media = c.fetchone()
        context_str = ""
        if media: context_str += f"[User previously sent {media[0]}: '{media[1]}']\n"
        for chat in chats: context_str += f"{chat[0]}: {chat[1]}\n"
        return context_str
    except: return ""

# --- 4. HELPER FUNCTIONS ---
def get_random_key(keys): return random.choice(keys).strip() if keys else None

def get_model():
    key = get_random_key(GEMINI_KEYS)
    if not key: return None
    genai.configure(api_key=key)
    return genai.GenerativeModel('gemini-1.5-flash')

# --- 5. ADVANCED SEARCH (DIRECT & 18+) ---
def google_search_direct(query, is_18plus=False):
    key = get_random_key(SEARCH_KEYS)
    if not key: return "Search Key Error (Check Render Environment)"

    try:
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            'key': key,
            'cx': GOOGLE_CX_ID,
            'q': query,
            'num': 7,
            'safe': 'off' # SafeSearch OFF for 18+
        }

        # Telegram Channel Specific Search
        is_channel_search = any(x in query.lower() for x in ["channel", "telegram", "group", "ချန်နယ်", "ဂရု"])
        if is_channel_search:
            params['q'] += " site:t.me"

        data = requests.get(url, params=params).json()

        results = ""
        found_links = 0

        if 'items' in data:
            for item in data['items']:
                link = item['link']
                title = item['title']
                snippet = item['snippet']

                if is_channel_search:
                    if "t.me/" in link:
                        # Clean /s/ for direct join
                        direct_link = link.replace("/s/", "/")
                        results += f"🔗 **{title}**\nDirect Link: {direct_link}\n\n"
                        found_links += 1

                elif is_18plus:
                    # Filter for video content pages
                    if any(x in snippet.lower() + title.lower() for x in ['video', 'watch', 'full', 'streaming', 'porn', 'sex', 'x', 'clips']):
                        results += f"🔞 **{title}**\nLink: {link}\n\n"
                        found_links += 1

                else:
                    results += f"- [{title}]({link}): {snippet}\n"
                    found_links += 1

        if found_links == 0: return "No direct links found."
        return results

    except Exception as e: return f"Search Error: {str(e)}"

# --- 6. TOOLS ---
def create_graph(expression):
    try:
        if len(expression) > 30 or "import" in expression: return None
        x = range(-10, 11)
        y = [eval(expression.replace('x', str(i)), {"__builtins__": {}}, {}) for i in x]
        plt.figure(figsize=(6, 4))
        plt.plot(x, y, marker='o', color='red')
        plt.grid(True)
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()
        return buf
    except: return None

def create_qrcode(data):
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill='black', back_color='white').save(buf)
    buf.seek(0)
    return buf

def create_pdf(text):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    textobject = c.beginText(40, 750)
    lines = text[:5000].split('\n')
    for line in lines: textobject.textLine(line[:90])
    c.drawText(textobject)
    c.showPage()
    c.save()
    buf.seek(0)
    return buf

# --- 7. HANDLERS ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "☢️ **FINAL BOT ONLINE** ☢️\n\n"
    msg += "🆔 **Admin ID:** Confirmed\n"
    msg += "🔗 **Search:** Direct Links & 18+ Enabled\n"
    msg += "🧠 **Memory:** Active\n"
    msg += "🛠️ **Tools:** Graph, QR, PDF\n"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_text = update.message.text

    # Debug Print to Console
    print(f"📩 Recieved: {user_text if user_text else 'Media File'}")

    # --- A. MEDIA HANDLING ---
    if update.message.photo or update.message.voice or update.message.audio:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        if update.message.photo:
            file = await update.message.photo[-1].get_file()
            fname = f"media_{user_id}.jpg"
            m_type = "Image"
        else:
            file = await update.message.voice.get_file() if update.message.voice else await update.message.audio.get_file()
            fname = f"media_{user_id}.ogg"
            m_type = "Audio"

        await file.download_to_drive(fname)

        model = get_model()
        if model:
            try:
                up_file = genai.upload_file(fname)
                while up_file.state.name == "PROCESSING": time.sleep(1)

                # DB Save
                desc = model.generate_content(["Describe detailedly in English for database.", up_file]).text
                save_media(user_id, m_type, desc)

                # Reply
                reply = model.generate_content(["Reply in Burmese.", up_file]).text

                if m_type == "Audio":
                    try:
                        tts = gTTS(text=reply, lang='my')
                        tts.save("tts.ogg")
                        await context.bot.send_voice(chat_id=chat_id, voice=open("tts.ogg", "rb"))
                        os.remove("tts.ogg")
                    except: await context.bot.send_message(chat_id=chat_id, text=reply)
                else:
                    await context.bot.send_message(chat_id=chat_id, text=reply)

            except Exception as e:
                print(f"Media Error: {e}")
                await context.bot.send_message(chat_id=chat_id, text="Media Error.")

        if os.path.exists(fname): os.remove(fname)
        return

    # --- B. TEXT & TOOLS ---
    if not user_text: return
    save_chat(user_id, "User", user_text)

    txt_lower = user_text.lower()

    # Tools
    if txt_lower.startswith("graph "):
        buf = create_graph(user_text[6:])
        if buf: await context.bot.send_photo(chat_id=chat_id, photo=buf)
        return
    if txt_lower.startswith("qr "):
        buf = create_qrcode(user_text[3:])
        await context.bot.send_photo(chat_id=chat_id, photo=buf)
        return
    if txt_lower.startswith("pdf "):
        buf = create_pdf(user_text[4:])
        await context.bot.send_document(chat_id=chat_id, document=buf, filename="doc.pdf")
        return

    # Admin Broadcast
    if txt_lower.startswith("/broadcast") and user_id == ADMIN_ID:
        # Simple Broadcast logic for now
        await context.bot.send_message(chat_id=chat_id, text="Admin Broadcast Sent (Simulation).")
        return

    # Search
    search_res = ""
    is_search = any(x in txt_lower for x in ["ရှာ", "search", "link", "channel", "video", "ကား", "news"])

    if is_search:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        is_adult = any(x in txt_lower for x in ["sex", "porn", "18+", "လိုး", "အော", "စောက်"])
        search_res = google_search_direct(user_text, is_18plus=is_adult)

    # Context & Reply
    history = get_recent_context(user_id)
    model = get_model()
    if model:
        prompt = f"""
        User Memory:
        {history}

        Search Results (Direct Links):
        {search_res}

        Query: "{user_text}"

        Instructions:
        1. If Search Results exist, show them EXACTLY (Do not change t.me links).
        2. If news, summarize.
        3. If asking about past media, check User Memory.
        4. Answer in Burmese.
        """
        try:
            response = model.generate_content(prompt)
            reply = response.text
            save_chat(user_id, "Bot", reply)
            await context.bot.send_message(chat_id=chat_id, text=reply, parse_mode=ParseMode.MARKDOWN)
        except:
            await context.bot.send_message(chat_id=chat_id, text="Busy.")

if __name__ == '__main__':
    keep_alive()
    if not TELEGRAM_TOKEN:
        print("ERROR: Token is missing!")
    else:
        print(f"Bot starting with Token: {TELEGRAM_TOKEN[:10]}...")
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler('start', start))
        app.add_handler(MessageHandler(filters.ALL, handle_message))

        # Webhook အဟောင်းတွေ ပိတ်မိနေရင် ရှင်းထုတ်ဖို့
        print("Polling started...")
        app.run_polling(drop_pending_updates=True)