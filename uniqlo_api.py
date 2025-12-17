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
    
    def get_store_specific_stock(self, l2_id: str, store_id: str) -> Optional[str]:
        """Get store-specific stock status for a variant (more accurate than general API)
        Returns: 'IN_STOCK', 'LOW_STOCK', 'OUT_OF_STOCK', or None
        """
        try:
            url = f"{self.base_url}/l2s/{l2_id}/stores"
            params = {
                'unit': 'km',
                'priceGroup': '00',
                'limit': '50',
                'httpFailure': 'true'
            }
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') == 'ok' and 'result' in data:
                stores = data['result'].get('stores', [])
                # Find the specific store
                for store in stores:
                    if store.get('storeId') == store_id or store.get('g1ImsStoreId6') == store_id:
                        stock_status = store.get('stockStatus', 'OUT_OF_STOCK')
                        return stock_status
            return None
        except Exception as e:
            print(f"[ERROR] Error fetching store-specific stock for l2={l2_id}, store={store_id}: {e}")
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
    
    def check_online_availability(self, product_id: str) -> Dict:
        """Check if product is available in online store and return available sizes"""
        try:
            # Get product info WITHOUT storeId to check online availability (NOT store-specific)
            # This endpoint without storeId returns online store stock
            url = f"{self.base_url}/products/{product_id}/price-groups/00/l2s"
            params = {
                'withPrices': 'true',
                'withStocks': 'true',
                'includePreviousPrice': 'false',
                'httpFailure': 'true'
            }
            
            print(f"[ONLINE_CHECK] Checking online availability for product {product_id}")
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') != 'ok' or 'result' not in data:
                print(f"[ONLINE_CHECK] Product not found in online store")
                return {'available': False, 'reason': 'product_not_found', 'sizes': []}
            
            result = data['result']
            stocks = result.get('stocks', {})
            l2s = result.get('l2s', [])
            print(f"[ONLINE_CHECK] Found {len(stocks)} variants in API response")
            
            # Map l2_id to size name
            l2_to_size = {}
            for l2 in l2s:
                l2_id = l2.get('l2Id')
                size_obj = l2.get('size', {})
                size_name = size_obj.get('name') or size_obj.get('displayName') or size_obj.get('label', '')
                l2_to_size[l2_id] = size_name
            
            # Check if any variant has online stock
            online_variants = []
            online_sizes = []
            for l2_id, stock_info in stocks.items():
                stock_status = stock_info.get('statusCode', '')
                stock_quantity = stock_info.get('quantity', 0)
                
                print(f"[ONLINE_CHECK] l2_id={l2_id}, status={stock_status}, quantity={stock_quantity}")
                
                # Check if available online (either IN_STOCK or LOW_STOCK with quantity > 0)
                if stock_quantity > 0 and stock_status in ['IN_STOCK', 'LOW_STOCK']:
                    online_variants.append(l2_id)
                    size_name = l2_to_size.get(l2_id, 'Unknown')
                    online_sizes.append(size_name)
            
            print(f"[ONLINE_CHECK] Result: {len(online_variants)} variants available online - Sizes: {', '.join(online_sizes)}")
            
            return {
                'available': len(online_variants) > 0,
                'variant_count': len(online_variants),
                'sizes': online_sizes,
                'reason': 'available' if online_variants else 'out_of_stock'
            }
        except Exception as e:
            print(f"[ERROR] Error checking online availability: {e}")
            return {'available': False, 'reason': 'error', 'error': str(e), 'sizes': []}
    
    def search_stores_by_product(self, l2_id: str, keyword: str = None, limit: int = 20) -> List[Dict]:
        """Search stores by product variant (l2_id) and optional keyword (city)"""
        try:
            url = f"{self.base_url}/l2s/{l2_id}/stores"
            params = {
                'unit': 'km',
                'priceGroup': '00',
                'limit': str(limit),
                'httpFailure': 'true'
            }
            
            if keyword:
                params['keyword'] = keyword
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') == 'ok' and 'result' in data:
                result = data['result']
                stores = result.get('stores', [])
                
                # Convert to consistent format
                formatted_stores = []
                for store in stores:
                    formatted_stores.append({
                        'id': store.get('storeId'),
                        'name': store.get('storeName'),
                        'address': '',  # Not provided in this endpoint
                        'business_status': store.get('businessStatus'),
                        'stock_status': store.get('stockStatus'),
                        'distance': store.get('distance')
                    })
                
                return formatted_stores
            return []
        except Exception as e:
            print(f"Error searching stores by product: {e}")
            return []
    
    def search_stores(self, city: str = None) -> List[Dict]:
        """Search for stores by city name (using a dummy product to get store list)"""
        try:
            # Use a common product ID to search stores
            # We'll use a basic t-shirt product that's available everywhere
            dummy_l2_id = "09055426"  # Example product variant ID
            
            if city:
                return self.search_stores_by_product(dummy_l2_id, keyword=city, limit=20)
            
            # If no city specified, try to get all stores
            url = f"{self.base_url}/stores"
            params = {
                'includeClosed': 'false',
                'httpFailure': 'true'
            }
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') == 'ok' and 'result' in data:
                return data['result']
            return []
        except Exception as e:
            print(f"Error searching stores: {e}")
            return []
    
    def parse_product_data(self, product_data: Dict, store_name: str = "Uniqlo") -> List[Dict]:
        """Parse product data into a list of variants with prices"""
        variants = []
        
        if not product_data:
            return variants
        
        # Mapping displayCode/sizeCode to size name
        SIZE_CODE_MAP = {
            # Standard sizes
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
            # Inch sizes (pants/jeans)
            '027': '27"',
            '028': '28"',
            '029': '29"',
            '030': '30"',
            '031': '31"',
            '032': '32"',
            '033': '33"',
            '034': '34"',
            '035': '35"',
            '036': '36"',
            '037': '37"',
            '038': '38"',
            '040': '40"',
            '042': '42"',
            # Kids sizes
            '100': '100cm',
            '110': '110cm',
            '120': '120cm',
            '130': '130cm',
            '140': '140cm',
            '150': '150cm',
            '160': '160cm',
        }
        
        l2s = product_data.get('l2s', [])
        prices = product_data.get('prices', {})
        stocks = product_data.get('stocks', {})
        
        for l2 in l2s:
            l2_id = l2.get('l2Id')
            size_obj = l2.get('size', {})
            
            # Get size code (prefer displayCode, fallback to sizeCode)
            display_code = size_obj.get('displayCode', '')
            full_size_code = size_obj.get('sizeCode', '')  # e.g., INS027
            
            # Extract numeric part from sizeCode if exists (e.g., INS027 → 027)
            if full_size_code and not display_code:
                # Extract last 3 digits from codes like INS027, INS028, etc.
                import re
                match = re.search(r'(\d{2,3})$', full_size_code)
                if match:
                    display_code = match.group(1)
            
            size_code = display_code or full_size_code
            
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
            stock_quantity = stock_info.get('quantity', 0)  # Get actual stock quantity
            
            # Debug: Log stock info for troubleshooting
            if l2_id and stock_info:
                print(f"[STOCK_DEBUG] l2_id={l2_id}, status={stock_status}, quantity={stock_quantity}, size={size_name}")
            
            # Include variants with actual stock (quantity > 0) and status IN_STOCK or LOW_STOCK
            # LOW_STOCK with quantity > 0 means still available
            # STOCK_OUT or quantity = 0 means not available
            if stock_quantity > 0 and stock_status in ['IN_STOCK', 'LOW_STOCK']:
                variants.append({
                    'l2_id': l2_id,
                    'size_code': size_code,
                    'size_name': size_name,  # Add size name (S, M, L, XL)
                    'color_code': color_code,
                    'base_price': base_price,
                    'promo_price': promo_price,
                    'is_on_sale': is_on_sale,
                    'store_name': store_name,
                    'stock_status': stock_status,
                    'stock_quantity': stock_quantity
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

