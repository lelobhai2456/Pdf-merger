import os
import logging
import asyncio
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
# CONFIG
# ──────────────────────────────────────────────

TOKEN = os.environ["TOKEN"]
BASE_URL = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
WEBHOOK_PATH = f"/{TOKEN}"  # secure: /<bot-token>
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

TEMP_FOLDER = Path("pdf_temp")
MAX_PDFS = 99

TEMP_FOLDER.mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# STATES & HANDLERS
# ──────────────────────────────────────────────

WAITING_PDFS = 0


async def start_merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"Hi {user.first_name}! 📄\n"
        "Send your PDF files one by one (max {MAX_PDFS})\n\n"
        "When finished:\n"
        "• /done   → merge them\n"
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
        await update.message.reply_text("Please send only PDF files 😅")
        return WAITING_PDFS

    paths: list[Path] = context.user_data.setdefault("pdf_paths", [])
    if len(paths) >= MAX_PDFS:
        await update.message.reply_text(f"Reached max {MAX_PDFS} files! Send /done or /cancel")
        return WAITING_PDFS

    file = await doc.get_file()
    path = TEMP_FOLDER / f"{update.effective_user.id}_{len(paths)+1}_{doc.file_name}"
    await file.download_to_drive(custom_path=path)

    paths.append(path)

    await update.message.reply_text(f"Got {len(paths)}/{MAX_PDFS} • {doc.file_name}")
    return WAITING_PDFS


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "collecting":
        await update.message.reply_text("Nothing to merge right now 🤷‍♂️")
        return ConversationHandler.END

    paths: list[Path] = context.user_data.get("pdf_paths", [])
    if not paths:
        await update.message.reply_text("No PDFs received yet 😕")
        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_text(f"Merging {len(paths)} PDFs... ⏳ Please wait")

    merger = PdfMerger()
    output = TEMP_FOLDER / f"merged_{update.effective_user.id}.pdf"

    try:
        for p in paths:
            merger.append(p)
        with open(output, "wb") as f_out:
            merger.write(f_out)

        await update.message.reply_document(
            document=output,
            caption=f"Here is your merged PDF! ({len(paths)} files combined) 🎉"
        )
    except Exception as e:
        logger.error(f"Merge error: {e}")
        await update.message.reply_text(f"Oops, merge failed 😢\nError: {str(e)[:180]}")
    finally:
        merger.close()
        for file_path in paths + [output]:
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass
        context.user_data.clear()

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    paths: list[Path] = context.user_data.get("pdf_paths", [])
    for p in paths:
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass

    context.user_data.clear()
    await update.message.reply_text("Operation cancelled. All temporary files cleaned 🧹")
    return ConversationHandler.END


# ──────────────────────────────────────────────
# MAIN — This is the correct pattern for v20+ webhook on Render
# ──────────────────────────────────────────────

async def main():
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

    # Important startup sequence
    await application.initialize()
    await application.start()
    await application.bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)

    logger.info(f"Webhook set successfully → {WEBHOOK_URL}")

    # This starts the webhook server and **blocks forever**
    await application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        url_path=WEBHOOK_PATH,
        webhook_url=WEBHOOK_URL,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
