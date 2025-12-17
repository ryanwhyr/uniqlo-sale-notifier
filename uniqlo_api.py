import requests
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs
from config import UNIQLO_API_BASE, UNIQLO_BASE_URL

class UniqloAPI:
    def __init__(self):
        self.base_url = UNIQLO_API_BASE
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'X-Fr-Clientid': 'uq.id.web-spa'
        })
    
    def extract_product_id_from_url(self, url: str) -> Optional[str]:
        """Extract product ID from Uniqlo product URL"""
        # Pattern: /id/id/products/{PRODUCT_ID}-{COLOR_CODE}/{SIZE_CODE}
        # Example: /id/id/products/E479678-000/00
        pattern = r'/products/([A-Z0-9]+-\d{3})'
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        return None
    
    def get_product_info(self, product_id: str, store_id: str = "113757") -> Optional[Dict]:
        """Get product information including prices and stock"""
        try:
            # Get product prices and stock
            url = f"{self.base_url}/products/{product_id}/price-groups/00/l2s"
            params = {
                'withPrices': 'true',
                'withStocks': 'true',
                'storeId': store_id,
                'includePreviousPrice': 'false',
                'httpFailure': 'true'
            }
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') == 'ok' and 'result' in data:
                return data['result']
            return None
        except Exception as e:
            print(f"Error fetching product info: {e}")
            return None
    
    def get_store_info(self, store_id: str) -> Optional[Dict]:
        """Get store information"""
        try:
            url = f"{self.base_url}/stores/{store_id}"
            params = {
                'includeClosed': 'false',
                'httpFailure': 'true'
            }
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') == 'ok' and 'result' in data:
                return data['result']
            return None
        except Exception as e:
            print(f"Error fetching store info: {e}")
            return None
    
    def search_stores(self, city: str = None) -> List[Dict]:
        """Search for stores, optionally filter by city"""
        try:
            url = f"{self.base_url}/stores"
            params = {
                'includeClosed': 'false',
                'httpFailure': 'true'
            }
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') == 'ok' and 'result' in data:
                stores = data['result']
                
                # If city filter is provided, filter stores by city name
                if city:
                    city_lower = city.lower()
                    filtered_stores = []
                    for store in stores:
                        # Check various fields that might contain city info
                        store_city = store.get('city', '').lower()
                        store_name = store.get('name', '').lower()
                        store_address = store.get('address', '').lower()
                        
                        if (city_lower in store_city or 
                            city_lower in store_name or 
                            city_lower in store_address):
                            filtered_stores.append(store)
                    
                    return filtered_stores
                
                return stores
            return []
        except Exception as e:
            print(f"Error searching stores: {e}")
            return []
    
    def parse_product_data(self, product_data: Dict, store_name: str = "Uniqlo") -> List[Dict]:
        """Parse product data into a list of variants with prices"""
        variants = []
        
        if not product_data:
            return variants
        
        # Mapping displayCode to size name
        SIZE_CODE_MAP = {
            '00': 'FREE SIZE',
            '001': 'XXS',
            '002': 'XS',
            '003': 'S',
            '004': 'M',
            '005': 'L',
            '006': 'XL',
            '007': 'XXL',
            '008': 'XXXL',
            '009': '4XL',
            '010': '5XL',
        }
        
        l2s = product_data.get('l2s', [])
        prices = product_data.get('prices', {})
        stocks = product_data.get('stocks', {})
        
        for l2 in l2s:
            l2_id = l2.get('l2Id')
            size_obj = l2.get('size', {})
            size_code = size_obj.get('displayCode', '')
            # Try multiple fields to get size name
            size_name = (
                size_obj.get('name') or 
                size_obj.get('displayName') or 
                size_obj.get('label') or 
                SIZE_CODE_MAP.get(size_code, size_code)
            )
            color_code = l2.get('color', {}).get('displayCode', '')
            is_on_sale = l2.get('sales', False)
            
            price_info = prices.get(l2_id, {})
            base_price = price_info.get('base', {}).get('value', 0)
            promo_price = price_info.get('promo', {}).get('value', 0) if is_on_sale else base_price
            
            stock_info = stocks.get(l2_id, {})
            stock_status = stock_info.get('statusCode', '')
            
            # Only include variants that are in stock
            if stock_status == 'IN_STOCK':
                variants.append({
                    'l2_id': l2_id,
                    'size_code': size_code,
                    'size_name': size_name,  # Add size name (S, M, L, XL)
                    'color_code': color_code,
                    'base_price': base_price,
                    'promo_price': promo_price,
                    'is_on_sale': is_on_sale,
                    'store_name': store_name,
                    'stock_status': stock_status
                })
        
        return variants
    
    def get_product_name_from_url(self, url: str) -> Optional[str]:
        """Try to get product name from URL or API"""
        try:
            product_id = self.extract_product_id_from_url(url)
            if not product_id:
                return None
            
            # Try to fetch product page to get name
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                # Try to extract from HTML title or meta tags
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(response.text, 'html.parser')
                title = soup.find('title')
                if title:
                    # Extract product name from title
                    title_text = title.get_text()
                    # Remove common suffixes
                    name = title_text.split('|')[0].strip() if '|' in title_text else title_text
                    return name
        except Exception as e:
            print(f"Error getting product name: {e}")
        
        return None

