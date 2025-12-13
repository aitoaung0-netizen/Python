import logging
import os
import random
import re
import json
import requests
import io
import asyncio
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

# Use stable model
MODEL_NAME = "gemini-2.5-flash" 
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

ACTIVE_GEMINI_KEYS = [k.strip() for k in GEMINI_KEYS if k.strip()]
ACTIVE_SEARCH_KEYS = [k.strip() for k in GOOGLE_SEARCH_KEYS if k.strip()]

# --- 2. HELPER FUNCTIONS ---
def get_myanmar_time_str():
    utc_now = datetime.now(timezone.utc)
    mm_time = utc_now + timedelta(hours=6, minutes=30)
    return mm_time.strftime("%Y-%m-%d %I:%M %p")

def get_gemini_response(prompt, image=None):
    if not ACTIVE_GEMINI_KEYS: return "⚠️ Error: No Gemini Keys active."

    # Shuffle keys to distribute load
    random.shuffle(ACTIVE_GEMINI_KEYS)

    for key in ACTIVE_GEMINI_KEYS:
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel(MODEL_NAME)
            response = model.generate_content([prompt, image] if image else prompt)
            return response.text
        except Exception as e:
            print(f"Key failed: {key[:5]}... Error: {e}")
            continue
    return "⚠️ System Busy: All AI keys failed. Please wait or update keys."

def google_search(query, only_telegram=False):
    if not ACTIVE_SEARCH_KEYS or not GOOGLE_CX_ID:
        return None, []

    # Shuffle keys
    random.shuffle(ACTIVE_SEARCH_KEYS)

    for key in ACTIVE_SEARCH_KEYS:
        try:
            url = "https://www.googleapis.com/customsearch/v1"
            # Add strict filters for Telegram
            if only_telegram:
                query += " site:t.me"

            params = {'q': query, 'key': key, 'cx': GOOGLE_CX_ID}
            response = requests.get(url, params=params, timeout=5)

            if response.status_code == 200:
                data = response.json()
                results = []
                text_summary = ""

                if 'items' not in data: return "No results found.", []

                for item in data['items']:
                    title = item.get('title', '')
                    link = item.get('link', '')
                    snippet = item.get('snippet', '')

                    # Strict Filter: Must be t.me link if requested
                    if only_telegram and "t.me" not in link: continue

                    results.append({'title': title, 'link': link})
                    text_summary += f"Title: {title}\nLink: {link}\nInfo: {snippet}\n\n"

                return text_summary, results
            else:
                print(f"Search Key failed: {response.status_code}")
                continue # Try next key
        except Exception as e:
            print(f"Search Error: {e}")
            continue

    return None, []

# --- 3. MAIN BOT LOGIC ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if not user_text: return

    # Tell user we are working
    await update.message.reply_chat_action(constants.ChatAction.TYPING)

    # 1. Check for specific keywords (Hardcoded logic is faster & safer)
    text_lower = user_text.lower()

    # --- FEATURE A: GOLD/PRICE ---
    if any(x in text_lower for x in ["gold", "price", "ဈေး", "ဒေါ်လာ", "ရွှေ"]):
        await update.message.reply_text(f"📉 ဈေးနှုန်းရှာနေသည်: {user_text}...")

        # Search Google
        search_data, _ = google_search(f"Myanmar market price {user_text} today update")

        if not search_data:
            await update.message.reply_text("❌ Data မတွေ့ပါ (Search Key Error or No Data).")
        else:
            # Use AI to extract numbers
            ai_summary = get_gemini_response(f"""
            Analyze these search results: {search_data}
            User asked for: {user_text}
            Current Date: {get_myanmar_time_str()}

            Task: Extract the latest market prices/rates.
            If user asks for Gold, look for "Akhat" or "High Quality".
            Output in Burmese language list format.
            """)
            await update.message.reply_text(ai_summary, parse_mode='Markdown')
        return

    # --- FEATURE B: TELEGRAM LINKS ---
    if any(x in text_lower for x in ["link", "channel", "group", "ကား", "mms"]):
        await update.message.reply_text(f"🔍 Link ရှာနေသည်: {user_text}...")

        # Strict Telegram Search
        search_query = user_text.replace("link", "").strip()
        _, links = google_search(search_query, only_telegram=True)

        if not links:
            await update.message.reply_text("❌ Link အစစ်များ မတွေ့ပါ။")
        else:
            buttons = []
            for item in links[:5]: # Show top 5
                buttons.append([InlineKeyboardButton(f"🔗 {item['title'][:30]}", url=item['link'])])

            await update.message.reply_text(
                "တွေ့ရှိသော Links များ:", 
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        return

    # --- FEATURE C: GENERAL AI CHAT ---
    response = get_gemini_response(f"User said: {user_text}. Reply helpfully in Burmese.")
    await update.message.reply_text(response, parse_mode='Markdown')

# --- 4. STARTUP ---
if __name__ == '__main__':
    keep_alive()

    if not BOT_TOKEN:
        print("❌ Error: TELERAM_TOKEN missing.")
    elif not ACTIVE_GEMINI_KEYS:
        print("❌ Error: No Gemini Keys found in Secrets.")
    else:
        print(f"✅ Bot Starting... (Gemini Keys: {len(ACTIVE_GEMINI_KEYS)}, Search Keys: {len(ACTIVE_SEARCH_KEYS)})")

        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

        app.run_polling()