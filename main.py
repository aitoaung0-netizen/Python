import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from keep_alive import keep_alive

# Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = os.environ.get("TELERAM_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Connection ကောင်းပါတယ်။ Bot အလုပ်လုပ်နေပါပြီ။")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    await update.message.reply_text(f"မင်းပြောတာက: {user_text}\n(Render Server မှာ အဆင်ပြေပါတယ်)")

if __name__ == '__main__':
    keep_alive()
    if not TOKEN:
        print("Error: TELERAM_TOKEN မရှိပါ။")
    else:
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), echo))

        print("Bot Started Testing Mode...")
        app.run_polling()