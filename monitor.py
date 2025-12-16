import asyncio
from datetime import datetime
from typing import Dict, List
from telegram import Bot
from telegram.constants import ParseMode

from database import Database
from uniqlo_api import UniqloAPI
from config import CHECK_INTERVAL_MINUTES

class ProductMonitor:
    def __init__(self, db: Database, api: UniqloAPI):
        self.db = db
        self.api = api
        self.monitoring = False
    
    async def check_product(self, product_db_id: int, user_id: int, bot: Bot = None):
        """Check a single product for price changes"""
        try:
            # Get product info from database
            products = self.db.get_all_products()
            product = next((p for p in products if p['id'] == product_db_id), None)
            
            if not product:
                return
            
            product_id = product.get('product_id')
            product_url = product['product_url']
            product_name = product.get('product_name', 'Produk Tanpa Nama')
            
            if not product_id:
                # Try to extract from URL
                product_id = self.api.extract_product_id_from_url(product_url)
                if not product_id:
                    return
            
            # Get product data from API
            product_data = self.api.get_product_info(product_id)
            if not product_data:
                return
            
            # Get store info (using default store for now)
            store_info = self.api.get_store_info("113757")
            if store_info and isinstance(store_info, dict):
                store_name = store_info.get('name', 'Uniqlo')
            else:
                store_name = 'Uniqlo'
            
            # Parse product variants
            variants = self.api.parse_product_data(product_data, store_name)
            
            # Check if product has any price history (to determine if it's a new product)
            has_history = self.db.has_price_history(product_db_id)
            
            # IMPORTANT: Check if product was on sale BEFORE saving new price history
            was_product_on_sale = self.db.was_product_on_sale(product_db_id) if has_history else False
            
            # Collect all variants that are on sale
            sale_variants = []
            
            # Check each variant and save price history
            for variant in variants:
                l2_id = variant['l2_id']
                size_code = variant['size_code']
                is_on_sale = variant['is_on_sale']
                base_price = variant['base_price']
                promo_price = variant['promo_price']
                
                # Save current price
                self.db.save_price_history(product_db_id, {
                    'l2_id': l2_id,
                    'size_code': size_code,
                    'color_code': variant.get('color_code', ''),
                    'store_id': '113757',
                    'store_name': store_name,
                    'base_price': base_price,
                    'promo_price': promo_price,
                    'is_on_sale': is_on_sale
                })
                
                # Collect variants that are on sale
                if is_on_sale and base_price > promo_price:
                    sale_variants.append(variant)
            
            # If sale ended (was on sale, now not on sale), clear notification flag
            if was_product_on_sale and len(sale_variants) == 0:
                self.db.clear_product_notification_flag(product_db_id)
            
            # Only send notification if:
            # 1. Product has variants on sale
            # 2. Previously was NOT on sale (new sale detected) OR product is new (no history)
            # 3. Max 3 consecutive days, and price must drop to send again after 3 days
            if len(sale_variants) > 0:
                # For new products (no history), was_product_on_sale will be False, so is_new_sale = True
                is_new_sale = not was_product_on_sale
                
                # Get the lowest promo price from all sale variants
                lowest_promo_price = min(v['promo_price'] for v in sale_variants)
                
                # Check if should send notification (max 3 days, price drop logic)
                should_send, reason = self.db.should_send_notification(product_db_id, lowest_promo_price)
                
                print(f"[DEBUG] Product {product_db_id} ({product_name}):")
                print(f"  - sale_variants: {len(sale_variants)}")
                print(f"  - has_history: {has_history}")
                print(f"  - was_on_sale: {was_product_on_sale}")
                print(f"  - is_new_sale: {is_new_sale}")
                print(f"  - lowest_promo_price: {lowest_promo_price}")
                print(f"  - should_send: {should_send}, reason: {reason}")
                
                # Send notification if:
                # - It's a new sale (wasn't on sale before) OR it's a new product
                # - And should_send is True (max 3 days, price drop logic)
                if is_new_sale and should_send:
                    print(f"[DEBUG] ✅ Sending notification for product {product_db_id} ({reason})")
                    # Send ONE notification with all sale variants
                    if bot:
                        await self.send_sale_notification(
                            bot,
                            user_id,
                            product_name,
                            sale_variants,
                            store_name
                        )
                    
                    # Mark as notified with price (tracks consecutive days and price)
                    self.db.mark_product_notification_sent(product_db_id, lowest_promo_price)
                else:
                    if not is_new_sale:
                        print(f"[DEBUG] ❌ Not sending notification: not a new sale")
                    else:
                        print(f"[DEBUG] ❌ Not sending notification: {reason}")
            else:
                print(f"[DEBUG] Product {product_db_id}: No variants on sale")
        
        except Exception as e:
            print(f"Error checking product {product_db_id}: {e}")
    
    async def send_sale_notification(
        self,
        bot: Bot,
        user_id: int,
        product_name: str,
        sale_variants: List[Dict],
        store_name: str
    ):
        """Send sale notification to user (ONE notification per product)"""
        try:
            if not sale_variants:
                return
            
            # Format prices (assuming IDR)
            def format_price(price):
                return f"Rp {price:,}".replace(',', '.')
            
            # Get first variant for base info (all should have similar pricing)
            first_variant = sale_variants[0]
            base_price = first_variant['base_price']
            promo_price = first_variant['promo_price']
            
            # Calculate discount
            discount = base_price - promo_price
            discount_percent = int((discount / base_price) * 100)
            
            # Collect all sizes on sale (use size_name if available, fallback to size_code)
            sizes_on_sale = [v.get('size_name', v.get('size_code', '')) for v in sale_variants]
            # Sort by size order: XXS, XS, S, M, L, XL, XXL, XXXL, etc.
            size_order = {
                'FREE SIZE': -1, 'XXS': 0, 'XS': 1, 'S': 2, 'M': 3, 
                'L': 4, 'XL': 5, 'XXL': 6, 'XXXL': 7, '4XL': 8, '5XL': 9
            }
            sorted_sizes = sorted(set(sizes_on_sale), key=lambda x: size_order.get(x.upper(), 99))
            sizes_text = ", ".join(sorted_sizes)
            
            message = (
                "🎉 **PRODUK SEDANG SALE!**\n\n"
                f"📦 **{product_name}**\n"
                f"📏 **Size Tersedia:** {sizes_text}\n"
                f"🏪 **Toko:** {store_name}\n\n"
                f"💰 **Harga Sebelum Sale:** {format_price(base_price)}\n"
                f"🔥 **Harga Setelah Sale:** {format_price(promo_price)}\n"
                f"💸 **Diskon:** {format_price(discount)} ({discount_percent}%)\n\n"
                f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            )
            
            await bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            print(f"Error sending notification: {e}")
    
    async def check_all_products(self, bot: Bot):
        """Check all products being monitored"""
        products = self.db.get_all_products()
        
        for product in products:
            try:
                await self.check_product(product['id'], product['user_id'], bot)
                # Small delay between checks
                await asyncio.sleep(2)
            except Exception as e:
                print(f"Error checking product {product['id']}: {e}")
    
    def start_monitoring(self, application):
        """Start periodic monitoring task"""
        if self.monitoring:
            return
        
        self.monitoring = True
        
        async def monitoring_task(context):
            try:
                bot = context.bot
                await self.check_all_products(bot)
            except Exception as e:
                print(f"Error in monitoring task: {e}")
        
        # Use job queue for periodic task
        job_queue = application.job_queue
        if job_queue:
            job_queue.run_repeating(
                monitoring_task,
                interval=CHECK_INTERVAL_MINUTES * 60,
                first=CHECK_INTERVAL_MINUTES * 60
            )
            print(f"Monitoring started - checking every {CHECK_INTERVAL_MINUTES} minutes")
        else:
            print("Warning: Job queue not available, monitoring may not work properly")

