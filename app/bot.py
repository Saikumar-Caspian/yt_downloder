import os
import uuid
import requests
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
MAX_FILE_BYTES = 45 * 1024 * 1024  # Telegram safe limit

BASE_DIR = os.path.expanduser("~/yt_downloder")
TMP_DIR = os.path.join(BASE_DIR, "tmp")


def is_youtube_link(text: str) -> bool:
    return "youtube.com" in text or "youtu.be" in text


def fetch_metadata(url: str) -> dict:
    with YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
        return ydl.extract_info(url, download=False)


def upload_and_get_link(file_path: str) -> str:
    with open(file_path, "rb") as f:
        r = requests.post("https://file.io", files={"file": f})
    data = r.json()
    if not data.get("success"):
        raise RuntimeError("Upload failed")
    return data["link"]


def download_media(url: str, choice: str) -> str:
    uid = str(uuid.uuid4())
    outtmpl = os.path.join(TMP_DIR, f"{uid}.%(ext)s")

    if choice == "MP3":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "quiet": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }

    elif choice == "MP4_480":
        ydl_opts = {
            "format": "bv*[height<=480]+ba/b",
            "merge_output_format": "mp4",
            "outtmpl": outtmpl,
            "quiet": True,
        }

    else:  # MP4_1080
        ydl_opts = {
            "format": "bv*[height<=1080]+ba/best",
            "merge_output_format": "mp4",
            "outtmpl": outtmpl,
            "quiet": True,
        }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    if choice == "MP3":
        base, _ = os.path.splitext(filename)
        return base + ".mp3"

    return filename


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_STATE.pop(update.effective_user.id, None)
    await update.message.reply_text("Send me a YouTube link.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global DOWNLOAD_LOCK

    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Step 1: Link
    if user_id not in USER_STATE:
        if not is_youtube_link(text):
            await update.message.reply_text("Please send a valid YouTube link.")
            return

        USER_STATE[user_id] = {"link": text}
        keyboard = ReplyKeyboardMarkup(
            [["MP3", "MP4 480p", "MP4 1080p"]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )
        await update.message.reply_text("Choose format:", reply_markup=keyboard)
        return

    # Step 2: Format
    if text not in ("MP3", "MP4 480p", "MP4 1080p"):
        await update.message.reply_text("Please choose a valid option.")
        return

    if DOWNLOAD_LOCK:
        await update.message.reply_text("Another download is in progress. Please wait.")
        return

    choice_map = {
        "MP3": "MP3",
        "MP4 480p": "MP4_480",
        "MP4 1080p": "MP4_1080",
    }

    choice = choice_map[text]
    link = USER_STATE[user_id]["link"]
    USER_STATE.pop(user_id, None)

    await update.message.reply_text("Checking video details…")

    try:
        info = fetch_metadata(link)
    except Exception:
        await update.message.reply_text("Failed to fetch metadata.")
        return

    if info.get("duration", 0) > MAX_DURATION_SECONDS:
        await update.message.reply_text("Video too long (max 30 minutes).")
        return

    DOWNLOAD_LOCK = True
    try:
        await update.message.reply_text("Downloading…")
        file_path = download_media(link, choice)

        size = os.path.getsize(file_path)

        if choice == "MP4_1080" or size > MAX_FILE_BYTES:
            await update.message.reply_text("Uploading 1080p video…")
            link_url = upload_and_get_link(file_path)
            await update.message.reply_text(
                f"🎥 1080p video ready\n🔗 Download link:\n{link_url}"
            )
        else:
            with open(file_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=os.path.basename(file_path),
                    caption=info.get("title", "Here you go"),
                )

        os.remove(file_path)

    except Exception as e:
        await update.message.reply_text("Processing failed.")
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
