# merge_pdfs_bot.py   — full corrected version

import os
import logging
from pathlib import Path
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
#   CONFIG
# ──────────────────────────────────────────────

TOKEN = os.environ["TOKEN"]
BASE_URL = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
WEBHOOK_PATH = f"/{TOKEN}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

TEMP_FOLDER = Path("pdf_temp")
MAX_PDFS = 99   # you wanted 0-99 → max 99 files

TEMP_FOLDER.mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#   HANDLERS (same as before — just condensed a bit)
# ──────────────────────────────────────────────

WAITING_PDFS = 0

async def start_merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"Hi {user.first_name}! 📄\n"
        "Send PDF files one by one (max 99)\n\n"
        "Finish with:\n"
        "• /done  → merge\n"
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

    paths = context.user_data.setdefault("pdf_paths", [])
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
        await update.message.reply_text("No PDFs received! 😕")
        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_text(f"Merging {len(paths)} files... ⏳")

    merger = PdfMerger()
    output = TEMP_FOLDER / f"merged_{update.effective_user.id}.pdf"

    try:
        for p in paths:
            merger.append(p)
        with open(output, "wb") as f:
            merger.write(f)

        await update.message.reply_document(
            document=output,
            caption=f"Merged PDF ready! ({len(paths)} files) 🎉"
        )
    except Exception as e:
        logger.error(f"Merge failed: {e}")
        await update.message.reply_text(f"Error during merge 😢\n{str(e)[:200]}")
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
    await update.message.reply_text("Cancelled & cleaned 🧹")
    return ConversationHandler.END

# ──────────────────────────────────────────────
#   MAIN — MANUAL startup (NO asyncio.run!)
# ──────────────────────────────────────────────

def main():
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

    # Manual startup sequence — this is the key!
    application.initialize()
    application.start()
    application.bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)

    logger.info(f"Webhook successfully set → {WEBHOOK_URL}")

    # Let PTB run the webhook server forever (blocks here)
    application.updater.start_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        url_path=WEBHOOK_PATH,
        webhook_url=WEBHOOK_URL,
        drop_pending_updates=True,
    )

    # Keep the process alive
    application.updater.idle()  # ← blocks until Ctrl+C / SIGTERM


if __name__ == "__main__":
    main()
