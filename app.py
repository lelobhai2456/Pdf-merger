import os
import logging
import threading
import asyncio
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

# Global application
application = None

# ──────────────────────────────────────────────
# Conversation states & handlers
# ──────────────────────────────────────────────

WAITING_PDFS = 0


async def start_merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"Hi {user.first_name}! 📄\n"
        f"Send PDF files one by one (max {MAX_PDFS})\n\n"
        "Finish with:\n"
        "• /done   → merge\n"
        "• /cancel → abort"
    )
    context.user_data.clear()
    context.user_data["pdf_paths"] = []
    context.user_data["state"] = "collecting"
    return WAITING_PDFS


async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "collecting":
        return ConversationHandler.END

    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("Please send PDF files only 😅")
        return WAITING_PDFS

    paths: list[Path] = context.user_data.setdefault("pdf_paths", [])
    if len(paths) >= MAX_PDFS:
        await update.message.reply_text(f"Max {MAX_PDFS} files! Use /done or /cancel")
        return WAITING_PDFS

    file = await doc.get_file()
    path = TEMP_FOLDER / f"{update.effective_user.id}_{len(paths)+1}_{doc.file_name}"
    await file.download_to_drive(path)

    paths.append(path)

    await update.message.reply_text(f"Received {len(paths)}/{MAX_PDFS} • {doc.file_name}")
    return WAITING_PDFS


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "collecting":
        await update.message.reply_text("Nothing to merge 🤷‍♂️")
        return ConversationHandler.END

    paths = context.user_data.get("pdf_paths", [])
    if not paths:
        await update.message.reply_text("No PDFs were sent! 😕")
        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_text(f"Merging {len(paths)} PDFs... ⏳")

    merger = PdfMerger()
    output = TEMP_FOLDER / f"merged_{update.effective_user.id}.pdf"

    try:
        for p in paths:
            merger.append(p)
        with open(output, "wb") as f:
            merger.write(f)

        await update.message.reply_document(
            document=output,
            caption=f"Your merged PDF is ready! ({len(paths)} files) 🎉"
        )
    except Exception as e:
        logger.error(f"Merge error: {e}")
        await update.message.reply_text(f"Merge failed 😢\n{str(e)[:180]}")
    finally:
        merger.close()
        for p in paths + [output]:
            try:
                p.unlink(missing_ok=True)
            except:
                pass
        context.user_data.clear()

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for p in context.user_data.get("pdf_paths", []):
        try:
            p.unlink(missing_ok=True)
        except:
            pass
    context.user_data.clear()
    await update.message.reply_text("Cancelled. Files cleaned up 🧹")
    return ConversationHandler.END


# ──────────────────────────────────────────────
# Bot initialization (called once in background)
# ──────────────────────────────────────────────

def init_bot_in_background():
    global application

    if application is not None:
        return

    logger.info("Starting bot initialization in background...")

    try:
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

        # Run async startup in this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        loop.run_until_complete(application.initialize())
        loop.run_until_complete(application.start())
        loop.run_until_complete(application.bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True))

        logger.info(f"Webhook successfully set → {WEBHOOK_URL}")

    except Exception as e:
        logger.error(f"Bot initialization failed: {e}", exc_info=True)


# Start background initialization immediately (non-blocking)
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
        return "Bot is starting up... Please try again in 15-30 seconds", 503

    if request.headers.get("content-type") == "application/json":
        json_data = request.get_json(silent=True)
        if json_data:
            update = Update.de_json(json_data, application.bot)
            if update:
                # Process update synchronously (safe in Flask sync context)
                asyncio.run(application.process_update(update))
        return "", 200

    abort(403)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
