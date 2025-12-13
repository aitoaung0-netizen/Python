import logging
import os
import random
import re
import json
import requests
import io
from datetime import datetime, timedelta, timezone
from PIL import Image
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from keep_alive import keep_alive

# --- 1. CONFIGURATION ---
GEMINI_KEYS = os.environ.get("GEMINI_API_KEYS", "").split(",")
GOOGLE_SEARCH_KEYS = os.environ.get("GOOGLE_SEARCH_API_KEYS", "").split(",")
GOOGLE_CX_ID = os.environ.get("GOOGLE_CX_ID", "")
BOT_TOKEN = os.environ.get("TELERAM_TOKEN")

MODEL_NAME = "gemini-2.5-flash" 
MEMORY_FILE = "chat_memory.json"
logging.basicConfig(level=logging.INFO)

safety_settings = [
    { "category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE" },
    { "category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE" },
    { "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE" },
    { "category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE" },
]

ACTIVE_GEMINI_KEYS = []
ACTIVE_SEARCH_KEYS = []

# --- 2. KEY VALIDATION (omitted for brevity) ---
def validate_all_keys():
    # ... (Validation logic remains the same) ...
    valid_gemini = []
    for key in GEMINI_KEYS:
        key = key.strip()
        if not key: continue
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel(MODEL_NAME) 
            model.generate_content("Hi") 
            valid_gemini.append(key)
        except: pass

    valid_search = []
    for key in GOOGLE_SEARCH_KEYS:
        key = key.strip()
        if not key: continue
        try:
            url = "https://www.googleapis.com/customsearch/v1"
            params = {'q': 'test', 'key': key, 'cx': GOOGLE_CX_ID}
            res = requests.get(url, params=params)
            if res.status_code == 200: valid_search.append(key)
        except: pass

    print(f"✅ Active Keys: Gemini {len(valid_gemini)} | Search {len(valid_search)}")
    return valid_gemini, valid_search

# --- 3. MEMORY SYSTEM (omitted for brevity) ---
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
            model = genai.GenerativeModel(MODEL_NAME, safety_settings=safety_settings)
            response = model.generate_content(content_input)
            return response.text
        except: continue
    return None

def sanitize_query(query):
    # Sanitize to prevent 400 Bad Request
    return re.sub(r'[^a-zA-Z0-9\s\u1000-\u109F]+', ' ', query).strip()

def execute_google_search(query, fresh=False):
    if not GOOGLE_CX_ID or not ACTIVE_SEARCH_KEYS: return None, []

    sanitized_query = sanitize_query(query)

    shuffled_keys = ACTIVE_SEARCH_KEYS.copy()
    for key in shuffled_keys:
        try:
            url = "https://www.googleapis.com/customsearch/v1"
            params = {'q': sanitized_query, 'key': key, 'cx': GOOGLE_CX_ID, 'safe': 'off'}

            response = requests.get(url, params=params)
            if response.status_code != 200: continue

            res = response.json()
            if 'items' in res:
                text_out = ""
                links = []
                for item in res['items']:
                    title = item['title']
                    link = item['link'].replace("/s/", "/")
                    snippet = item.get('snippet', '')
                    text_out += f"TITLE: {title}\nLINK: {link}\nSNIPPET: {snippet}\n\n"
                    links.append({"title": title, "link": link})
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

    # VISION HANDLER (omitted)
    if update.message.photo:
        # ... (Vision logic omitted for focus) ...
        return

    # TEXT HANDLER
    user_text = update.message.text
    if not user_text: return

    await update.message.reply_chat_action("typing")
    previous_chat = get_history_text(user_id)
    expanded_text = expand_query(user_text)

    # SYSTEM PROMPT
    system_prompt = f"""
    You are Gemini AI (Model: {MODEL_NAME}).
    CRITICAL RULE: FOR PRICE CHECK, ALWAYS ASSUME 'BLACK MARKET' or 'YANGON MARKET' is the user's intent unless specified otherwise.
    History: {previous_chat}
    Input: "{expanded_text}"

    RULES:
    1. CHECK_PRICE -> "Price", "Gold", "Dollar", "ဈေး"
    2. CHECK_TIME -> "Time", "Date", "Today"
    3. READ_NEWS -> "News"
    4. FIND_LINK -> Movies, Songs, 18+, Downloads
    5. IMAGE -> Draw.
    6. REPLY -> Chat.

    OUTPUT FORMAT: COMMAND "Query"
    """

    decision = get_gemini_content(system_prompt)
    if not decision: 
        await update.message.reply_text("⚠️ System Busy (AI unresponsive)")
        return

    # Clean and parse decision
    decision_clean = decision.strip().replace('"', '').replace("'", "")
    if decision_clean.startswith("SEARCH"): decision_clean = decision_clean.replace("SEARCH", "FIND_LINK")

    price_match = re.search(r'CHECK_PRICE\s*[:|]?\s*(.*)', decision_clean, re.IGNORECASE)
    news_match = re.search(r'READ_NEWS\s*[:|]?\s*(.*)', decision_clean, re.IGNORECASE)
    link_match = re.search(r'FIND_LINK\s*[:|]?\s*(.*)', decision_clean, re.IGNORECASE)
    time_match = re.search(r'CHECK_TIME', decision_clean, re.IGNORECASE)

    # --- EXECUTION ---
    if price_match:
        query = price_match.group(1).strip()
        await update.message.reply_text(f"📉 ဈေးနှုန်းရှာနေသည်: '{query}'...")

        # Search is now optimized for speed and market price
        search_q = "Myanmar black market gold and USD exchange rate"
        search_data, _ = execute_google_search(search_q) 

        if not search_data:
            await update.message.reply_text("❌ Data မတွေ့ပါ။")
        else:
            # 🔥 PROMPT REFINEMENT: Direct extraction of market price
            price_prompt = f"""
            Search Results: {search_data}
            Task: Synthesize and list the most recent and relevant Myanmar BLACK MARKET Prices (Gold/USD).
            IGNORE official/old rates. Prioritize specific figures.
            Reply in Burmese Markdown format:
            🥇 **ပြင်ပပေါက်ဈေး (ရွှေ):** ... (e.g., 55 သိန်း 8 သောင်း)
            💵 **ပြင်ပပေါက်ဈေး (USD):** ... (e.g., 4100 MMK)
            """
            price_report = get_gemini_content(price_prompt)
            await update.message.reply_text(price_report, parse_mode='Markdown')

    elif link_match:
        raw_query = link_match.group(1).strip()
        is_adult = any(x in raw_query.lower() for x in ["18+", "porn", "leak"]) or ("18+" in previous_chat)

        if is_adult:
            # 🔥 STRICT LINK FILTERING: Use both t.me and explicit Burmese keywords
            final_query = f'site:t.me "{raw_query}" (leak OR viral OR sex OR အောကား OR အပြာကား OR လိုးကား)'
        else:
            # ALWAYS ensure site:t.me is prepended to avoid intermediate sites
            final_query = f'site:t.me "{raw_query}"'

        await update.message.reply_text(f"🔍 Searching: '{raw_query}'...")

        search_data, links = execute_google_search(final_query, fresh=False)

        if not links:
            await update.message.reply_text("❌ Links မတွေ့ပါ။")
        else:
            # Display links directly from the fastest search results
            keyboard = [[InlineKeyboardButton(f"🔗 {item['title'][:30]}", url=item['link'])] for item in links[:6]]
            update_history(user_id, "User", user_text)
            update_history(user_id, "Bot", "Links Sent")
            await update.message.reply_text(f"တွေ့ရှိသော Links:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif news_match:
        query = news_match.group(1).strip()
        await update.message.reply_text(f"📰 Reading News: '{query}'...")

        # Query is sanitized in execute_google_search
        search_data, _ = execute_google_search(f"Myanmar news {query}")

        if not search_data:
             await update.message.reply_text("❌ No news.")
        else:
             report_prompt = f"Search Results: {search_data}\nTask: Summarize the main facts and key events concisely in Burmese. Avoid unnecessary commentary."
             report = get_gemini_content(report_prompt)
             await update.message.reply_text(report, parse_mode='Markdown')

    elif time_match:
        mm_time = get_myanmar_time_str()
        await update.message.reply_text(f"📆 {mm_time}")

    else:
        # Default Chat Reply
        chat_reply = get_gemini_content(f"History: {previous_chat}\nUser: {user_text}\nReply smartly in Burmese.")
        if chat_reply:
            update_history(user_id, "User", user_text)
            update_history(user_id, "Bot", chat_reply)
            await update.message.reply_text(chat_reply, parse_mode='Markdown')
        else:
            await update.message.reply_text("⚠️ System Busy (AI unresponsive)")

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