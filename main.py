import logging
import os
import random
import re
import json
import requests
import io
import time
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from PIL import Image
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from keep_alive import keep_alive

# --- 0. AUTO-UPDATE ---
try:
    import google.generativeai as genai
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "google-generativeai"])
    import google.generativeai as genai

# --- 1. CONFIGURATION ---
GEMINI_KEYS = os.environ.get("GEMINI_API_KEYS", "").split(",")
GOOGLE_SEARCH_KEYS = os.environ.get("GOOGLE_SEARCH_API_KEYS", "").split(",")
GOOGLE_CX_ID = os.environ.get("GOOGLE_CX_ID", "")
BOT_TOKEN = os.environ.get("TELERAM_TOKEN")

MODEL_NAME = "gemini-2.5-flash" 
MEMORY_FILE = "chat_memory.json"
logging.basicConfig(level=logging.INFO)

# Global lists
ACTIVE_GEMINI_KEYS = []
ACTIVE_SEARCH_KEYS = []

# --- 2. KEY VALIDATION ---
def validate_all_keys():
    print("🚀 SYSTEM STARTUP...")
    global ACTIVE_GEMINI_KEYS, ACTIVE_SEARCH_KEYS

    # Simple validation to populate lists
    for key in GEMINI_KEYS:
        if key.strip(): ACTIVE_GEMINI_KEYS.append(key.strip())

    for key in GOOGLE_SEARCH_KEYS:
        if key.strip(): ACTIVE_SEARCH_KEYS.append(key.strip())

    print(f"✅ Gemini Keys: {len(ACTIVE_GEMINI_KEYS)}")
    print(f"✅ Search Keys: {len(ACTIVE_SEARCH_KEYS)}")
    return ACTIVE_GEMINI_KEYS, ACTIVE_SEARCH_KEYS

# --- 3. MEMORY SYSTEM ---
def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

def save_memory(data):
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)
    except: pass

user_chat_history = load_memory()

def update_history(user_id, role, text):
    str_id = str(user_id)
    if str_id not in user_chat_history: user_chat_history[str_id] = []
    user_chat_history[str_id].append(f"{role}: {text}")
    if len(user_chat_history[str_id]) > 20: user_chat_history[str_id].pop(0)
    save_memory(user_chat_history)

def get_history_text(user_id):
    str_id = str(user_id)
    return "\n".join(user_chat_history[str_id]) if str_id in user_chat_history else ""

# --- 4. HELPER FUNCTIONS ---
def get_myanmar_time_str():
    utc_now = datetime.now(timezone.utc)
    mm_time = utc_now + timedelta(hours=6, minutes=30)
    return mm_time.strftime("%Y-%m-%d %I:%M %p")

def get_gemini_content(content_input):
    if not ACTIVE_GEMINI_KEYS: return None
    shuffled_keys = ACTIVE_GEMINI_KEYS.copy()
    random.shuffle(shuffled_keys)

    for key in shuffled_keys:
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel(MODEL_NAME)
            response = model.generate_content(content_input)
            return response.text
        except: continue
    return None

def execute_google_search(query, fresh=False, only_telegram=False):
    if not GOOGLE_CX_ID or not ACTIVE_SEARCH_KEYS: return None, []

    shuffled_keys = ACTIVE_SEARCH_KEYS.copy()
    for key in shuffled_keys:
        try:
            url = "https://www.googleapis.com/customsearch/v1"
            params = {'q': query, 'key': key, 'cx': GOOGLE_CX_ID, 'safe': 'off'}
            if fresh: params['dateRestrict'] = 'd1'

            response = requests.get(url, params=params)
            if response.status_code != 200: continue

            res = response.json()
            if 'items' in res:
                text_out = ""
                links = []
                for item in res['items']:
                    title = item['title']
                    link = item['link']
                    snippet = item.get('snippet', '')

                    # 🔥 CRITICAL FIX: Python-Side Link Filtering
                    if only_telegram:
                        # If link doesn't contain t.me, SKIP IT.
                        if "t.me" not in link: continue

                        # Clean Link (/s/ removal)
                        link = link.replace("/s/", "/")

                        # Filter junk titles
                        if "Telegram: Contact" in title and len(snippet) < 10: continue

                    text_out += f"TITLE: {title}\nLINK: {link}\nDETAILS: {snippet}\n\n"
                    links.append({"title": title, "link": link})

                # If filtering resulted in empty list, return empty
                if only_telegram and not links: return "", []

                return text_out, links
        except: continue
    return "", []

def tool_image_gen(prompt):
    return f"https://image.pollinations.ai/prompt/{prompt}"

def expand_query(text):
    text = text.lower()
    if "btth" in text: text = text.replace("btth", "Battle Through The Heavens")
    if re.search(r'\b(mms|mmsub)\b', text): 
        text = text.replace("mms", "Myanmar Subtitle").replace("mmsub", "Myanmar Subtitle")
    return text

# --- 5. MAIN LOGIC ---
async def gemini_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # VISION
    if update.message.photo:
        await update.message.reply_chat_action("typing")
        user_text = update.message.caption if update.message.caption else "Analyze this"
        try:
            photo_file = await update.message.photo[-1].get_file()
            photo_bytes = await photo_file.download_as_bytearray()
            img_data = Image.open(io.BytesIO(photo_bytes))

            vision_prompt = f"User: {user_text}. Task: Identify movie/character OR read receipt. Reply in Burmese list."
            response = get_gemini_content([vision_prompt, img_data])

            if response:
                update_history(user_id, "User", f"[IMAGE] {user_text}")
                update_history(user_id, "Bot", f"[IMAGE INFO] {response}")
                await update.message.reply_text(response, parse_mode='Markdown')
            else: await update.message.reply_text("❌ Vision Error.")
        except: await update.message.reply_text("❌ Error processing image.")
        return

    # TEXT
    user_text = update.message.text
    if not user_text: return

    await update.message.reply_chat_action("typing")
    previous_chat = get_history_text(user_id)
    expanded_text = expand_query(user_text)
    current_mm_time = get_myanmar_time_str()

    # SYSTEM PROMPT
    system_prompt = f"""
    You are Gemini AI (Model: {MODEL_NAME}).
    Time: {current_mm_time}
    History: {previous_chat}
    Input: "{expanded_text}"

    RULES:
    1. CHECK_PRICE -> "Price", "Gold", "Dollar".
    2. CHECK_TIME -> "Time", "Date", "Today".
    3. READ_NEWS -> "News".
    4. FIND_LINK -> Movies, Songs, 18+, Downloads.
       * If history has "18+" and user says "mms", assume "18+ MMS".
    5. IMAGE -> Draw.
    6. REPLY -> Chat.

    OUTPUT FORMAT: COMMAND "Query"
    """

    decision = get_gemini_content(system_prompt)
    if not decision: 
        await update.message.reply_text("⚠️ System Busy (Keys Failed)")
        return

    decision_clean = decision.strip().replace('"', '').replace("'", "")
    if decision_clean.startswith("SEARCH"): decision_clean = decision_clean.replace("SEARCH", "FIND_LINK")

    print(f"🧠 Decision: {decision_clean}")

    price_match = re.search(r'CHECK_PRICE\s*[:|]?\s*(.*)', decision_clean, re.IGNORECASE)
    news_match = re.search(r'READ_NEWS\s*[:|]?\s*(.*)', decision_clean, re.IGNORECASE)
    link_match = re.search(r'FIND_LINK\s*[:|]?\s*(.*)', decision_clean, re.IGNORECASE)
    time_match = re.search(r'CHECK_TIME', decision_clean, re.IGNORECASE)
    image_match = re.search(r'IMAGE\s*[:|]?\s*(.*)', decision_clean, re.IGNORECASE)

    # --- EXECUTION ---

    # 🔥 PRICE FIX: Multi-step + No Strict Date
    if price_match:
        query = price_match.group(1).strip()
        await update.message.reply_text(f"📉 ဈေးနှုန်းရှာနေသည်: '{query}'...")

        # 1. Search Broadly
        search_q = "Myanmar gold price market rate today" if "gold" in query.lower() else f"Myanmar {query} market price"
        search_data, _ = execute_google_search(search_q, fresh=False) # Fresh=False ensures we get results even if old

        # 2. Try Specific Source if 1 failed
        if not search_data:
             search_data, _ = execute_google_search("YGEA gold price today update", fresh=False)

        if not search_data:
            await update.message.reply_text("❌ Data မတွေ့ပါ။")
        else:
            # Force Extraction Prompt
            price_prompt = f"""
            Search Results: {search_data}
            Task: Estimate LATEST Myanmar Market Prices.

            INSTRUCTIONS:
            - Scan snippet for numbers like '59', '60' (Lakhs) or '4100', '4200' (MMK).
            - If snippet says 'Yesterday', USE IT as latest.
            - DO NOT say 'Not found'. Make an educated guess based on the text.

            Reply in Burmese List:
            🥇 ရွှေ: ...
            💵 ငွေကြေး: ...
            """
            price_report = get_gemini_content(price_prompt)
            await update.message.reply_text(price_report, parse_mode='Markdown')

    # 🔥 LINK FIX: Strict Python-side Filtering
    elif link_match:
        raw_query = link_match.group(1).strip()

        is_adult = any(x in raw_query.lower() for x in ["18+", "porn", "leak"]) or ("18+" in previous_chat)

        if is_adult:
            final_query = f'site:t.me "{raw_query}" (leak OR viral OR sex OR porn)'
        else:
            final_query = f'site:t.me "{raw_query}" (channel OR chat OR 1080p)'

        await update.message.reply_text(f"🔍 Searching: '{raw_query}'...")

        # Enable 'only_telegram=True' to strip non-telegram links
        search_data, links = execute_google_search(final_query, fresh=False, only_telegram=True)

        if not links:
            # Fallback
            search_data, links = execute_google_search(f'site:t.me {raw_query}', fresh=False, only_telegram=True)

        if not links:
            await update.message.reply_text("❌ Links မတွေ့ပါ။")
        else:
            keyboard = [[InlineKeyboardButton(f"🔗 {item['title'][:30]}", url=item['link'])] for item in links[:6]]
            update_history(user_id, "User", user_text)
            update_history(user_id, "Bot", "Links Sent")
            await update.message.reply_text(f"တွေ့ရှိသော Links:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif news_match:
        query = news_match.group(1).strip()
        await update.message.reply_text(f"📰 Reading News: '{query}'...")
        search_data, _ = execute_google_search(f"Myanmar news {query}", fresh=True)
        if not search_data:
             await update.message.reply_text("❌ No news.")
        else:
             report = get_gemini_content(f"Summarize in Burmese:\n{search_data}")
             await update.message.reply_text(report, parse_mode='Markdown')

    elif time_match:
        mm_time = get_myanmar_time_str()
        await update.message.reply_text(f"📆 {mm_time}")

    elif image_match:
        prompt = image_match.group(1).strip()
        await update.message.reply_text(f"🎨 Generating...")
        await update.message.reply_photo(tool_image_gen(prompt))

    else:
        clean_reply = decision.replace("REPLY", "").replace('|', '').strip()
        if "COMMAND" in clean_reply:
             await update.message.reply_text("⚠️ Processing...")
        else:
            chat_reply = get_gemini_content(f"History: {previous_chat}\nUser: {user_text}\nReply smartly in Burmese.")
            update_history(user_id, "User", user_text)
            update_history(user_id, "Bot", chat_reply)
            await update.message.reply_text(chat_reply, parse_mode='Markdown')

if __name__ == '__main__':
    keep_alive()
    if not BOT_TOKEN:
        print("Error: TOKEN missing")
    else:
        ACTIVE_GEMINI_KEYS, ACTIVE_SEARCH_KEYS = validate_all_keys()

        if not ACTIVE_GEMINI_KEYS:
            print("❌ CRITICAL: No Gemini keys working. Please update Secrets!")
        elif not ACTIVE_SEARCH_KEYS:
            print("⚠️ WARNING: Search keys mostly dead. Search might fail.")

        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, gemini_agent))
        print("Bot Started...")
        app.run_polling()