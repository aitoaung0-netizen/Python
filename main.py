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
from urllib.parse import urlparse

# --- SAFE CREATION TOOLS ---
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

# --- 1. WEB SERVER ---
app = Flask('')
@app.route('/')
def home(): return "🤖 DIRECT LINK BOT ONLINE!"
def run_http(): app.run(host='0.0.0.0', port=8080)
def keep_alive():
    t = Thread(target=run_http)
    t.start()

# --- 2. CONFIGS ---
TELEGRAM_TOKEN = "7778399973:AAFSMO3iMBhxb0CG6OOd09lJ7AgBH6CqT_o"
GOOGLE_CX_ID = os.getenv("GOOGLE_CX_ID")
GEMINI_KEYS = os.getenv("GEMINI_API_KEYS").split(',') if os.getenv("GEMINI_API_KEYS") else []
SEARCH_KEYS = os.getenv("GOOGLE_SEARCH_API_KEYS").split(',') if os.getenv("GOOGLE_SEARCH_API_KEYS") else []
ADMIN_ID = 6780671216  # <--- Change to your ID

# --- 3. DATABASE (MEMORY) ---
conn = sqlite3.connect('bot_memory.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS chat_logs (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)''')
c.execute('''CREATE TABLE IF NOT EXISTS media_logs (user_id INTEGER, type TEXT, description TEXT, timestamp DATETIME)''')
conn.commit()

def save_chat(user_id, role, content):
    c.execute("INSERT INTO chat_logs VALUES (?, ?, ?, ?)", (user_id, role, content, datetime.now()))
    conn.commit()

def save_media(user_id, media_type, description):
    c.execute("INSERT INTO media_logs VALUES (?, ?, ?, ?)", (user_id, media_type, description, datetime.now()))
    conn.commit()

def get_recent_context(user_id, limit=5):
    c.execute("SELECT role, content FROM chat_logs WHERE user_id=? ORDER BY timestamp DESC LIMIT ?", (user_id, limit))
    chats = c.fetchall()[::-1]
    c.execute("SELECT type, description FROM media_logs WHERE user_id=? ORDER BY timestamp DESC LIMIT 1", (user_id,))
    media = c.fetchone()
    context_str = ""
    if media: context_str += f"[User sent {media[0]}: '{media[1]}']\n"
    for chat in chats: context_str += f"{chat[0]}: {chat[1]}\n"
    return context_str

# --- 4. HELPER FUNCTIONS ---
def get_random_key(keys): return random.choice(keys).strip() if keys else None

def get_model():
    key = get_random_key(GEMINI_KEYS)
    if not key: return None
    genai.configure(api_key=key)
    return genai.GenerativeModel('gemini-2.5-flash')

# --- 5. ADVANCED SEARCH (DIRECT LINKS ONLY) ---
def google_search_direct(query, is_18plus=False):
    key = get_random_key(SEARCH_KEYS)
    if not key: return "Search Key Error"

    try:
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            'key': key,
            'cx': GOOGLE_CX_ID,
            'q': query,
            'num': 7, # ပိုရှာမယ်၊ ပြီးမှ စစ်ထုတ်မယ်
            'safe': 'off' # SafeSearch OFF
        }

        # Telegram Channel ရှာချင်ရင် t.me ကို Force လုပ်မယ်
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

                # Filter 1: Telegram Channels
                if is_channel_search:
                    if "t.me/" in link:
                        # /s/ (Preview link) ကို ဖျက်ပြီး Direct Link လုပ်မယ်
                        direct_link = link.replace("/s/", "/")
                        # Post link (t.me/user/123) မဟုတ်ဘဲ Channel link (t.me/user) ကို ဦးစားပေးမယ်
                        results += f"🔗 **{title}**\nDirect Link: {direct_link}\n\n"
                        found_links += 1

                # Filter 2: 18+ Direct Pages
                elif is_18plus:
                    # Video keyword ပါမှ ယူမယ်
                    if any(x in snippet.lower() + title.lower() for x in ['video', 'watch', 'full', 'streaming', 'porn', 'sex']):
                        results += f"🔞 **{title}**\nLink: {link}\n\n"
                        found_links += 1

                # Normal Search
                else:
                    results += f"- [{title}]({link}): {snippet}\n"
                    found_links += 1

        if found_links == 0: return "တိုက်ရိုက် Link ရှာမတွေ့ပါ Boss။"
        return results

    except Exception as e: return f"Error: {str(e)}"

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
    msg = "☢️ **DIRECT LINK BOT ONLINE** ☢️\n\n"
    msg += "🔗 **Channels:** `t.me` Direct Link အစစ်ပဲ ပေးမယ်။\n"
    msg += "🔞 **18+:** Safe Mode ပိတ်ထားတယ်။\n"
    msg += "🧠 **Memory:** ပုံဟောင်း/အသံဟောင်းတွေကို မှတ်မိတယ်။\n"
    msg += "🛠️ **Tools:** QR, Graph, PDF, Weather.\n"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_text = update.message.text

    # --- A. MEDIA LOGGING (DB SAVE) ---
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

                # 1. Analyze for DB (Future Memory)
                desc = model.generate_content(["Describe this detail in English.", up_file]).text
                save_media(user_id, m_type, desc)

                # 2. Reply to User Now
                reply = model.generate_content(["Reply in Burmese naturally.", up_file]).text

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
                await context.bot.send_message(chat_id=chat_id, text=f"Error: {e}")

        if os.path.exists(fname): os.remove(fname)
        return

    # --- B. TEXT & SEARCH ---
    if not user_text: return
    save_chat(user_id, "User", user_text)

    # Check Tools
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

    # Check Search Requirement
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
        User Context & Memory:
        {history}

        Search Results (Direct Links):
        {search_res}

        User Input: "{user_text}"

        Instructions:
        1. If Search Results contain 'Direct Link', output them EXACTLY as shown.
        2. Do NOT change t.me links.
        3. If news, summarize the content (don't just show link).
        4. If answering from memory (about past image), refer to the User Context.
        5. Answer in Burmese.
        """
        try:
            response = model.generate_content(prompt)
            reply = response.text
            save_chat(user_id, "Bot", reply)
            await context.bot.send_message(chat_id=chat_id, text=reply, parse_mode=ParseMode.MARKDOWN)
        except:
            await context.bot.send_message(chat_id=chat_id, text="System Busy.")

if __name__ == '__main__':
    keep_alive()
    if not TELEGRAM_TOKEN: print("Token Missing")
    else:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler('start', start))
        app.add_handler(MessageHandler(filters.ALL, handle_message))
        print("DIRECT LINK BOT RUNNING...")
        app.run_polling()