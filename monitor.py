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
                    print(f"[ERROR] Cannot extract product ID from URL: {product_url}")
                    return
            
            print(f"[DEBUG] Checking product: {product_name} (ID: {product_id})")
            
            # Collect all variants from all stores
            all_variants = []
            store_names = {}  # Map store_id to store_name
            
            # Get user's store list (if empty, use default from config)
            user_store_ids = self.db.get_all_user_store_ids(user_id)
            if not user_store_ids:
                user_store_ids = STORE_IDS  # Fallback to default stores
            
            print(f"[DEBUG] Checking product {product_db_id} across {len(user_store_ids)} stores")
            
            # Loop through all stores
            for store_id in user_store_ids:
                try:
                    # Get product data from API for this store
                    product_data = self.api.get_product_info(product_id, store_id)
                    if not product_data:
                        print(f"[DEBUG] No product data for store {store_id}")
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
                    
                    if not variants:
                        print(f"[DEBUG] No variants found for store {store_id}")
                        continue
                    
                    # Validate store-specific stock using /l2s/{l2_id}/stores endpoint (ACCURATE)
                    # This endpoint matches website behavior and shows real offline store stock
                    validated_variants = []
                    for variant in variants:
                        l2_id = variant.get('l2_id')
                        size_name = variant.get('size_name', 'Unknown')
                        color_code = variant.get('color_code', '')
                        
                        # Try to get accurate store stock status
                        store_stock_status = self.api.get_store_specific_stock(l2_id, store_id)
                        
                        if store_stock_status and store_stock_status in ['IN_STOCK', 'LOW_STOCK']:
                            # Variant is actually available at this offline store
                            variant['store_id'] = store_id
                            variant['store_stock_status'] = store_stock_status
                            validated_variants.append(variant)
                            print(f"[VALIDATED] ✅ {size_name} {color_code} available at {store_name} ({store_stock_status})")
                        elif store_stock_status == 'OUT_OF_STOCK':
                            # Confirmed out of stock at this store
                            print(f"[VALIDATED] ❌ {size_name} {color_code} OUT_OF_STOCK at {store_name}")
                        else:
                            # Endpoint failed (400 error) - fallback: trust API response with storeId
                            print(f"[VALIDATED] ⚠️ {size_name} {color_code} - endpoint failed, trusting API response")
                            variant['store_id'] = store_id
                            validated_variants.append(variant)
                        
                        # Small delay to avoid rate limiting
                        await asyncio.sleep(0.3)
                    
                    all_variants.extend(validated_variants)
                    print(f"[DEBUG] Found {len(validated_variants)}/{len(variants)} variants actually in stock at store {store_id}")
                    
                    # Small delay between API calls
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"[ERROR] Error processing store {store_id}: {e}")
                    continue
            
            # Check if we found any variants (in stock)
            if not all_variants:
                print(f"[DEBUG] No variants found for product {product_db_id} in any store")
                
                # Check online availability
                online_check = self.api.check_online_availability(product_id)
                online_available = online_check.get('available', False)
                online_sizes = online_check.get('sizes', [])
                
                # Send out of stock notification if bot is provided
                if bot:
                    print(f"[DEBUG] Sending out of stock notification for product {product_db_id}")
                    try:
                        online_status = ""
                        if online_available and online_sizes:
                            sizes_str = ", ".join(sorted(set(online_sizes)))
                            online_status = f"🌐 **Tersedia di Online Store:** {sizes_str} ✅\n"
                        else:
                            online_status = f"🌐 **Tidak tersedia di Online Store** ❌\n"
                        
                        message = (
                            f"⚠️ **PRODUK TIDAK TERSEDIA DI TOKO OFFLINE**\n\n"
                            f"📦 **{product_name}**\n\n"
                            f"❌ Produk saat ini tidak tersedia di semua toko offline yang dipantau.\n\n"
                            f"{online_status}\n"
                            f"🔔 Bot akan terus memantau dan mengirim notifikasi saat:\n"
                            f"   • Produk kembali tersedia di toko offline\n"
                            f"   • Produk sedang sale\n\n"
                            f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}"
                        )
                        await bot.send_message(
                            chat_id=user_id,
                            text=message,
                            parse_mode=ParseMode.MARKDOWN
                        )
                        print(f"[DEBUG] Out of stock notification sent successfully (online: {online_available})")
                    except Exception as e:
                        print(f"[ERROR] Failed to send out of stock notification: {e}")
                
                return {"status": "out_of_stock", "message": "Produk tidak tersedia di semua toko", "online_available": online_available}
            
            print(f"[DEBUG] Total variants found: {len(all_variants)}")
            
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
                            product_id,
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
            
            # Return success status
            return {"status": "success", "has_sale": total_sale_variants > 0}
        
        except Exception as e:
            print(f"Error checking product {product_db_id}: {e}")
            return {"status": "error", "message": str(e)}
    
    async def send_sale_notification(
        self,
        bot: Bot,
        user_id: int,
        product_name: str,
        product_id: str,
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
            
            # Check online availability
            online_check = self.api.check_online_availability(product_id)
            online_available = online_check.get('available', False)
            online_sizes = online_check.get('sizes', [])
            
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
            
            # Add online availability status with sizes
            if online_available and online_sizes:
                sizes_str = ", ".join(sorted(set(online_sizes)))
                message += f"🌐 **Tersedia di Online Store:** {sizes_str} ✅\n\n"
            else:
                message += "🌐 **Tidak tersedia di Online Store** ❌\n\n"
            
            # Add store-specific info
            message += "🏪 **Toko Offline yang Tersedia:**\n"
            
            for store_id, variants in sale_variants_by_store.items():
                store_name = variants[0].get('store_name', f'Store {store_id}')
                
                # Collect sizes for this store
                sizes_on_sale = [v.get('size_name', v.get('size_code', '')) for v in variants]
                
                # Smart size sorting function
                def sort_size(size_str):
                    # Standard sizes
                    size_order = {
                        'FREE SIZE': -1, 'XXS': 0, 'XS': 1, 'S': 2, 'M': 3, 
                        'L': 4, 'XL': 5, 'XXL': 6, 'XXXL': 7, '4XL': 8, '5XL': 9
                    }
                    
                    size_upper = size_str.upper()
                    
                    # If it's a standard size, use the predefined order
                    if size_upper in size_order:
                        return (0, size_order[size_upper])
                    
                    # If it's an inch size (e.g., 27", 28", etc.)
                    if '"' in size_str or 'INCH' in size_upper:
                        import re
                        match = re.search(r'(\d+)', size_str)
                        if match:
                            return (1, int(match.group(1)))
                    
                    # If it's a cm size (e.g., 100cm, 110cm, etc.)
                    if 'CM' in size_upper:
                        import re
                        match = re.search(r'(\d+)', size_str)
                        if match:
                            return (2, int(match.group(1)))
                    
                    # If it's a pure number (e.g., 027, 028, etc.)
                    if size_str.isdigit():
                        return (3, int(size_str))
                    
                    # Default: alphabetical
                    return (99, size_str)
                
                sorted_sizes = sorted(set(sizes_on_sale), key=sort_size)
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

