import asyncio
from datetime import datetime
from typing import Dict, List
from telegram import Bot
from telegram.constants import ParseMode

from database import Database
from uniqlo_api import UniqloAPI
from config import CHECK_INTERVAL_MINUTES, STORE_IDS

class ProductMonitor:
    def __init__(self, db: Database, api: UniqloAPI):
        self.db = db
        self.api = api
        self.monitoring = False
    
    async def check_product(self, product_db_id: int, user_id: int, bot: Bot = None):
        """Check a single product for price changes across multiple stores"""
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
            
            # Collect all variants from all stores
            all_variants = []
            store_names = {}  # Map store_id to store_name
            
            # Get user's store list (if empty, use default from config)
            user_store_ids = self.db.get_all_user_store_ids(user_id)
            if not user_store_ids:
                user_store_ids = STORE_IDS  # Fallback to default stores
            
            # Loop through all stores
            for store_id in user_store_ids:
                # Get product data from API for this store
                product_data = self.api.get_product_info(product_id, store_id)
                if not product_data:
                    continue
                
                # Get store info
                store_info = self.api.get_store_info(store_id)
                if store_info and isinstance(store_info, dict):
                    store_name = store_info.get('name', f'Store {store_id}')
                else:
                    store_name = f'Store {store_id}'
                
                store_names[store_id] = store_name
                
                # Parse product variants for this store
                variants = self.api.parse_product_data(product_data, store_name)
                
                # Add store_id to each variant
                for variant in variants:
                    variant['store_id'] = store_id
                
                all_variants.extend(variants)
                
                # Small delay between API calls
                await asyncio.sleep(0.5)
            
            # Check if product has any price history (to determine if it's a new product)
            has_history = self.db.has_price_history(product_db_id)
            
            # IMPORTANT: Check if product was on sale BEFORE saving new price history
            was_product_on_sale = self.db.was_product_on_sale(product_db_id) if has_history else False
            
            # Collect all variants that are on sale, grouped by store
            sale_variants_by_store = {}  # {store_id: [variants]}
            
            # Check each variant and save price history
            for variant in all_variants:
                l2_id = variant['l2_id']
                size_code = variant['size_code']
                is_on_sale = variant['is_on_sale']
                base_price = variant['base_price']
                promo_price = variant['promo_price']
                store_id = variant.get('store_id', 'unknown')
                store_name = variant.get('store_name', 'Unknown Store')
                
                # Save current price
                self.db.save_price_history(product_db_id, {
                    'l2_id': l2_id,
                    'size_code': size_code,
                    'color_code': variant.get('color_code', ''),
                    'store_id': store_id,
                    'store_name': store_name,
                    'base_price': base_price,
                    'promo_price': promo_price,
                    'is_on_sale': is_on_sale
                })
                
                # Collect variants that are on sale, grouped by store
                if is_on_sale and base_price > promo_price:
                    if store_id not in sale_variants_by_store:
                        sale_variants_by_store[store_id] = []
                    sale_variants_by_store[store_id].append(variant)
            
            # Count total sale variants across all stores
            total_sale_variants = sum(len(variants) for variants in sale_variants_by_store.values())
            
            # If sale ended (was on sale, now not on sale), clear notification flag
            if was_product_on_sale and total_sale_variants == 0:
                self.db.clear_product_notification_flag(product_db_id)
            
            # Only send notification if:
            # 1. Product has variants on sale in any store
            # 2. Previously was NOT on sale (new sale detected) OR product is new (no history)
            # 3. Max 3 consecutive days, and price must drop to send again after 3 days
            if total_sale_variants > 0:
                # For new products (no history), was_product_on_sale will be False, so is_new_sale = True
                is_new_sale = not was_product_on_sale
                
                # Get the lowest promo price from all sale variants across all stores
                all_sale_variants = []
                for variants in sale_variants_by_store.values():
                    all_sale_variants.extend(variants)
                lowest_promo_price = min(v['promo_price'] for v in all_sale_variants)
                
                # Check if should send notification (max 3 days, price drop logic)
                should_send, reason = self.db.should_send_notification(product_db_id, lowest_promo_price)
                
                print(f"[DEBUG] Product {product_db_id} ({product_name}):")
                print(f"  - total_sale_variants: {total_sale_variants}")
                print(f"  - stores_with_sale: {len(sale_variants_by_store)}")
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
                    # Send ONE notification with all sale variants grouped by store
                    if bot:
                        await self.send_sale_notification(
                            bot,
                            user_id,
                            product_name,
                            sale_variants_by_store
                        )
                    
                    # Mark as notified with price (tracks consecutive days and price)
                    self.db.mark_product_notification_sent(product_db_id, lowest_promo_price)
                else:
                    if not is_new_sale:
                        print(f"[DEBUG] ❌ Not sending notification: not a new sale")
                    else:
                        print(f"[DEBUG] ❌ Not sending notification: {reason}")
            else:
                print(f"[DEBUG] Product {product_db_id}: No variants on sale in any store")
        
        except Exception as e:
            print(f"Error checking product {product_db_id}: {e}")
    
    async def send_sale_notification(
        self,
        bot: Bot,
        user_id: int,
        product_name: str,
        sale_variants_by_store: Dict[str, List[Dict]]
    ):
        """Send sale notification to user (ONE notification per product, grouped by store)"""
        try:
            if not sale_variants_by_store:
                return
            
            # Format prices (assuming IDR)
            def format_price(price):
                return f"Rp {price:,}".replace(',', '.')
            
            # Get all variants for price calculation
            all_variants = []
            for variants in sale_variants_by_store.values():
                all_variants.extend(variants)
            
            # Get min/max prices
            base_price = all_variants[0]['base_price']
            lowest_promo_price = min(v['promo_price'] for v in all_variants)
            highest_promo_price = max(v['promo_price'] for v in all_variants)
            
            # Calculate discount (based on lowest promo price)
            discount = base_price - lowest_promo_price
            discount_percent = int((discount / base_price) * 100)
            
            # Build message
            message = (
                "🎉 **PRODUK SEDANG SALE!**\n\n"
                f"📦 **{product_name}**\n\n"
                f"💰 **Harga Normal:** {format_price(base_price)}\n"
                f"🔥 **Harga Sale:** {format_price(lowest_promo_price)}"
            )
            
            # Add price range if there are different prices across stores
            if lowest_promo_price != highest_promo_price:
                message += f" - {format_price(highest_promo_price)}"
            
            message += f"\n💸 **Diskon:** {format_price(discount)} ({discount_percent}%)\n\n"
            
            # Add store-specific info
            message += "🏪 **Toko yang Tersedia:**\n"
            
            for store_id, variants in sale_variants_by_store.items():
                store_name = variants[0].get('store_name', f'Store {store_id}')
                
                # Collect sizes for this store
                sizes_on_sale = [v.get('size_name', v.get('size_code', '')) for v in variants]
                # Sort by size order
                size_order = {
                    'FREE SIZE': -1, 'XXS': 0, 'XS': 1, 'S': 2, 'M': 3, 
                    'L': 4, 'XL': 5, 'XXL': 6, 'XXXL': 7, '4XL': 8, '5XL': 9
                }
                sorted_sizes = sorted(set(sizes_on_sale), key=lambda x: size_order.get(x.upper(), 99))
                sizes_text = ", ".join(sorted_sizes)
                
                # Get price for this store
                store_promo_price = variants[0]['promo_price']
                
                message += f"\n• **{store_name}**\n"
                message += f"  📏 Size: {sizes_text}\n"
                message += f"  💰 Harga: {format_price(store_promo_price)}\n"
            
            message += f"\n⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            
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

