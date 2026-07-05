import os
import logging
import io
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
from datetime import datetime

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get environment variables
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(os.environ.get("PORT", 8080))

if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN not set!")
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

# Initialize Flask app
app = Flask(__name__)

# Store user sessions
user_sessions = {}

# ============================================
# IMAGE PROCESSING FUNCTIONS
# ============================================

def process_image(image_bytes, operation, **kwargs):
    """Main image processing function."""
    img = Image.open(io.BytesIO(image_bytes))
    output = io.BytesIO()
    
    if operation == "grayscale":
        img = img.convert('L')
    
    elif operation == "blur":
        img = img.filter(ImageFilter.GaussianBlur(radius=kwargs.get('radius', 3)))
    
    elif operation == "sharpen":
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(2.0)
    
    elif operation == "invert":
        if img.mode == 'RGBA':
            r, g, b, a = img.split()
            rgb_img = Image.merge('RGB', (r, g, b))
            inverted = ImageOps.invert(rgb_img)
            r2, g2, b2 = inverted.split()
            img = Image.merge('RGBA', (r2, g2, b2, a))
        else:
            img = ImageOps.invert(img)
    
    elif operation == "rotate":
        img = img.rotate(kwargs.get('angle', 90), expand=True)
    
    elif operation == "resize":
        img = img.resize(
            (kwargs.get('width', 512), kwargs.get('height', 512)),
            Image.Resampling.LANCZOS
        )
    
    elif operation == "convert":
        target_format = kwargs.get('format', 'PNG').upper()
        if target_format == 'JPEG' and img.mode == 'RGBA':
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[3])
            img = rgb_img
        img.save(output, format=target_format)
        return output.getvalue()
    
    img.save(output, format='PNG')
    return output.getvalue()

# ============================================
# TELEGRAM BOT HANDLERS
# ============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("🖼 Convert", callback_data="convert"),
         InlineKeyboardButton("🎨 Filter", callback_data="filter")],
        [InlineKeyboardButton("🔧 Effects", callback_data="advanced"),
         InlineKeyboardButton("📐 Resize", callback_data="resize")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ]
    
    await update.message.reply_text(
        f"👋 Welcome {user.first_name}!\n\n"
        "I'm ImageMagicBot - your image processing assistant!\n\n"
        "📤 Send me an image to get started!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    await update.message.reply_text(
        "📖 *ImageMagicBot Help*\n\n"
        "*How to use:*\n"
        "1. Send me an image (photo or file)\n"
        "2. Choose an operation from the menu\n"
        "3. Get your processed image!\n\n"
        "*Commands:*\n"
        "/start - Start the bot\n"
        "/help - Show this help\n"
        "/cancel - Cancel current operation",
        parse_mode='Markdown'
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command."""
    user_id = update.effective_user.id
    if user_id in user_sessions:
        del user_sessions[user_id]
    await update.message.reply_text("✅ Session cleared. Send /start to begin again.")

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming images."""
    user_id = update.effective_user.id
    
    try:
        if update.message.photo:
            file = await context.bot.get_file(update.message.photo[-1].file_id)
        elif update.message.document:
            file = await context.bot.get_file(update.message.document.file_id)
        else:
            await update.message.reply_text("❌ Please send an image.")
            return
        
        image_bytes = await file.download_as_bytearray()
        
        user_sessions[user_id] = {
            'original': image_bytes,
            'current': image_bytes
        }
        
        keyboard = [
            [InlineKeyboardButton("🖼 Convert", callback_data="convert"),
             InlineKeyboardButton("🎨 Filter", callback_data="filter")],
            [InlineKeyboardButton("🔧 Effects", callback_data="advanced"),
             InlineKeyboardButton("📐 Resize", callback_data="resize")],
            [InlineKeyboardButton("↩️ Reset", callback_data="reset")]
        ]
        
        await update.message.reply_text(
            "✅ Image received! What would you like to do?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error handling image: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if user_id not in user_sessions and data not in ["help", "back"]:
        await query.edit_message_text("❌ No image in session. Please send an image first.")
        return
    
    if data == "help":
        await query.edit_message_text(
            "📖 *Quick Help*\n\n• Send an image to start\n• Choose operations from menus\n• Use /cancel to clear session",
            parse_mode='Markdown'
        )
        return
    
    if data == "convert":
        keyboard = [
            [InlineKeyboardButton("PNG", callback_data="conv_png"),
             InlineKeyboardButton("JPEG", callback_data="conv_jpeg")],
            [InlineKeyboardButton("WEBP", callback_data="conv_webp"),
             InlineKeyboardButton("BMP", callback_data="conv_bmp")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ]
        await query.edit_message_text(
            "🔄 Select output format:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    if data.startswith("conv_"):
        format_name = data.replace("conv_", "").upper()
        await query.edit_message_text(f"⏳ Converting to {format_name}...")
        
        try:
            image_bytes = user_sessions[user_id]['current']
            processed = process_image(image_bytes, "convert", format=format_name)
            
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=io.BytesIO(processed),
                filename=f"converted.{format_name.lower()}",
                caption=f"✅ Converted to {format_name}"
            )
            
            await query.edit_message_text("✅ Conversion complete!")
        except Exception as e:
            logger.error(f"Conversion error: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")
        return
    
    if data == "filter":
        keyboard = [
            [InlineKeyboardButton("⚫ Grayscale", callback_data="filt_grayscale"),
             InlineKeyboardButton("🌫 Blur", callback_data="filt_blur")],
            [InlineKeyboardButton("✨ Sharpen", callback_data="filt_sharpen"),
             InlineKeyboardButton("🔄 Invert", callback_data="filt_invert")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ]
        await query.edit_message_text(
            "🎨 Select filter:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    if data.startswith("filt_"):
        filter_name = data.replace("filt_", "")
        await query.edit_message_text(f"⏳ Applying {filter_name} filter...")
        
        try:
            image_bytes = user_sessions[user_id]['current']
            processed = process_image(image_bytes, filter_name)
            user_sessions[user_id]['current'] = processed
            
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=io.BytesIO(processed),
                caption=f"✅ Applied {filter_name.capitalize()} filter"
            )
            
            await query.edit_message_text("✅ Filter applied!")
        except Exception as e:
            logger.error(f"Filter error: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")
        return
    
    if data == "advanced":
        keyboard = [
            [InlineKeyboardButton("🔄 Rotate 90°", callback_data="adv_rotate90"),
             InlineKeyboardButton("🔄 Rotate 180°", callback_data="adv_rotate180")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ]
        await query.edit_message_text(
            "🔧 Advanced effects:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    if data.startswith("adv_"):
        effect = data.replace("adv_", "")
        await query.edit_message_text(f"⏳ Applying {effect}...")
        
        try:
            image_bytes = user_sessions[user_id]['current']
            
            if effect == "rotate90":
                processed = process_image(image_bytes, "rotate", angle=90)
            elif effect == "rotate180":
                processed = process_image(image_bytes, "rotate", angle=180)
            else:
                await query.edit_message_text("❌ Unknown effect.")
                return
            
            user_sessions[user_id]['current'] = processed
            
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=io.BytesIO(processed),
                caption=f"✅ {effect.replace('rotate', 'Rotated ')}"
            )
            
            await query.edit_message_text("✅ Effect applied!")
        except Exception as e:
            logger.error(f"Advanced effect error: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")
        return
    
    if data == "resize":
        keyboard = [
            [InlineKeyboardButton("256x256", callback_data="res_256_256"),
             InlineKeyboardButton("512x512", callback_data="res_512_512")],
            [InlineKeyboardButton("1024x1024", callback_data="res_1024_1024"),
             InlineKeyboardButton("1280x720", callback_data="res_1280_720")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ]
        await query.edit_message_text(
            "📐 Select size:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    if data.startswith("res_"):
        parts = data.replace("res_", "").split("_")
        width, height = int(parts[0]), int(parts[1])
        
        await query.edit_message_text(f"⏳ Resizing to {width}x{height}...")
        
        try:
            image_bytes = user_sessions[user_id]['current']
            processed = process_image(image_bytes, "resize", width=width, height=height)
            user_sessions[user_id]['current'] = processed
            
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=io.BytesIO(processed),
                caption=f"✅ Resized to {width}x{height}"
            )
            
            await query.edit_message_text("✅ Resize complete!")
        except Exception as e:
            logger.error(f"Resize error: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")
        return
    
    if data == "reset":
        if 'original' in user_sessions[user_id]:
            user_sessions[user_id]['current'] = user_sessions[user_id]['original']
            await query.edit_message_text("✅ Reset to original image!")
        else:
            await query.edit_message_text("❌ No original image to reset to.")
        return
    
    if data == "back":
        keyboard = [
            [InlineKeyboardButton("🖼 Convert", callback_data="convert"),
             InlineKeyboardButton("🎨 Filter", callback_data="filter")],
            [InlineKeyboardButton("🔧 Effects", callback_data="advanced"),
             InlineKeyboardButton("📐 Resize", callback_data="resize")],
            [InlineKeyboardButton("↩️ Reset", callback_data="reset")]
        ]
        await query.edit_message_text(
            "📸 What would you like to do?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors."""
    logger.error(f"Update {update} caused error: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("❌ An error occurred. Please try again.")

# ============================================
# FLASK ROUTES
# ============================================

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "status": "running",
        "bot": "ImageMagicBot",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"}), 200

@app.route('/webhook', methods=['POST'])
async def webhook():
    """Handle Telegram webhook."""
    try:
        update_data = request.get_json(force=True)
        update = Update.de_json(update_data, bot_application.bot)
        await bot_application.process_update(update)
        return '', 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================
# APPLICATION SETUP
# ============================================

def setup_application():
    """Create and configure the bot application."""
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(MessageHandler(filters.Document.IMAGE, handle_image))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)
    
    return application

bot_application = setup_application()

# ============================================
# MAIN ENTRY POINT
# ============================================

if __name__ == '__main__':
    logger.info(f"🚀 Starting ImageMagicBot on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
