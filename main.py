import logging
import os
import random
import json
import re
import requests
import io
import asyncio
from datetime import datetime, timedelta, timezone
from PIL import Image
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from keep_alive import keep_alive

# --- 1. SYSTEM CONFIGURATION ---
# Load Environment Variables
GEMINI_KEYS = os.environ.get("GEMINI_API_KEYS", "").split(",")
GOOGLE_SEARCH_KEYS = os.environ.get("GOOGLE_SEARCH_API_KEYS", "").split(",")
GOOGLE_CX_ID = os.environ.get("GOOGLE_CX_ID", "")
BOT_TOKEN = os.environ.get("TELERAM_TOKEN")

# Setup Logging & Model
logging.basicConfig(level=logging.INFO)
MODEL_NAME = "gemini-1.5-flash" 

# Active Keys Storage
ACTIVE_GEMINI_KEYS = [k.strip() for k in GEMINI_KEYS if k.strip()]
ACTIVE_SEARCH_KEYS = [k.strip() for k in GOOGLE_SEARCH_KEYS if k.strip()]

# --- 2. THE BRAIN (GEMINI INTELLIGENCE) ---

def get_current_time():
    # Force Myanmar Time
    utc_now = datetime.now(timezone.utc)
    mm_time = utc_now + timedelta(hours=6, minutes=30)
    return mm_time.strftime("%Y-%m-%d (%I:%M %p)")

def ask_gemini(prompt, image=None, json_mode=False):
    """
    This is the core brain function. It switches keys if one fails.
    """
    if not ACTIVE_GEMINI_KEYS: return None
    random.shuffle(ACTIVE_GEMINI_KEYS)

    for key in ACTIVE_GEMINI_KEYS:
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel(MODEL_NAME)

            # If JSON mode is requested, we force JSON structure in prompt
            if json_mode:
                prompt += "\n\nRETURN JSON ONLY. NO MARKDOWN."

            content = [prompt, image] if image else prompt
            response = model.generate_content(content)

            if json_mode:
                # Clean up markdown code blocks to extract pure JSON
                text = response.text.replace("```json", "").replace("```", "").strip()
                return json.loads(text)

            return response.text
        except Exception as e:
            print(f"Key Error ({key[:5]}...): {e}")
            continue
    return None

# --- 3. THE HANDS (TOOLS) ---

def tool_google_search(query, search_type="general"):
    """
    Smart Search Tool that auto-filters garbage dates.
    """
    if not ACTIVE_SEARCH_KEYS or not GOOGLE_CX_ID: return None, []

    random.shuffle(ACTIVE_SEARCH_KEYS)
    for key in ACTIVE_SEARCH_KEYS:
        try:
            params = {
                'q': query, 'key': key, 'cx': GOOGLE_CX_ID, 'safe': 'off'
            }

            # 🔥 STRICT RULE: For Prices & News, force 24-hour freshness
            if search_type in ["PRICE", "NEWS"]:
                params['dateRestrict'] = 'd1'

            response = requests.get("https://www.googleapis.com/customsearch/v1", params=params)
            data = response.json()

            if 'items' not in data: continue

            results_text = ""
            links = []

            for item in data['items']:
                title = item.get('title', 'No Title')
                link = item.get('link', '')
                snippet = item.get('snippet', '')

                # Filter Logic based on Type
                if search_type == "LINK_TELEGRAM":
                    if "t.me" not in link: continue
                    if "Telegram: Contact" in title and len(snippet) < 15: continue

                results_text += f"SOURCE: {title}\nDETAILS: {snippet}\nLINK: {link}\n\n"
                links.append({'title': title, 'link': link})

            return results_text, links
        except: continue
    return None, []

def tool_image_generator(prompt):
    return f"https://image.pollinations.ai/prompt/{prompt}"

# --- 4. THE AUTONOMOUS AGENT LOGIC ---

async def agent_core(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    user_id = update.effective_user.id
    timestamp = get_current_time()

    # --- A. VISION INPUT ---
    if update.message.photo:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        caption = update.message.caption if update.message.caption else "Analyze this image"

        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        img_data = Image.open(io.BytesIO(photo_bytes))

        analysis = ask_gemini(f"User sent image. Context: {caption}. Analyze and reply in Burmese.", img_data)
        await update.message.reply_text(analysis if analysis else "❌ Error analyzing image.")
        return

    if not user_text: return
    await update.message.reply_chat_action(constants.ChatAction.TYPING)

    # --- B. INTENT ANALYSIS (THE BRAIN) ---
    # We ask Gemini to decide what to do instead of using 'if' statements.

    brain_prompt = f"""
    You are the "Master Control" of a Telegram Bot.
    Current Time (Myanmar): {timestamp}
    User Input: "{user_text}"

    TASK: Analyze user intent and output a JSON decision.

    INTENT CATEGORIES:
    1. "PRICE_CHECK" -> If user asks for Gold, USD, Currency, Fuel prices.
    2. "LINK_FINDER" -> If user asks for Movie, Series, Channel, 18+, MMSUB links.
       - set "is_adult": true if keywords (sex, porn, leak, viral, 18+) are present.
    3. "NEWS_UPDATE" -> If user asks for News/Events.
    4. "IMAGE_GEN" -> If user asks to Draw/Create image.
    5. "CHAT" -> General conversation.

    JSON FORMAT:
    {{
        "intent": "PRICE_CHECK" | "LINK_FINDER" | "NEWS_UPDATE" | "IMAGE_GEN" | "CHAT",
        "search_query": "Optimized Google search query based on user input",
        "is_adult": true/false
    }}
    """

    decision = ask_gemini(brain_prompt, json_mode=True)

    if not decision:
        await update.message.reply_text("⚠️ Brain Error: I couldn't think.")
        return

    intent = decision.get("intent")
    query = decision.get("search_query")
    is_adult = decision.get("is_adult", False)

    print(f"🤖 DECISION: {intent} | Query: {query} | Adult: {is_adult}")

    # --- C. EXECUTION PHASE ---

    # 1. PRICE CHECK AGENT
    if intent == "PRICE_CHECK":
        await update.message.reply_text(f"📉 ဈေးနှုန်းစိစစ်နေသည် (Date: {timestamp})...")

        # We enforce "Market Price" search keywords
        final_query = f"{query} market price Myanmar {timestamp} black market"
        raw_data, _ = tool_google_search(final_query, search_type="PRICE")

        if not raw_data:
            await update.message.reply_text("❌ ဒီနေ့အတွက် Data အသစ်မတွေ့ပါ။")
        else:
            # Re-Analyze data to remove old dates
            analyst_prompt = f"""
            You are a Market Analyst.
            Raw Data: {raw_data}
            Current Time: {timestamp}

            Task: Extract ONLY valid prices for TODAY/YESTERDAY.
            - Ignore "Official Rate". Find "External/Black Market Rate".
            - Ignore data older than 24 hours.
            - Reply in Burmese format.
            """
            final_response = ask_gemini(analyst_prompt)
            await update.message.reply_text(final_response, parse_mode='Markdown')

    # 2. LINK FINDER AGENT
    elif intent == "LINK_FINDER":
        await update.message.reply_text(f"🔍 Link ရှာနေသည် ({'18+' if is_adult else 'Safe'})...")

        if is_adult:
            final_query = f'site:t.me "{query}" (leak OR viral OR sex OR porn)'
        else:
            final_query = f'site:t.me "{query}" (channel OR mmsub OR 1080p)'

        _, links = tool_google_search(final_query, search_type="LINK_TELEGRAM")

        # Strict Filter
        valid_links = []
        for l in links:
            title_lower = l['title'].lower()
            # If Adult requested, Title MUST sound adult
            if is_adult:
                if any(k in title_lower for k in ["sex", "porn", "leak", "viral", "အော", "လိုး"]):
                    valid_links.append(l)
            else:
                # If Safe requested, remove obvious adult titles
                if not any(k in title_lower for k in ["sex", "porn"]):
                    valid_links.append(l)

        if valid_links:
            buttons = [[InlineKeyboardButton(f"🔗 {item['title'][:30]}", url=item['link'])] for item in valid_links[:6]]
            await update.message.reply_text(f"တွေ့ရှိသော Links များ:", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await update.message.reply_text("❌ Link အစစ်အမှန် မတွေ့ရှိပါ။")

    # 3. NEWS AGENT
    elif intent == "NEWS_UPDATE":
        await update.message.reply_text("📰 သတင်းဖတ်နေသည်...")
        raw_data, _ = tool_google_search(f"{query} latest", search_type="NEWS")

        if raw_data:
            news_prompt = f"Summarize these latest Myanmar news events into a short Burmese report. Ignore old news.\nData: {raw_data}"
            final_response = ask_gemini(news_prompt)
            await update.message.reply_text(final_response, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ သတင်းထူး မတွေ့ပါ။")

    # 4. ARTIST AGENT
    elif intent == "IMAGE_GEN":
        await update.message.reply_text("🎨 ပုံဖန်တီးနေသည်...")
        image_url = tool_image_generator(query)
        await update.message.reply_photo(image_url)

    # 5. CHAT AGENT
    else:
        chat_prompt = f"User said: {user_text}\nReply as a smart AI assistant in Burmese."
        response = ask_gemini(chat_prompt)
        await update.message.reply_text(response, parse_mode='Markdown')

# --- 5. INITIALIZATION ---

if __name__ == '__main__':
    keep_alive()

    if not BOT_TOKEN:
        print("❌ Error: TELERAM_TOKEN missing.")
    else:
        print("✅ AI AUTONOMOUS AGENT STARTED...")
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, agent_core))
        app.run_polling()