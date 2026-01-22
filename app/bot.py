import os
import uuid
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from yt_dlp import YoutubeDL

BOT_TOKEN = os.getenv("BOT_TOKEN")

# In-memory state & lock
USER_STATE = {}
DOWNLOAD_LOCK = False

# Limits
MAX_DURATION_SECONDS = 60 * 30  # 30 minutes
MAX_FILE_BYTES = 45 * 1024 * 1024  # 45 MB (safe margin for bots)

BASE_DIR = os.path.expanduser("~/tg-runtime")
TMP_DIR = os.path.join(BASE_DIR, "tmp")


def is_youtube_link(text: str) -> bool:
    return "youtube.com" in text or "youtu.be" in text


def fetch_metadata(url: str) -> dict:
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "nocheckcertificate": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def download_media(url: str, choice: str) -> str:
    """
    Downloads media and returns the final file path.
    Uses FFmpeg via yt-dlp postprocessors.
    """
    uid = str(uuid.uuid4())
    outtmpl = os.path.join(TMP_DIR, f"{uid}.%(ext)s")

    if choice == "MP3":
        # True MP3 conversion via FFmpeg
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "quiet": True,
            "nocheckcertificate": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",  # kbps
                }
            ],
        }
    else:
        # Robust MP4: best video + best audio, merge with FFmpeg
        ydl_opts = {
            "format": "bestvideo[ext=mp4]/bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "outtmpl": outtmpl,
            "quiet": True,
            "nocheckcertificate": True,
        }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    # yt-dlp may change extension after postprocessing (e.g., .mp3)
    if choice == "MP3":
        base, _ = os.path.splitext(filename)
        mp3_path = base + ".mp3"
        return mp3_path

    return filename


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_STATE.pop(update.effective_user.id, None)
    await update.message.reply_text("Send me a YouTube link.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global DOWNLOAD_LOCK

    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Step 1: Expecting YouTube link
    if user_id not in USER_STATE:
        if not is_youtube_link(text):
            await update.message.reply_text("Please send a valid YouTube link.")
            return

        USER_STATE[user_id] = {"link": text}
        keyboard = ReplyKeyboardMarkup(
            [["MP3", "MP4"]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )
        await update.message.reply_text("Choose format:", reply_markup=keyboard)
        return

    # Step 2: Expecting format choice
    if text not in ("MP3", "MP4"):
        await update.message.reply_text("Please choose MP3 or MP4.")
        return

    if DOWNLOAD_LOCK:
        await update.message.reply_text("Another download is in progress. Please wait.")
        return

    choice = text
    link = USER_STATE[user_id]["link"]
    USER_STATE.pop(user_id, None)

    await update.message.reply_text("Checking video details…")

    try:
        info = fetch_metadata(link)
    except Exception:
        await update.message.reply_text("Failed to fetch video metadata.")
        return

    duration = info.get("duration", 0)
    title = info.get("title", "Unknown title")

    if duration > MAX_DURATION_SECONDS:
        await update.message.reply_text(
            "Video is too long. Please choose a video under 30 minutes."
        )
        return

    DOWNLOAD_LOCK = True
    try:
        await update.message.reply_text("Downloading and processing…")
        file_path = download_media(link, choice)

        if not os.path.exists(file_path):
            await update.message.reply_text("Processing failed.")
            return

        size = os.path.getsize(file_path)
        if size > MAX_FILE_BYTES:
            os.remove(file_path)
            await update.message.reply_text("File is too large to send via Telegram.")
            return

        await update.message.reply_text("Uploading to Telegram…")
        with open(file_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=os.path.basename(file_path),
                caption=title,
            )

        os.remove(file_path)

    except Exception:
        await update.message.reply_text("Download or processing failed.")
    finally:
        DOWNLOAD_LOCK = False


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not set")

    os.makedirs(TMP_DIR, exist_ok=True)

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()


if __name__ == "__main__":
    main()

