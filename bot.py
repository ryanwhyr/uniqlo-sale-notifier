import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode
import re
from typing import List

from config import TELEGRAM_BOT_TOKEN, CHECK_INTERVAL_MINUTES
from database import Database
from uniqlo_api import UniqloAPI
from monitor import ProductMonitor

# Setup logging - reduce spam from telegram library
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.WARNING  # Only show warnings and errors, not info/debug
)
# Suppress telegram library verbose logging
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Initialize components
db = Database('uniqlo_monitor.db')
api = UniqloAPI()
monitor = ProductMonitor(db, api)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    keyboard = [
        [InlineKeyboardButton("➕ Tambah Produk", callback_data='add_product')],
        [InlineKeyboardButton("📋 Daftar Produk", callback_data='list_products')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "👋 Selamat datang di Bot Monitor Sale Uniqlo!\n\n"
        "Bot ini akan membantu Anda memantau produk Uniqlo yang sedang sale.\n\n"
        "Fitur:\n"
        "• ➕ Tambah produk untuk dipantau\n"
        "• 📋 Lihat daftar produk yang dipantau\n"
        "• 🔔 Notifikasi otomatis saat produk sale\n"
        "• 📊 Info lengkap: nama, size, toko, harga sebelum & sesudah sale\n\n"
        "Pilih menu di bawah:"
    )
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation and return to main menu."""
    # Clear any waiting state
    context.user_data['waiting_for_url'] = False
    
    # Show main menu
    keyboard = [
        [InlineKeyboardButton("➕ Tambah Produk", callback_data='add_product')],
        [InlineKeyboardButton("📋 Daftar Produk", callback_data='list_products')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "❌ Operasi dibatalkan.\n\nPilih menu di bawah:",
        reply_markup=reply_markup
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if query.data == 'add_product':
        await query.edit_message_text(
            "📝 **Tambah Produk Baru**\n\n"
            "Silakan kirim link produk Uniqlo yang ingin dipantau.\n\n"
            "Contoh:\n"
            "`https://www.uniqlo.com/id/id/products/E479678-000/00`\n\n"
            "Atau kirim /cancel untuk membatalkan.",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data['waiting_for_url'] = True
        
    elif query.data == 'list_products':
        products = db.get_user_products(user_id)
        
        if not products:
            await query.edit_message_text(
                "📋 **Daftar Produk**\n\n"
                "Anda belum menambahkan produk untuk dipantau.\n\n"
                "Klik '➕ Tambah Produk' untuk menambahkan produk.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            text = "📋 **Daftar Produk yang Dipantau**\n\n"
            keyboard = []
            
            for i, product in enumerate(products, 1):
                product_name = product.get('product_name', 'Produk Tanpa Nama')
                product_url = product['product_url']
                # Shorten URL for display
                short_url = product_url.split('/products/')[-1] if '/products/' in product_url else product_url[:50]
                text += f"{i}. {product_name}\n   `{short_url}`\n\n"
                keyboard.append([InlineKeyboardButton(
                    f"❌ Hapus {i}",
                    callback_data=f"delete_{product['id']}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data='back_to_menu')])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif query.data == 'back_to_menu':
        keyboard = [
            [InlineKeyboardButton("➕ Tambah Produk", callback_data='add_product')],
            [InlineKeyboardButton("📋 Daftar Produk", callback_data='list_products')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "👋 **Menu Utama**\n\nPilih menu di bawah:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif query.data.startswith('delete_'):
        product_id = int(query.data.split('_')[1])
        deleted = db.delete_product(user_id, product_id)
        
        if deleted:
            await query.answer("✅ Produk berhasil dihapus!", show_alert=True)
            # Refresh list
            products = db.get_user_products(user_id)
            if not products:
                await query.edit_message_text(
                    "📋 **Daftar Produk**\n\n"
                    "Anda belum menambahkan produk untuk dipantau.",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                # Rebuild list
                text = "📋 **Daftar Produk yang Dipantau**\n\n"
                keyboard = []
                for i, product in enumerate(products, 1):
                    product_name = product.get('product_name', 'Produk Tanpa Nama')
                    product_url = product['product_url']
                    short_url = product_url.split('/products/')[-1] if '/products/' in product_url else product_url[:50]
                    text += f"{i}. {product_name}\n   `{short_url}`\n\n"
                    keyboard.append([InlineKeyboardButton(
                        f"❌ Hapus {i}",
                        callback_data=f"delete_{product['id']}"
                    )])
                keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data='back_to_menu')])
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages."""
    user_id = update.message.from_user.id
    text = update.message.text
    
    # Check if user is waiting to add a product
    if context.user_data.get('waiting_for_url'):
        if text.lower() == '/cancel':
            context.user_data['waiting_for_url'] = False
            # Return to main menu
            keyboard = [
                [InlineKeyboardButton("➕ Tambah Produk", callback_data='add_product')],
                [InlineKeyboardButton("📋 Daftar Produk", callback_data='list_products')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "❌ Penambahan produk dibatalkan.\n\nPilih menu di bawah:",
                reply_markup=reply_markup
            )
            return
        
        # Validate URL
        if not ('uniqlo.com' in text and '/products/' in text):
            await update.message.reply_text(
                "❌ URL tidak valid. Pastikan URL adalah link produk Uniqlo.\n\n"
                "Contoh: https://www.uniqlo.com/id/id/products/E479678-000/00\n\n"
                "Kirim /cancel untuk membatalkan."
            )
            return
        
        # Extract product ID
        product_id = api.extract_product_id_from_url(text)
        if not product_id:
            await update.message.reply_text(
                "❌ Tidak dapat mengekstrak ID produk dari URL.\n"
                "Pastikan URL valid dan coba lagi.\n\n"
                "Kirim /cancel untuk membatalkan."
            )
            return
        
        # Get product name
        product_name = api.get_product_name_from_url(text)
        if not product_name:
            product_name = f"Produk {product_id}"
        
        # Add product to database
        db_id = db.add_product(user_id, text, product_id, product_name)
        
        if db_id:
            context.user_data['waiting_for_url'] = False
            await update.message.reply_text(
                f"✅ **Produk berhasil ditambahkan!**\n\n"
                f"📦 **{product_name}**\n"
                f"🔗 `{text}`\n\n"
                f"Bot akan memantau produk ini dan mengirim notifikasi saat ada sale.\n"
                f"Memeriksa status produk saat ini...",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Do initial check (this will send notification if product is already on sale)
            try:
                await monitor.check_product(db_id, user_id, context.bot)
                await asyncio.sleep(1)  # Small delay to ensure notification is sent
            except Exception as e:
                print(f"Error in initial check: {e}")
                await update.message.reply_text(
                    "⚠️ Produk berhasil ditambahkan, tapi terjadi error saat pengecekan awal.\n"
                    "Bot akan tetap memantau produk ini secara berkala."
                )
        else:
            await update.message.reply_text(
                "⚠️ Produk ini sudah ada dalam daftar pemantauan Anda."
            )
    else:
        # Regular message - show menu
        keyboard = [
            [InlineKeyboardButton("➕ Tambah Produk", callback_data='add_product')],
            [InlineKeyboardButton("📋 Daftar Produk", callback_data='list_products')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "Pilih menu di bawah:",
            reply_markup=reply_markup
        )

async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all products being monitored."""
    user_id = update.message.from_user.id
    products = db.get_user_products(user_id)
    
    if not products:
        await update.message.reply_text(
            "📋 Anda belum menambahkan produk untuk dipantau.\n\n"
            "Gunakan /add untuk menambahkan produk."
        )
    else:
        text = "📋 **Daftar Produk yang Dipantau**\n\n"
        for i, product in enumerate(products, 1):
            product_name = product.get('product_name', 'Produk Tanpa Nama')
            text += f"{i}. {product_name}\n"
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def check_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually check all products for sales."""
    user_id = update.message.from_user.id
    products = db.get_user_products(user_id)
    
    if not products:
        await update.message.reply_text(
            "📋 Anda belum menambahkan produk untuk dipantau."
        )
        return
    
    await update.message.reply_text(
        f"🔍 Memeriksa {len(products)} produk...\n"
        "Mohon tunggu sebentar..."
    )
    
    checked = 0
    for product in products:
        try:
            await monitor.check_product(product['id'], user_id, context.bot)
            checked += 1
            await asyncio.sleep(1)  # Small delay between checks
        except Exception as e:
            print(f"Error checking product {product['id']}: {e}")
    
    await update.message.reply_text(
        f"✅ Selesai memeriksa {checked} produk.\n"
        "Jika ada produk yang sale, Anda akan menerima notifikasi."
    )

async def reset_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset notifications for today (allow re-notification)"""
    user_id = update.message.from_user.id
    
    # Reset notifications for today
    deleted = db.reset_today_notifications()
    
    await update.message.reply_text(
        f"✅ **Notifikasi hari ini telah direset!**\n\n"
        f"🗑️ {deleted} notifikasi dihapus.\n"
        f"🔔 Bot akan mengirim notifikasi lagi jika produk sale."
    )

# Global flag to prevent duplicate startup notifications
_startup_notification_sent = False

async def send_startup_notification(application):
    """Send startup notification to all users with monitored products and check products immediately"""
    global _startup_notification_sent
    
    # Prevent duplicate notifications if function is called multiple times
    if _startup_notification_sent:
        print("Startup notification already sent, skipping...")
        return
    
    try:
        # Get all unique users who have products
        all_products = db.get_all_products()
        
        if not all_products:
            print("Tidak ada produk yang dipantau. Bot siap menerima produk baru.")
            _startup_notification_sent = True
            return
        
        # Group products by user_id (ensure unique users)
        user_products = {}
        for product in all_products:
            user_id = product['user_id']
            if user_id not in user_products:
                user_products[user_id] = []
            user_products[user_id].append(product)
        
        bot = application.bot
        
        # Send notification to each user ONCE and check products
        for user_id, products in user_products.items():
            try:
                # Remove duplicates by product_id
                unique_products = {}
                for product in products:
                    prod_id = product.get('id')
                    if prod_id and prod_id not in unique_products:
                        unique_products[prod_id] = product
                
                products = list(unique_products.values())
                
                product_list = ""
                for i, product in enumerate(products, 1):
                    product_name = product.get('product_name', 'Produk Tanpa Nama')
                    product_list += f"{i}. {product_name}\n"
                
                message = (
                    "✅ **Bot Monitor Sale Uniqlo telah aktif!**\n\n"
                    f"📦 **Produk yang dipantau ({len(products)}):**\n"
                    f"{product_list}\n"
                    f"🔄 Bot akan mengecek setiap {CHECK_INTERVAL_MINUTES} menit.\n"
                    f"🔔 Anda akan mendapat notifikasi saat produk sale.\n\n"
                    f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
                )
                
                await bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # Immediately check all products for this user
                print(f"Checking {len(products)} products for user {user_id}...")
                for product in products:
                    try:
                        await monitor.check_product(product['id'], user_id, bot)
                        await asyncio.sleep(1)  # Small delay between checks
                    except Exception as e:
                        print(f"Error checking product {product['id']}: {e}")
                
                # Small delay between users
                await asyncio.sleep(0.5)
                
            except Exception as e:
                print(f"Error sending startup notification to user {user_id}: {e}")
        
        _startup_notification_sent = True
        print(f"Startup notification sent and products checked for {len(user_products)} user(s)")
        
    except Exception as e:
        print(f"Error in send_startup_notification: {e}")
        _startup_notification_sent = True  # Set flag even on error to prevent retry loops

def main():
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN tidak ditemukan!")
        print("Buat file .env dan tambahkan: TELEGRAM_BOT_TOKEN=your_token_here")
        return
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list", list_products))
    application.add_handler(CommandHandler("check", check_products))
    application.add_handler(CommandHandler("reset", reset_notifications))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start monitoring task
    monitor.start_monitoring(application)
    
    # Setup post_init hook for startup notification
    async def post_init(app: Application):
        """Run after bot is initialized"""
        await asyncio.sleep(1)  # Small delay to ensure bot is ready
        print("Bot sedang berjalan...")
        print("Mengirim notifikasi startup ke semua user...")
        await send_startup_notification(app)
        print("Bot siap menerima perintah!")
    
    application.post_init = post_init
    
    # Run bot
    print("Memulai bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

