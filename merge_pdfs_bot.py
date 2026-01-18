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
    ConversationHandler
)
from PyPDF2 import PdfMerger

# ---------------- STATES ----------------
WAITING_PDFS = 0

# ---------------- CONFIG ----------------
TOKEN = os.environ['TOKEN']
BASE_URL = os.environ['RENDER_EXTERNAL_URL'].rstrip('/')   # automatically provided by Render
WEBHOOK_PATH = f"/{TOKEN}"                                 # secure path using token
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

TEMP_FOLDER = Path("pdf_temp")
MAX_PDFS = 100

TEMP_FOLDER.mkdir(exist_ok=True)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
#   Your existing handlers (start_merge, handle_pdf, done, cancel)
#   remain EXACTLY THE SAME — just paste them here
# ──────────────────────────────────────────────────────────────

async def start_merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"Hi {user.first_name}! 📄\n"
        "Start sending PDF files one by one (max 99 files)\n\n"
        "When you're done send:\n"
        "• /done    → merge & get result\n"
        "• /cancel  → abort everything"
    )

    context.user_data.clear()
    context.user_data["pdf_paths"] = []
    context.user_data["state"] = "collecting"

    return WAITING_PDFS


async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "collecting":
        return ConversationHandler.END

    document = update.message.document
    if not document or not document.file_name.lower().endswith('.pdf'):
        await update.message.reply_text("Please send PDF files only 😅")
        return WAITING_PDFS

    current_count = len(context.user_data.get("pdf_paths", []))

    if current_count >= MAX_PDFS:
        await update.message.reply_text(f"Maximum {MAX_PDFS} files reached! Use /done or /cancel")
        return WAITING_PDFS

    file = await document.get_file()
    file_path = TEMP_FOLDER / f"{update.effective_user.id}_{current_count+1}_{document.file_name}"
    await file.download_to_drive(file_path)

    context.user_data.setdefault("pdf_paths", []).append(file_path)

    await update.message.reply_text(
        f"Received {current_count+1}/{MAX_PDFS}  •  {document.file_name}"
    )
    return WAITING_PDFS


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "collecting":
        await update.message.reply_text("Nothing to merge right now 🤷‍♂️")
        return ConversationHandler.END

    pdf_paths = context.user_data.get("pdf_paths", [])
    if not pdf_paths:
        await update.message.reply_text("No PDFs were sent! 😕")
        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_text(f"Merging {len(pdf_paths)} PDFs... ⏳")

    merger = PdfMerger()
    output_path = TEMP_FOLDER / f"merged_{update.effective_user.id}.pdf"

    try:
        for path in pdf_paths:
            merger.append(path)

        with open(output_path, "wb") as f:
            merger.write(f)

        await update.message.reply_document(
            document=output_path,
            caption=f"Here is your merged PDF! ({len(pdf_paths)} files) 🎉"
        )

    except Exception as e:
        logger.error(f"Merge failed: {e}")
        await update.message.reply_text(f"Merge failed 😢\nError: {str(e)[:200]}")

    finally:
        merger.close()
        for p in pdf_paths + [output_path]:
            try:
                if p.exists():
                    p.unlink()
            except:
                pass
        context.user_data.clear()

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pdf_paths = context.user_data.get("pdf_paths", [])
    for p in pdf_paths:
        try:
            if p.exists():
                p.unlink()
        except:
            pass

    context.user_data.clear()
    await update.message.reply_text("Cancelled & cleaned up 🧹")
    return ConversationHandler.END


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
        allow_reentry=True
    )

    application.add_handler(conv_handler)

    # Very important: set webhook on startup
    await application.initialize()
    await application.bot.set_webhook(url=WEBHOOK_URL)

    logger.info(f"Webhook set to: {WEBHOOK_URL}")

    # Start webhook server using Render-provided PORT
    await application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        url_path=WEBHOOK_PATH,
        webhook_url=WEBHOOK_URL,
        drop_pending_updates=True,           # optional: clean old updates
    )


if __name__ == "__main__":
    asyncio.run(main())
