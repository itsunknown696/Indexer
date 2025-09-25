import re
import sqlite3
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from pyrogram import Client, filters
from pyrogram.types import Message
import asyncio
import config

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize database
def init_db():
    conn = sqlite3.connect(config.DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS media_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            file_type TEXT,
            title TEXT,
            course TEXT,
            extracted_by TEXT,
            file_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

class ChannelMonitor:
    def __init__(self):
        self.pyro_client = Client(
            "channel_monitor",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            bot_token=config.BOT_TOKEN
        )
        self.setup_handlers()
    
    def setup_handlers(self):
        @self.pyro_client.on_message(filters.chat(config.CHANNEL_USERNAME))
        async def handle_channel_message(client, message: Message):
            await self.process_channel_message(message)
    
    async def process_channel_message(self, message: Message):
        """Process messages from the channel and extract media information"""
        
        # Check if message contains video or document
        if message.video or message.document:
            caption = message.caption if message.caption else ""
            
            # Extract information using regex patterns
            title = self.extract_title(caption)
            course = self.extract_course(caption)
            extracted_by = self.extract_extracted_by(caption)
            
            if title:
                file_type = "video" if message.video else "pdf"
                file_id = message.video.file_id if message.video else message.document.file_id
                
                # Store in database
                self.store_media_data(
                    message_id=message.id,
                    file_type=file_type,
                    title=title,
                    course=course,
                    extracted_by=extracted_by,
                    file_id=file_id
                )
                
                logger.info(f"Stored {file_type}: {title}")
    
    def extract_title(self, caption):
        """Extract title from caption"""
        # Pattern for video title
        video_pattern = r"🎞️𝐓𝐢𝐭𝐥𝐞 »\s*([^\n]+)"
        # Pattern for PDF title
        pdf_pattern = r"📕𝐓𝐢𝐭𝐥𝐞 »\s*([^\n]+)"
        
        video_match = re.search(video_pattern, caption)
        pdf_match = re.search(pdf_pattern, caption)
        
        if video_match:
            return video_match.group(1).strip()
        elif pdf_match:
            return pdf_match.group(1).strip()
        return None
    
    def extract_course(self, caption):
        """Extract course information"""
        course_pattern = r"📚 Course :\s*([^\n]+)"
        match = re.search(course_pattern, caption)
        return match.group(1).strip() if match else "Unknown"
    
    def extract_extracted_by(self, caption):
        """Extract extracted by information"""
        extracted_pattern = r"🌟𝐄𝐱𝐭𝐫𝐚𝐜𝐭𝐞𝐝 𝐁𝐲 »\s*([^\n]+)"
        match = re.search(extracted_pattern, caption)
        return match.group(1).strip() if match else "Unknown"
    
    def store_media_data(self, message_id, file_type, title, course, extracted_by, file_id):
        """Store media data in SQLite database"""
        conn = sqlite3.connect(config.DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO media_files 
            (message_id, file_type, title, course, extracted_by, file_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (message_id, file_type, title, course, extracted_by, file_id))
        
        conn.commit()
        conn.close()
    
    async def start_monitoring(self):
        """Start monitoring the channel"""
        await self.pyro_client.start()
        logger.info("Channel monitoring started...")
    
    async def stop_monitoring(self):
        """Stop monitoring the channel"""
        await self.pyro_client.stop()

class TelegramBot:
    def __init__(self):
        self.application = Application.builder().token(config.BOT_TOKEN).build()
        self.channel_monitor = ChannelMonitor()
        self.setup_handlers()
    
    def setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("post_summary", self.post_summary))
        self.application.add_handler(CommandHandler("get_videos", self.get_videos))
        self.application.add_handler(CommandHandler("get_pdfs", self.get_pdfs))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
    
    async def start(self, update: Update, context: CallbackContext):
        """Start command handler"""
        if update.effective_user.id != config.ADMIN_ID:
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        
        await update.message.reply_text(
            "Bot started! Monitoring channel for videos and PDFs.\n\n"
            "Available commands:\n"
            "/post_summary - Post organized summary to channel\n"
            "/get_videos - Get list of all videos\n"
            "/get_pdfs - Get list of all PDFs"
        )
    
    def get_media_files(self, file_type=None):
        """Retrieve media files from database"""
        conn = sqlite3.connect(config.DB_FILE)
        cursor = conn.cursor()
        
        if file_type:
            cursor.execute('''
                SELECT * FROM media_files 
                WHERE file_type = ? 
                ORDER BY timestamp DESC
            ''', (file_type,))
        else:
            cursor.execute('''
                SELECT * FROM media_files 
                ORDER BY timestamp DESC
            ''')
        
        results = cursor.fetchall()
        conn.close()
        
        return results
    
    async def post_summary(self, update: Update, context: CallbackContext):
        """Post organized summary to channel"""
        if update.effective_user.id != config.ADMIN_ID:
            await update.message.reply_text("You are not authorized to use this command.")
            return
        
        # Get all media files
        media_files = self.get_media_files()
        
        if not media_files:
            await update.message.reply_text("No media files found in database.")
            return
        
        # Organize by course
        organized_data = {}
        for file in media_files:
            course = file[4]  # course column
            if course not in organized_data:
                organized_data[course] = []
            organized_data[course].append(file)
        
        # Create summary message
        summary_text = "📚 **Course Materials Summary**\n\n"
        
        for course, files in organized_data.items():
            summary_text += f"**{course}**\n"
            
            videos = [f for f in files if f[2] == "video"]  # file_type column
            pdfs = [f for f in files if f[2] == "pdf"]
            
            if videos:
                summary_text += "🎥 **Videos:**\n"
                for video in videos[:5]:  # Show first 5 videos
                    title = video[3]  # title column
                    message_id = video[1]  # message_id column
                    summary_text += f"• [{title}](https://t.me/{config.CHANNEL_USERNAME}/{message_id})\n"
            
            if pdfs:
                summary_text += "📄 **PDFs:**\n"
                for pdf in pdfs[:5]:  # Show first 5 PDFs
                    title = pdf[3]  # title column
                    message_id = pdf[1]  # message_id column
                    summary_text += f"• [{title}](https://t.me/{config.CHANNEL_USERNAME}/{message_id})\n"
            
            summary_text += "\n"
        
        # Post to channel
        try:
            await context.bot.send_message(
                chat_id=f"@{config.CHANNEL_USERNAME}",
                text=summary_text,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            await update.message.reply_text("Summary posted successfully!")
        except Exception as e:
            await update.message.reply_text(f"Error posting summary: {e}")
    
    async def get_videos(self, update: Update, context: CallbackContext):
        """Get list of all videos"""
        if update.effective_user.id != config.ADMIN_ID:
            await update.message.reply_text("You are not authorized to use this command.")
            return
        
        videos = self.get_media_files("video")
        
        if not videos:
            await update.message.reply_text("No videos found in database.")
            return
        
        response = "🎥 **All Videos**\n\n"
        for video in videos:
            title = video[3]
            course = video[4]
            message_id = video[1]
            response += f"• [{title}](https://t.me/{config.CHANNEL_USERNAME}/{message_id})\n"
            response += f"  Course: {course}\n\n"
        
        await update.message.reply_text(
            response,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
    
    async def get_pdfs(self, update: Update, context: CallbackContext):
        """Get list of all PDFs"""
        if update.effective_user.id != config.ADMIN_ID:
            await update.message.reply_text("You are not authorized to use this command.")
            return
        
        pdfs = self.get_media_files("pdf")
        
        if not pdfs:
            await update.message.reply_text("No PDFs found in database.")
            return
        
        response = "📄 **All PDFs**\n\n"
        for pdf in pdfs:
            title = pdf[3]
            course = pdf[4]
            message_id = pdf[1]
            response += f"• [{title}](https://t.me/{config.CHANNEL_USERNAME}/{message_id})\n"
            response += f"  Course: {course}\n\n"
        
        await update.message.reply_text(
            response,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
    
    async def button_handler(self, update: Update, context: CallbackContext):
        """Handle button clicks"""
        query = update.callback_query
        await query.answer()
        
        # Extract data from callback data
        data = query.data
        if data.startswith("video_"):
            message_id = data.replace("video_", "")
            # You can implement specific actions here
    
    async def run(self):
        """Start the bot"""
        init_db()
        
        # Start channel monitoring
        asyncio.create_task(self.channel_monitor.start_monitoring())
        
        # Start the bot
        await self.application.run_polling()

# Main execution
if __name__ == "__main__":
    bot = TelegramBot()
    asyncio.run(bot.run())
