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

# --- 1. WEB SERVER & CONFIGS ---
app = Flask('')
@app.route('/')
def home(): return "🤖 MEMORY BOT ONLINE!"
def run_http(): app.run(host='0.0.0.0', port=8080)
def keep_alive():
    t = Thread(target=run_http)
    t.start()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_CX_ID = os.getenv("GOOGLE_CX_ID")
GEMINI_KEYS = os.getenv("GEMINI_API_KEYS").split(',') if os.getenv("GEMINI_API_KEYS") else []
SEARCH_KEYS = os.getenv("GOOGLE_SEARCH_API_KEYS").split(',') if os.getenv("GOOGLE_SEARCH_API_KEYS") else []
ADMIN_ID = 6780671216  # <--- Change this to your ID

# --- 2. DATABASE SETUP (Long Term Memory) ---
# Replit/Render မှာ ဖိုင်တွေက Restart ချရင် ပျောက်တတ်လို့
# SQLite ကို သုံးပြီး စနစ်တကျ သိမ်းပါမယ်။
conn = sqlite3.connect('bot_memory.db', check_same_thread=False)
c = conn.cursor()

# ဇယားများ တည်ဆောက်ခြင်း
# ૧။ Chat History (စကားပြော မှတ်တမ်း)
c.execute('''CREATE TABLE IF NOT EXISTS chat_logs 
             (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)''')

# ၂။ Media Context (ပုံ/ဗီဒီယို မှတ်တမ်း) - ပုံပို့ပြီး ကြာမှ ပြန်မေးရင် သိအောင်
c.execute('''CREATE TABLE IF NOT EXISTS media_logs 
             (user_id INTEGER, type TEXT, description TEXT, timestamp DATETIME)''')
conn.commit()

def save_chat(user_id, role, content):
    c.execute("INSERT INTO chat_logs VALUES (?, ?, ?, ?)", (user_id, role, content, datetime.now()))
    conn.commit()

def save_media(user_id, media_type, description):
    c.execute("INSERT INTO media_logs VALUES (?, ?, ?, ?)", (user_id, media_type, description, datetime.now()))
    conn.commit()

def get_recent_context(user_id, limit=5):
    # နောက်ဆုံး ပြောခဲ့တဲ့ စကား ၅ ခွန်း
    c.execute("SELECT role, content FROM chat_logs WHERE user_id=? ORDER BY timestamp DESC LIMIT ?", (user_id, limit))
    chats = c.fetchall()[::-1] # Reverse to chronological

    # နောက်ဆုံး ပို့ခဲ့တဲ့ ပုံ/မီဒီယို အကြောင်းအရာ ၁ ခု (ကြာနေလည်း ပြန်ပါလာမယ်)
    c.execute("SELECT type, description FROM media_logs WHERE user_id=? ORDER BY timestamp DESC LIMIT 1", (user_id,))
    media = c.fetchone()

    context_str = ""
    if media:
        context_str += f"[System Note: User previously sent a {media[0]} described as: '{media[1]}']\n"

    for chat in chats:
        context_str += f"{chat[0]}: {chat[1]}\n"

    return context_str

# --- 3. HELPER FUNCTIONS ---
def get_random_key(keys): return random.choice(keys).strip() if keys else None

def get_model():
    key = get_random_key(GEMINI_KEYS)
    if not key: return None
    genai.configure(api_key=key)
    return genai.GenerativeModel('gemini-2.5-flash')

# --- 4. ADVANCED SEARCH (UNRESTRICTED) ---
def google_search_unrestricted(query, is_18plus=False):
    key = get_random_key(SEARCH_KEYS)
    if not key: return "Search Key Error"

    try:
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            'key': key,
            'cx': GOOGLE_CX_ID,
            'q': query,
            'num': 5, # ရလဒ် ၅ ခု ရှာမယ်
            'safe': 'off' # 🔥 SAFE MODE OFF (18+ ရှာလို့ရအောင်)
        }

        # Channel ရှာခိုင်းရင် t.me ပါမှ ယူမယ်
        if "channel" in query.lower() or "telegram" in query.lower():
            params['q'] += " site:t.me" # Telegram Link သီးသန့်ရှာမယ်

        data = requests.get(url, params=params).json()

        results = ""
        if 'items' in data:
            for item in data['items']:
                title = item['title']
                link = item['link']
                snippet = item['snippet']

                # 18+ စစ်ဆေးခြင်း (User လိုချင်တဲ့ Keyword ပါမှ Active ဖြစ်မယ်)
                if is_18plus:
                    # Video ပါနိုင်ခြေရှိတဲ့ စကားလုံးတွေပါမှ ရွေးမယ်
                    if any(x in snippet.lower() or x in title.lower() for x in ['video', 'clip', 'full', 'vids', 'watch']):
                        results += f"🔞 [Channel]: {link}\nInfo: {snippet}\n\n"
                else:
                    results += f"- [{title}]({link}): {snippet}\n"

            return results if results else "သက်ဆိုင်ရာ Channel ရှာမတွေ့ပါ Boss။"

        return "No results found."
    except Exception as e: return f"Search Error: {str(e)}"

# --- 5. TOOLS (Graph, QR, PDF, Weather) ---
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

# --- 6. HANDLERS ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "😈 **ULTIMATE UNRESTRICTED BOT** 😈\n\n"
    msg += "✅ **Memory:** ပုံပို့ထားရင် နောက်မှပြန်မေးလည်း သိတယ်။\n"
    msg += "✅ **Search:** Safe Mode Off ထားတယ်။ 18+ ရှာလို့ရတယ်။\n"
    msg += "✅ **Channels:** Telegram Link အစစ်တွေပဲ ရှာပေးမယ်။\n"
    msg += "✅ **Tools:** QR, PDF, Graph, Weather အကုန်ရ။\n"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_text = update.message.text

    # --- A. MEDIA HANDLING (ပုံ/အသံ ရောက်ရင် DB ထဲ အရင်သိမ်းမယ်) ---
    if update.message.photo or update.message.voice or update.message.audio:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # File Download
        if update.message.photo:
            file = await update.message.photo[-1].get_file()
            fname = f"media_{user_id}.jpg"
            m_type = "Image"
        else:
            file = await update.message.voice.get_file() if update.message.voice else await update.message.audio.get_file()
            fname = f"media_{user_id}.ogg"
            m_type = "Audio"

        await file.download_to_drive(fname)

        # Gemini Vision/Audio Analysis
        model = get_model()
        if model:
            try:
                uploaded_file = genai.upload_file(fname)
                while uploaded_file.state.name == "PROCESSING": time.sleep(1)

                # AI ကို ဒီဖိုင်အကြောင်း မှတ်တမ်းတင်ခိုင်းမယ်
                analysis = model.generate_content(["Describe this detailedly in English for future reference.", uploaded_file]).text

                # Database ထဲမှာ မှတ်ဉာဏ်သိမ်းမယ်
                save_media(user_id, m_type, analysis)

                # User ကို ချက်ချင်းပြန်ဖြေမယ်
                reply_prompt = "Reply to this media in Burmese naturally."
                reply = model.generate_content([reply_prompt, uploaded_file]).text

                # အသံဖိုင်ဆိုရင် အသံနဲ့ပြန်မယ်
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
                await context.bot.send_message(chat_id=chat_id, text=f"Media Error: {e}")

        if os.path.exists(fname): os.remove(fname)
        return

    # --- B. TEXT & TOOLS HANDLING ---
    if not user_text: return
    save_chat(user_id, "User", user_text) # Chat Log သိမ်းမယ်

    # 1. Tools Check
    txt_lower = user_text.lower()
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

    # 2. Search Logic (18+ & Channels)
    search_result = ""
    is_search_needed = any(x in txt_lower for x in ["ရှာ", "search", "link", "channel", "video", "ကား", "news"])

    if is_search_needed:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # 18+ Keywords Check
        is_adult = any(x in txt_lower for x in ["sex", "porn", "18+", "လိုး", "အော", "စောက်"])
        search_result = google_search_unrestricted(user_text, is_18plus=is_adult)

    # 3. AI Generation with Memory
    # အရင်မှတ်ဉာဏ် (ပုံ/စာ) တွေကို ပြန်ခေါ်မယ်
    history_context = get_recent_context(user_id)

    model = get_model()
    if model:
        prompt = f"""
        System Context: You are a helpful assistant.
        User's Memory & Context:
        {history_context}

        Search Results (if any):
        {search_result}

        User Query: "{user_text}"

        Instructions:
        1. If showing news, summarize it (Do not just show links).
        2. If providing Telegram channels, ensure links start with 't.me/'.
        3. If 18+ content is requested, provide the found links directly.
        4. If user asks about a previous photo/media, use the 'User's Memory' section to answer (e.g., "That movie was X").
        5. Answer in Burmese.
        """
        try:
            response = model.generate_content(prompt)
            reply_text = response.text
            save_chat(user_id, "Bot", reply_text) # Bot အဖြေကိုလည်း မှတ်ထားမယ်
            await context.bot.send_message(chat_id=chat_id, text=reply_text, parse_mode=ParseMode.MARKDOWN)
        except:
            await context.bot.send_message(chat_id=chat_id, text="System Busy.")

if __name__ == '__main__':
    keep_alive()
    if not TELEGRAM_TOKEN: print("Token Missing")
    else:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler('start', start))
        app.add_handler(MessageHandler(filters.ALL, handle_message))
        print("MEMORY + UNRESTRICTED BOT RUNNING...")
        app.run_polling()