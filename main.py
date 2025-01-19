import os
import logging
import asyncio
import json
from datetime import datetime
from typing import Dict, Optional, Union

import yt_dlp
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode
from dotenv import load_dotenv
from PIL import Image
from io import BytesIO


# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Constants
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', 0))
MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 50 * 1024 * 1024))  # 50MB Telegram limit
DOWNLOAD_PATH = "downloads"
USER_DATA_FILE = "user_data.json"

# Ensure download directory exists
os.makedirs(DOWNLOAD_PATH, exist_ok=True)

# Global state
active_downloads: Dict[int, asyncio.Task] = {}
user_data: Dict[int, dict] = {}

# Load user data from file
def load_user_data():
    global user_data
    try:
        with open(USER_DATA_FILE, 'r') as f:
            user_data = json.load(f)
    except FileNotFoundError:
        user_data = {}

# Save user data to file
def save_user_data():
    with open(USER_DATA_FILE, 'w') as f:
        json.dump(user_data, f)

# Initialize user if not exists
def init_user(user_id: int):
    if str(user_id) not in user_data:
        user_data[str(user_id)] = {
            'downloads': 0,
            'total_size': 0,
            'preferred_quality': '720p',
            'joined_date': datetime.now().isoformat(),
            'last_download': None
        }
        save_user_data()

# YouTube download options
ydl_opts = {
    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
    'outtmpl': f'{DOWNLOAD_PATH}/%(title)s.%(ext)s',
    'noplaylist': True,
    'quiet': False,
    'no_warnings': False,
    'extract-audio': False,
    'progress': True,
    'merge_output_format': 'mp4',
}

# Keyboard markups
quality_keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("360p", callback_data="quality_360p"),
        InlineKeyboardButton("480p", callback_data="quality_480p"),
        InlineKeyboardButton("720p", callback_data="quality_720p")
    ],
    [
        InlineKeyboardButton("1080p", callback_data="quality_1080p"),
        InlineKeyboardButton("MP3", callback_data="quality_mp3")
    ]
])

# Helper Functions
async def get_video_info(url: str) -> Optional[dict]:
    """Get video information using yt-dlp."""
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        logger.error(f"Error getting video info: {str(e)}")
        return None

async def download_progress_callback(d):
    """Callback function to track download progress."""
    message = d.get('message')
    if not message:
        return

    try:
        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes')
            downloaded_bytes = d.get('downloaded_bytes', 0)

            if total_bytes:
                progress = (downloaded_bytes / total_bytes) * 100
            else:
                progress = float(d.get('_percent_str', '0').replace('%', ''))

            speed = d.get('_speed_str', 'N/A')
            eta = d.get('_eta_str', 'N/A')

            await message.edit_text(
                f"⬇️ Downloading: {progress:.1f}%\n"
                f"⚡️ Speed: {speed}\n"
                f"⏱ ETA: {eta}"
            )
        elif d['status'] == 'finished':
            await message.edit_text("✅ Download completed! Processing...")

    except Exception as e:
        logger.error(f"Error in progress callback: {str(e)}")

async def process_video(url: str, quality: str, message: Message) -> Optional[str]:
    """Process video download with specified quality."""
    try:
        info = await get_video_info(url)
        if not info:
            return None

        file_path = os.path.join(DOWNLOAD_PATH, f"{info['title']}.mp4")

        if quality == 'mp3':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
            file_path = file_path.replace('.mp4', '.mp3')
        else:
            # Reset postprocessors if they were set for mp3
            if 'postprocessors' in ydl_opts:
                del ydl_opts['postprocessors']

            ydl_opts.update({
                'format': f'bestvideo[height<={quality[:-1]}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality[:-1]}][ext=mp4]/best'
            })

        # Add progress callback
        ydl_opts['progress_hooks'] = [
            lambda d: asyncio.create_task(download_progress_callback({**d, 'message': message}))
        ]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            error_code = ydl.download([url])
            if error_code != 0:
                raise Exception(f"yt-dlp download failed with code {error_code}")

        if not os.path.exists(file_path):
            # Try to find the file with a different name
            files = os.listdir(DOWNLOAD_PATH)
            for file in files:
                if file.endswith('.mp4') or file.endswith('.mp3'):
                    file_path = os.path.join(DOWNLOAD_PATH, file)
                    break

        if not os.path.exists(file_path):
            raise Exception("Downloaded file not found")

        return file_path
    except Exception as e:
        logger.error(f"Error processing video: {str(e)}")
        return None

# Command Handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    init_user(user.id)

    welcome_text = (
        f"👋 Hello {user.first_name}!\n\n"
        "Welcome to TeleuBe - Your YouTube Download Assistant! 🎉\n\n"
        "I can help you:\n"
        "📥 Download YouTube videos\n"
        "🎵 Convert videos to MP3\n"
        "🎮 Choose video quality\n\n"
        "Try these commands:\n"
        "/help - Show all commands\n"
        "/download [URL] - Download a video\n"
        "/mp3 [URL] - Get audio only\n"
        "/quality - Set preferred quality"
    )

    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = (
        "🤖 *Available Commands:*\n\n"
        "📥 *Download Commands:*\n"
        "/download [URL] - Download YouTube video\n"
        "/mp3 [URL] - Convert video to MP3\n"
        "/quality - Set preferred quality\n"
        "/cancel - Cancel current download\n\n"
        "ℹ️ *Info Commands:*\n"
        "/help - Show this help message\n"
        "/stats - View your download statistics\n\n"
        "⚠️ *Note:*\n"
        "- Maximum file size: 50MB\n"
        "- One download at a time\n"
        "- Be patient during conversion"
    )

    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def quality_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /quality command."""
    await update.message.reply_text(
        "Select your preferred video quality:",
        reply_markup=quality_keyboard
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command."""
    user_id = str(update.effective_user.id)
    if user_id not in user_data:
        await update.message.reply_text("No statistics available yet!")
        return

    stats = user_data[user_id]
    stats_text = (
        "📊 *Your Statistics:*\n\n"
        f"📥 Total Downloads: {stats['downloads']}\n"
        f"💾 Total Data: {stats['total_size'] / (1024*1024):.2f} MB\n"
        f"⚙️ Preferred Quality: {stats['preferred_quality']}\n"
        f"📅 Member Since: {stats['joined_date'][:10]}\n"
    )

    if stats['last_download']:
        stats_text += f"🕒 Last Download: {stats['last_download'][:10]}"

    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin command."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("⛔️ This command is only for administrators.")
        return

    total_downloads = sum(data['downloads'] for data in user_data.values())
    total_users = len(user_data)
    total_size = sum(data['total_size'] for data in user_data.values())

    admin_text = (
        "👑 *Admin Statistics:*\n\n"
        f"👥 Total Users: {total_users}\n"
        f"📥 Total Downloads: {total_downloads}\n"
        f"💾 Total Data: {total_size / (1024*1024*1024):.2f} GB\n"
        f"🖥 Active Downloads: {len(active_downloads)}"
    )

    await update.message.reply_text(admin_text, parse_mode=ParseMode.MARKDOWN)

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /download command."""
    if not context.args:
        await update.message.reply_text(
            "Please provide a YouTube URL!\n"
            "Example: `/download https://youtube.com/watch?v=...`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    url = context.args[0]
    user_id = update.effective_user.id

    if user_id in active_downloads:
        await update.message.reply_text(
            "⚠️ You already have an active download. Use /cancel to stop it."
        )
        return

    status_message = await update.message.reply_text("🔍 Checking video...")

    try:
        info = await get_video_info(url)
        if not info:
            await status_message.edit_text("❌ Could not fetch video information.")
            return

        # Check video duration
        if info.get('duration', 0) > 1800:  # 30 minutes
            await status_message.edit_text("❌ Video is too long (max 30 minutes).")
            return

        user_quality = user_data.get(str(user_id), {}).get('preferred_quality', '720p')
        file_path = await process_video(url, user_quality, status_message)

        if not file_path:
            await status_message.edit_text("❌ Failed to process video.")
            return

        if os.path.getsize(file_path) > MAX_FILE_SIZE:
            os.remove(file_path)
            await status_message.edit_text(
                "❌ File size exceeds Telegram's limit (50MB).\n"
                "Try a lower quality or use /mp3 for audio only."
            )
            return

        await status_message.edit_text("📤 Uploading to Telegram...")

        try:
            with open(file_path, 'rb') as f:
                if file_path.endswith('.mp3'):
                    await update.message.reply_audio(
                        f,
                        title=info['title'],
                        performer=info.get('uploader', 'Unknown'),
                        duration=info.get('duration', 0)
                    )
                else:
                    sent_message = await update.message.reply_video(
                        f,
                        caption=f"🎥 {info['title']}\n🔗 {url}",
                        supports_streaming=True
                    )
                    if not sent_message:
                        raise Exception("Failed to send video to Telegram")

            # Update user statistics
            user_data[str(user_id)]['downloads'] += 1
            user_data[str(user_id)]['total_size'] += os.path.getsize(file_path)
            user_data[str(user_id)]['last_download'] = datetime.now().isoformat()
            save_user_data()

            # Clean up the file
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Successfully deleted file: {file_path}")

            await status_message.edit_text("✅ Download completed! Check your chat for the video.")
        except Exception as e:
            logger.error(f"Error sending video: {str(e)}")
            await status_message.edit_text(f"❌ An error occurred: {str(e)}")
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        await status_message.edit_text(f"❌ An error occurred: {str(e)}")
    finally:
        if user_id in active_downloads:
            del active_downloads[user_id]

async def mp3_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mp3 command."""
    if not context.args:
        await update.message.reply_text(
            "Please provide a YouTube URL!\n"
            "Example: `/mp3 https://youtube.com/watch?v=...`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    context.args.append('mp3')
    await download_command(update, context)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command."""
    user_id = update.effective_user.id
    if user_id in active_downloads:
        active_downloads[user_id].cancel()
        del active_downloads[user_id]
        await update.message.reply_text("❌ Download cancelled.")
    else:
        await update.message.reply_text("No active download to cancel.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks."""
    query = update.callback_query
    await query.answer()

    if query.data.startswith('quality_'):
        quality = query.data.replace('quality_', '')
        user_id = str(query.from_user.id)
        init_user(query.from_user.id)
        user_data[user_id]['preferred_quality'] = quality
        save_user_data()

        await query.edit_message_text(
            f"✅ Quality preference set to {quality}!"
        )

def main():
    """Start the bot."""
    # Load existing user data
    load_user_data()

    # Create application and add handlers
    application = Application.builder().token(BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("quality", quality_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("download", download_command))
    application.add_handler(CommandHandler("mp3", mp3_command))
    application.add_handler(CommandHandler("cancel", cancel_command))

    # Add callback query handler
    application.add_handler(CallbackQueryHandler(button_handler))

    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()