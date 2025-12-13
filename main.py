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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from keep_alive import keep_alive

# --- 1. CONFIGURATION ---
GEMINI_KEYS = os.environ.get("GEMINI_API_KEYS", "").split(",")
GOOGLE_SEARCH_KEYS = os.environ.get("GOOGLE_SEARCH_API_KEYS", "").split(",")
GOOGLE_CX_ID = os.environ.get("GOOGLE_CX_ID", "")
BOT_TOKEN = os.environ.get("TELERAM_TOKEN")

# 🔥 USE "PRO" MODEL IF AVAILABLE, ELSE FLASH (For better reasoning)
MODEL_NAME = "gemini-2.5-flash" 
MEMORY_FILE = "chat_memory.json"

logging.basicConfig(level=logging.INFO)

ACTIVE_GEMINI_KEYS = [k.strip() for k in GEMINI_KEYS if k.strip()]
ACTIVE_SEARCH_KEYS = [k.strip() for k in GOOGLE_SEARCH_KEYS if k.strip()]

# 🔥 KEYWORDS
ADULT_KEYWORDS = ["sex", "porn", "xxx", "18+", "leak", "viral", "bsw", "အော", "လိုး"]

# --- 2. INTELLIGENT HELPERS ---

def get_gemini_content(prompt, image=None):
    if not ACTIVE_GEMINI_KEYS: return "⚠️ Error: AI Keys missing."
    shuffled_keys = ACTIVE_GEMINI_KEYS.copy()
    random.shuffle(shuffled_keys)

    for key in shuffled_keys:
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel(MODEL_NAME)
            content = [prompt, image] if image else prompt
            response = model.generate_content(content)
            return response.text
        except: continue
    return "⚠️ System Busy (AI Overload)."

def execute_google_search(query, fresh=False, only_telegram=False, strict_adult=False):
    if not GOOGLE_CX_ID or not ACTIVE_SEARCH_KEYS: return None, []

    shuffled_keys = ACTIVE_SEARCH_KEYS.copy()
    random.shuffle(shuffled_keys)

    for key in shuffled_keys:
        try:
            url = "https://www.googleapis.com/customsearch/v1"
            params = {'q': query, 'key': key, 'cx': GOOGLE_CX_ID, 'safe': 'off'}
            if fresh: params['dateRestrict'] = 'd1' # Last 24 hours

            response = requests.get(url, params=params)
            if response.status_code != 200: continue

            res = response.json()
            if 'items' in res:
                text_out = ""
                links = []
                for item in res['items']:
                    title = item.get('title', '')
                    link = item.get('link', '')
                    snippet = item.get('snippet', '').lower()

                    # 1. Telegram Filter
                    if only_telegram:
                        if "t.me" not in link: continue
                        link = link.replace("/s/", "/")
                        if "Telegram: Contact" in title and len(snippet) < 10: continue

                    # 2. Strict Adult Filter
                    full_text = (title + " " + snippet).lower()
                    if strict_adult and not any(k in full_text for k in ADULT_KEYWORDS):
                        continue

                    text_out += f"- Title: {title}\n  Snippet: {snippet}\n  Link: {link}\n\n"
                    links.append({"title": title, "link": link})

                if only_telegram and not links: return "", []
                return text_out, links
        except: continue
    return "", []

def tool_image_gen(prompt):
    return f"https://image.pollinations.ai/prompt/{prompt}"

# --- 3. THE SMART BRAIN ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    if not user_text and not update.message.photo: return

    # 1. Vision (Eyes)
    if update.message.photo:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        caption = update.message.caption if update.message.caption else "Analyze this"
        try:
            photo_file = await update.message.photo[-1].get_file()
            photo_bytes = await photo_file.download_as_bytearray()
            img_data = Image.open(io.BytesIO(photo_bytes))

            # Smart Analysis
            analysis = get_gemini_content([f"User: {caption}. Analyze deeply and reply in Burmese.", img_data])
            await update.message.reply_text(analysis)
        except: await update.message.reply_text("❌ Vision Error")
        return

    # 2. Text Analysis (Brain)
    await update.message.reply_chat_action(constants.ChatAction.TYPING)

    # Check "Intent" - What does the user REALLY want?
    # We ask Gemini to think first.

    intent_prompt = f"""
    You are a smart assistant. User Input: "{user_text}"
    Current Time: {datetime.now(timezone(timedelta(hours=6, minutes=30))).strftime("%Y-%m-%d %I:%M %p")}

    Analyze the intent. Return ONLY the JSON:
    {{
        "action": "SEARCH_PRICE" | "SEARCH_LINK" | "SEARCH_NEWS" | "GEN_IMAGE" | "CHAT",
        "query": "refined search query or prompt",
        "strict_adult": true/false (if user explicitly asks for 18+)
    }}
    """

    try:
        raw_decision = get_gemini_content(intent_prompt)
        decision = json.loads(re.search(r'\{.*\}', raw_decision, re.DOTALL).group())
    except:
        decision = {"action": "CHAT", "query": user_text, "strict_adult": False}

    action = decision.get("action")
    query = decision.get("query")
    is_strict = decision.get("strict_adult")

    # --- EXECUTION PHASE ---

    # 🧠 CASE 1: INTELLIGENT PRICE ANALYSIS
    if action == "SEARCH_PRICE":
        await update.message.reply_text(f"📉 ဈေးကွက်ကို လေ့လာသုံးသပ်နေသည်: {query}...")

        # We search specifically for external/black market
        search_q = f"Myanmar external market price {query} black market today real update"
        raw_data, _ = execute_google_search(search_q)

        if not raw_data:
            await update.message.reply_text("❌ Data မတွေ့ပါ။")
        else:
            # 🔥 THE "GEMINI" TOUCH: Analyze raw data like a human
            analysis_prompt = f"""
            Here is raw search data about Myanmar Market Prices:
            {raw_data}

            USER QUESTION: "{user_text}"

            TASK: 
            1. Identify the 'External/Black Market' price (usually higher).
            2. Identify 'YGEA/Official' price (usually lower).
            3. If data is messy, ESTIMATE the most likely real trading price based on trends.
            4. Reply in Burmese like a smart market analyst. (Don't just list numbers, explain slightly).
            """
            final_reply = get_gemini_content(analysis_prompt)
            await update.message.reply_text(final_reply, parse_mode='Markdown')

    # 🧠 CASE 2: SMART LINK FINDER
    elif action == "SEARCH_LINK":
        search_type = "(sex OR porn OR leak)" if is_strict else "(channel OR 1080p OR mmsub)"
        final_query = f'site:t.me "{query}" {search_type}'

        await update.message.reply_text(f"🔍 Link ရှာဖွေမှု စတင်နေပြီ: {query}...")
        _, links = execute_google_search(final_query, fresh=False, only_telegram=True, strict_adult=is_strict)

        if not links:
             # Fallback
             _, links = execute_google_search(f'site:t.me {query}', fresh=False, only_telegram=True)

        if not links:
            await update.message.reply_text("❌ လိုချင်သော Link အစစ်အမှန် မတွေ့ရှိပါ။")
        else:
            # Let Gemini verify if these look like good links (Optional, but let's stick to buttons for speed)
            buttons = [[InlineKeyboardButton(f"🔗 {item['title'][:40]}", url=item['link'])] for item in links[:6]]
            await update.message.reply_text(f"တွေ့ရှိရသော အကောင်းဆုံး Links များ:", reply_markup=InlineKeyboardMarkup(buttons))

    # 🧠 CASE 3: NEWS SUMMARY
    elif action == "SEARCH_NEWS":
        await update.message.reply_text(f"📰 သတင်းများကို ဖတ်ရှုနေသည်...")
        raw_data, _ = execute_google_search(f"Myanmar news {query} latest", fresh=True)

        if not raw_data:
            await update.message.reply_text("❌ သတင်းထူး မတွေ့ပါ။")
        else:
            summary_prompt = f"""
            Raw News Data: {raw_data}
            User Topic: {user_text}

            TASK: Summarize the TRUTH. Identify rumors vs facts if possible.
            Reply in Burmese as a News Anchor.
            """
            final_reply = get_gemini_content(summary_prompt)
            await update.message.reply_text(final_reply, parse_mode='Markdown')

    # 🧠 CASE 4: IMAGE
    elif action == "GEN_IMAGE":
        await update.message.reply_text("🎨 ပုံဖန်တီးနေသည်...")
        await update.message.reply_photo(tool_image_gen(query))

    # 🧠 CASE 5: PURE INTELLIGENT CHAT
    else:
        # Just talk like Gemini
        chat_prompt = f"""
        User said: "{user_text}"
        Act as 'Gemini', a helpful, smart, and friendly AI assistant.
        Reply in Burmese naturally.
        """
        reply = get_gemini_content(chat_prompt)
        await update.message.reply_text(reply, parse_mode='Markdown')

if __name__ == '__main__':
    keep_alive()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))
    print("Smart Bot Started...")
    app.run_polling()