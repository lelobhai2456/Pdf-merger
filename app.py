# app.py - FINAL version

import os
import logging
import threading
from pathlib import Path
from flask import Flask, request, abort

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

from PyPDF2 import PdfMerger

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────

TOKEN = os.environ["TOKEN"]
BASE_URL = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
WEBHOOK_PATH = f"/{TOKEN}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

TEMP_FOLDER = Path("pdf_temp")
MAX_PDFS = 99

TEMP_FOLDER.mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Global application - will be set once
application = None

# ──────────────────────────────────────────────
# Bot Handlers (same as before)
# ──────────────────────────────────────────────

WAITING_PDFS = 0

async def start_merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"Hi {user.first_name}! 📄 Send PDFs one by one (max {MAX_PDFS})\n\n"
        "/done → merge\n/cancel → abort"
    )
    context.user_data.clear()
    context.user_data["pdf_paths"] = []
    context.user_data["state"] = "collecting"
    return WAITING_PDFS

# ... (handle_pdf, done, cancel functions remain the same - copy from previous version)

# ──────────────────────────────────────────────
# One-time bot startup in background thread
# ──────────────────────────────────────────────

def init_bot_in_background():
    global application
    if application is not None:
        return

    logger.info("Starting bot initialization in background...")

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("mer", start_merge)],
        states={
            WAITING_PDFS: [
                MessageHandler(filters.Document.PDF, handle_pdf),
                CommandHandler("done", done),
                CommandHandler("cancel", cancel),
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)

    # Run async startup synchronously in this thread
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(application.initialize())
    loop.run_until_complete(application.start())
    loop.run_until_complete(application.bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True))

    logger.info(f"Webhook successfully set → {WEBHOOK_URL}")

# Start initialization in background (non-blocking for first request)
threading.Thread(target=init_bot_in_background, daemon=True).start()

# ──────────────────────────────────────────────
# Flask Routes
# ──────────────────────────────────────────────

@app.route("/health")
def health_check():
    return "OK", 200


@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    global application
    if application is None:
        return "Bot starting up, try again in 15 seconds", 503

    if request.headers.get("content-type") == "application/json":
        json_data = request.get_json(silent=True)
        if json_data:
            update = Update.de_json(json_data, application.bot)
            if update:
                # Run async process_update in sync context
                import asyncio
                asyncio.run(application.process_update(update))
        return "", 200

    abort(403)


if __name__ == "__main__":
    # Local dev
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
