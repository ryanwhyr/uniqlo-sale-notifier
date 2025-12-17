import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')

# Uniqlo API Configuration
UNIQLO_BASE_URL = 'https://www.uniqlo.com'
UNIQLO_API_BASE = 'https://www.uniqlo.com/id/api/commerce/v5/id'

# Database Configuration
DATABASE_FILE = 'uniqlo_monitor.db'

# Monitoring Configuration
CHECK_INTERVAL_MINUTES = 30  # Check every 30 minutes

# Store IDs to monitor (add more store IDs as needed)
STORE_IDS = [
    "113757",  # UNIQLO TUNJUNGAN PLAZA 3
    "10104199",  # Store lain (tambahkan store ID yang ingin dipantau)
    # Tambahkan store ID lainnya di sini
    # Contoh: "12345", "67890"
]

