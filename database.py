import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional

class Database:
    def __init__(self, db_file: str):
        self.db_file = db_file
        self.init_database()
    
    def get_connection(self):
        return sqlite3.connect(self.db_file)
    
    def init_database(self):
        """Initialize database tables"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Products table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_url TEXT NOT NULL,
                product_id TEXT,
                product_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, product_url)
            )
        ''')
        
        # Price history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                l2_id TEXT,
                size_code TEXT,
                color_code TEXT,
                store_id TEXT,
                store_name TEXT,
                base_price INTEGER,
                promo_price INTEGER,
                is_on_sale BOOLEAN,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        ''')
        
        # Notifications sent table (to avoid duplicate notifications)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications_sent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                l2_id TEXT,
                size_code TEXT,
                notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products (id),
                UNIQUE(product_id, l2_id, size_code)
            )
        ''')
        
        # Product notifications table (one notification per product per day, max 3 days)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS product_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER UNIQUE,
                notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_promo_price INTEGER,
                consecutive_days INTEGER DEFAULT 1,
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        ''')
        
        # User stores table (stores that user wants to monitor)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                store_id TEXT NOT NULL,
                store_name TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, store_id)
            )
        ''')
        
        # Migrate existing table if columns don't exist
        try:
            cursor.execute('SELECT consecutive_days FROM product_notifications LIMIT 1')
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            try:
                cursor.execute('ALTER TABLE product_notifications ADD COLUMN last_promo_price INTEGER')
            except sqlite3.OperationalError:
                pass  # Column might already exist
            
            try:
                cursor.execute('ALTER TABLE product_notifications ADD COLUMN consecutive_days INTEGER DEFAULT 1')
            except sqlite3.OperationalError:
                pass  # Column might already exist
        
        conn.commit()
        conn.close()
    
    def add_product(self, user_id: int, product_url: str, product_id: str = None, product_name: str = None) -> int:
        """Add a product to monitor"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Check if product already exists for this user
            cursor.execute('''
                SELECT id FROM products WHERE user_id = ? AND product_url = ?
            ''', (user_id, product_url))
            existing = cursor.fetchone()
            
            if existing:
                # Product already exists, return existing ID
                return existing[0]
            
            # Insert new product
            cursor.execute('''
                INSERT INTO products (user_id, product_url, product_id, product_name)
                VALUES (?, ?, ?, ?)
            ''', (user_id, product_url, product_id, product_name))
            conn.commit()
            product_db_id = cursor.lastrowid
            return product_db_id
        except Exception as e:
            print(f"Error adding product: {e}")
            return None
        finally:
            conn.close()
    
    def get_user_products(self, user_id: int) -> List[Dict]:
        """Get all products monitored by a user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, product_url, product_id, product_name, created_at
            FROM products
            WHERE user_id = ?
        ''', (user_id,))
        
        products = []
        for row in cursor.fetchall():
            products.append({
                'id': row[0],
                'product_url': row[1],
                'product_id': row[2],
                'product_name': row[3],
                'created_at': row[4]
            })
        
        conn.close()
        return products
    
    def get_all_products(self) -> List[Dict]:
        """Get all products being monitored"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, user_id, product_url, product_id, product_name
            FROM products
        ''')
        
        products = []
        for row in cursor.fetchall():
            products.append({
                'id': row[0],
                'user_id': row[1],
                'product_url': row[2],
                'product_id': row[3],
                'product_name': row[4]
            })
        
        conn.close()
        return products
    
    def save_price_history(self, product_id: int, price_data: Dict):
        """Save price history for a product"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO price_history 
            (product_id, l2_id, size_code, color_code, store_id, store_name, base_price, promo_price, is_on_sale)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            product_id,
            price_data.get('l2_id'),
            price_data.get('size_code'),
            price_data.get('color_code'),
            price_data.get('store_id'),
            price_data.get('store_name'),
            price_data.get('base_price'),
            price_data.get('promo_price'),
            price_data.get('is_on_sale', False)
        ))
        
        conn.commit()
        conn.close()
    
    def get_last_price(self, product_id: int, l2_id: str, size_code: str) -> Optional[Dict]:
        """Get the last known price for a product variant"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT base_price, promo_price, is_on_sale, checked_at
            FROM price_history
            WHERE product_id = ? AND l2_id = ? AND size_code = ?
            ORDER BY checked_at DESC
            LIMIT 1
        ''', (product_id, l2_id, size_code))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'base_price': row[0],
                'promo_price': row[1],
                'is_on_sale': bool(row[2]),
                'checked_at': row[3]
            }
        return None
    
    def has_notification_been_sent(self, product_id: int, l2_id: str, size_code: str) -> bool:
        """Check if notification has been sent for this variant"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM notifications_sent
            WHERE product_id = ? AND l2_id = ? AND size_code = ?
        ''', (product_id, l2_id, size_code))
        
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    
    def mark_notification_sent(self, product_id: int, l2_id: str, size_code: str):
        """Mark that notification has been sent"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Use INSERT OR REPLACE to avoid duplicates
        cursor.execute('''
            INSERT OR REPLACE INTO notifications_sent (product_id, l2_id, size_code)
            VALUES (?, ?, ?)
        ''', (product_id, l2_id, size_code))
        
        conn.commit()
        conn.close()
    
    def clear_notification_flag(self, product_id: int, l2_id: str, size_code: str):
        """Clear notification flag when sale ends (allows re-notification if sale comes back)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM notifications_sent
            WHERE product_id = ? AND l2_id = ? AND size_code = ?
        ''', (product_id, l2_id, size_code))
        
        conn.commit()
        conn.close()
    
    def has_price_history(self, product_id: int) -> bool:
        """Check if product has any price history"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM price_history
            WHERE product_id = ?
        ''', (product_id,))
        
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    
    def was_product_on_sale(self, product_id: int) -> bool:
        """Check if product was on sale in the previous check (before current check)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Get distinct check times, ordered by most recent
        cursor.execute('''
            SELECT DISTINCT checked_at FROM price_history
            WHERE product_id = ?
            ORDER BY checked_at DESC
            LIMIT 2
        ''', (product_id,))
        
        times = cursor.fetchall()
        
        if len(times) < 2:
            # Only one check or no checks - this is the first check, so wasn't on sale before
            return False
        
        # Get the previous check time (second most recent)
        previous_check_time = times[1][0]
        
        # Check if any variant was on sale in the previous check
        cursor.execute('''
            SELECT COUNT(*) FROM price_history
            WHERE product_id = ? 
            AND checked_at = ?
            AND is_on_sale = 1
        ''', (product_id, previous_check_time))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count > 0
    
    def get_product_notification_info(self, product_id: int) -> dict:
        """Get notification info for product: consecutive_days, last_promo_price, last_notified_date"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT consecutive_days, last_promo_price, DATE(notified_at) as last_date
            FROM product_notifications
            WHERE product_id = ?
        ''', (product_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'consecutive_days': row[0] or 1,
                'last_promo_price': row[1],
                'last_date': row[2]
            }
        return {
            'consecutive_days': 0,
            'last_promo_price': None,
            'last_date': None
        }
    
    def should_send_notification(self, product_id: int, current_promo_price: int):
        """
        Check if should send notification based on:
        - Max 3 consecutive days
        - Price must be lower than last notified price (or first time)
        Returns: (should_send, reason)
        """
        info = self.get_product_notification_info(product_id)
        consecutive_days = info['consecutive_days']
        last_promo_price = info['last_promo_price']
        last_date = info['last_date']
        
        from datetime import datetime
        today = datetime.now().date().isoformat()
        
        # If never notified, can send
        if last_date is None:
            return True, "first_notification"
        
        # If notified today already, don't send
        if last_date == today:
            return False, "already_notified_today"
        
        # Check if consecutive days (yesterday)
        from datetime import datetime, timedelta
        yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
        is_consecutive = last_date == yesterday
        
        # If not consecutive (gap day), reset counter
        if not is_consecutive:
            return True, "new_sale_after_gap"
        
        # If already 3 consecutive days with same price, don't send
        if consecutive_days >= 3:
            if last_promo_price == current_promo_price:
                return False, "max_3_days_same_price"
            # But if price dropped, reset and send
            if current_promo_price < last_promo_price:
                return True, "price_dropped_reset"
            return False, "max_3_days_reached"
        
        # If price is same as last time, continue counting
        if last_promo_price == current_promo_price:
            return True, "same_price_continue"
        
        # If price dropped (lower), reset counter and send
        if current_promo_price < last_promo_price:
            return True, "price_dropped_reset"
        
        # If price increased, don't send
        return False, "price_increased"
    
    def mark_product_notification_sent(self, product_id: int, promo_price: int):
        """Mark that notification has been sent for this product today with price"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Get current info
        info = self.get_product_notification_info(product_id)
        consecutive_days = info['consecutive_days']
        last_date = info['last_date']
        last_promo_price = info['last_promo_price']
        
        from datetime import datetime, timedelta
        today = datetime.now().date().isoformat()
        yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
        
        # Calculate new consecutive days
        if last_date is None:
            # First notification
            new_consecutive_days = 1
        elif last_date == yesterday:
            # Consecutive day
            if last_promo_price == promo_price:
                # Same price, continue counting
                new_consecutive_days = consecutive_days + 1
            else:
                # Different price, reset counter
                new_consecutive_days = 1
        else:
            # Gap day, reset counter
            new_consecutive_days = 1
        
        # Update or insert with current timestamp, price, and consecutive days
        cursor.execute('''
            INSERT OR REPLACE INTO product_notifications 
            (product_id, notified_at, last_promo_price, consecutive_days)
            VALUES (?, CURRENT_TIMESTAMP, ?, ?)
        ''', (product_id, promo_price, new_consecutive_days))
        
        conn.commit()
        conn.close()
    
    def clear_product_notification_flag(self, product_id: int):
        """Clear notification flag when sale ends (allows re-notification if sale comes back)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM product_notifications
            WHERE product_id = ?
        ''', (product_id,))
        
        conn.commit()
        conn.close()
    
    def cleanup_old_notifications(self):
        """Clean up notifications older than 1 day (optional maintenance)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Delete notifications older than 1 day
        cursor.execute('''
            DELETE FROM product_notifications
            WHERE DATE(notified_at) < DATE('now', '-1 day')
        ''')
        
        conn.commit()
        conn.close()
    
    def reset_today_notifications(self):
        """Reset all notifications for today (allow re-notification today)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Delete notifications sent today
        cursor.execute('''
            DELETE FROM product_notifications
            WHERE DATE(notified_at) = DATE('now')
        ''')
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        return deleted
    
    def reset_all_notifications(self):
        """Reset all notifications (clear all notification history)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM product_notifications')
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        return deleted
    
    def delete_product(self, user_id: int, product_id: int) -> bool:
        """Delete a product from monitoring"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM products WHERE id = ? AND user_id = ?
        ''', (product_id, user_id))
        
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted
    
    # User stores management
    def add_user_store(self, user_id: int, store_id: str, store_name: str = None) -> bool:
        """Add a store to user's monitoring list"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO user_stores (user_id, store_id, store_name)
                VALUES (?, ?, ?)
            ''', (user_id, store_id, store_name))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error adding user store: {e}")
            return False
        finally:
            conn.close()
    
    def get_user_stores(self, user_id: int) -> List[Dict]:
        """Get all stores monitored by a user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT store_id, store_name, added_at
            FROM user_stores
            WHERE user_id = ?
            ORDER BY added_at DESC
        ''', (user_id,))
        
        stores = []
        for row in cursor.fetchall():
            stores.append({
                'store_id': row[0],
                'store_name': row[1],
                'added_at': row[2]
            })
        
        conn.close()
        return stores
    
    def delete_user_store(self, user_id: int, store_id: str) -> bool:
        """Remove a store from user's monitoring list"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM user_stores WHERE user_id = ? AND store_id = ?
        ''', (user_id, store_id))
        
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted
    
    def get_all_user_store_ids(self, user_id: int) -> List[str]:
        """Get list of store IDs for a user"""
        stores = self.get_user_stores(user_id)
        return [store['store_id'] for store in stores]

