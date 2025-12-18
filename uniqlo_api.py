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
        """Extract product ID from Uniqlo product URL
        
        Returns full product ID with color code (e.g., E478145-000)
        API requires full product ID format, does not support base ID alone
        """
        # Pattern: /id/id/products/{PRODUCT_ID}-{COLOR_CODE}/{SIZE_CODE}
        # Example: /id/id/products/E479678-000/00
        pattern = r'/products/([A-Z0-9]+-\d{3})'
        match = re.search(pattern, url)
        if match:
            product_id = match.group(1)  # E479678-000
            print(f"[EXTRACT] Product ID: {product_id}")
            return product_id
        return None
    
    def get_l2_id_from_color_size(self, product_id: str, color_display_code: str, size_display_code: str) -> Optional[str]:
        """Get l2_id (variant ID) from colorDisplayCode and sizeDisplayCode"""
        try:
            # Get product data to find matching l2_id
            url = f"{self.base_url}/products/{product_id}/price-groups/00/l2s"
            params = {
                'withPrices': 'true',
                'withStocks': 'true',
                'includePreviousPrice': 'false',
                'httpFailure': 'true'
            }
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') == 'ok' and 'result' in data:
                l2s = data['result'].get('l2s', [])
                for l2 in l2s:
                    color_code = l2.get('color', {}).get('displayCode', '')
                    size_code = l2.get('size', {}).get('displayCode', '')
                    
                    if color_code == color_display_code and size_code == size_display_code:
                        l2_id = l2.get('l2Id')
                        print(f"[L2_ID] Found l2_id={l2_id} for color={color_display_code}, size={size_display_code}")
                        return l2_id
                
                print(f"[L2_ID] No matching l2_id found for color={color_display_code}, size={size_display_code}")
            return None
        except Exception as e:
            print(f"[ERROR] Error getting l2_id from color/size: {e}")
            return None
    
    def check_store_stock_by_color_size(self, product_id: str, color_display_code: str, size_display_code: str, store_id: str) -> Optional[str]:
        """Check store stock for specific color and size using store-selection endpoint logic
        
        Returns: 'IN_STOCK', 'LOW_STOCK', 'OUT_OF_STOCK', or None
        """
        try:
            # Get l2_id from color and size
            l2_id = self.get_l2_id_from_color_size(product_id, color_display_code, size_display_code)
            if not l2_id:
                return None
            
            # Use existing endpoint to check store stock
            return self.get_store_specific_stock(l2_id, store_id)
        except Exception as e:
            print(f"[ERROR] Error checking store stock by color/size: {e}")
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
    
    def get_store_specific_stock(self, l2_id: str, store_id: str, keyword: str = None) -> Optional[str]:
        """Get store-specific stock status for a variant using /l2s/{l2_id}/stores endpoint
        This is the ACCURATE way to check offline store stock (matches website behavior)
        
        Args:
            l2_id: Product variant ID
            store_id: Store ID to check
            keyword: Optional city keyword (e.g., 'surabaya') to narrow down results
        
        Returns: 'IN_STOCK', 'LOW_STOCK', 'OUT_OF_STOCK', or None
        """
        try:
            url = f"{self.base_url}/l2s/{l2_id}/stores"
            params = {
                'unit': 'km',
                'priceGroup': '00',
                'limit': '50',  # Get up to 50 stores
                'httpFailure': 'true'
            }
            
            # Add keyword if provided (helps narrow down results)
            if keyword:
                params['keyword'] = keyword
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') == 'ok' and 'result' in data:
                stores = data['result'].get('stores', [])
                print(f"[STORE_STOCK_CHECK] l2_id={l2_id}, found {len(stores)} stores in response")
                
                # Find the specific store
                for store in stores:
                    store_id_match = store.get('storeId') or store.get('g1ImsStoreId6')
                    if store_id_match == store_id:
                        stock_status = store.get('stockStatus', 'OUT_OF_STOCK')
                        store_name = store.get('storeName', f'Store {store_id}')
                        print(f"[STORE_STOCK_CHECK] ✅ Found store {store_id} ({store_name}): stockStatus={stock_status}")
                        return stock_status
                
                print(f"[STORE_STOCK_CHECK] ❌ Store {store_id} not found in response")
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
            
            # Size code mapping (same as parse_product_data)
            SIZE_CODE_MAP = {
                '00': 'FREE SIZE', '001': 'XXS', '002': 'XS', '003': 'S', '004': 'M', 
                '005': 'L', '006': 'XL', '007': 'XXL', '008': 'XXXL', '009': '4XL', '010': '5XL',
                '027': '27"', '028': '28"', '029': '29"', '030': '30"', '031': '31"', '032': '32"',
                '033': '33"', '034': '34"', '035': '35"', '036': '36"', '037': '37"', '038': '38"',
                '040': '40"', '042': '42"',
                '100': '100cm', '110': '110cm', '120': '120cm', '130': '130cm', 
                '140': '140cm', '150': '150cm', '160': '160cm',
            }
            
            # Map l2_id to size name
            l2_to_size = {}
            for l2 in l2s:
                l2_id = l2.get('l2Id')
                size_obj = l2.get('size', {})
                
                # Get size code (prefer displayCode, fallback to sizeCode)
                display_code = size_obj.get('displayCode', '')
                full_size_code = size_obj.get('sizeCode', '')
                
                # Extract numeric part from sizeCode if needed
                if full_size_code and not display_code:
                    import re
                    match = re.search(r'(\d{2,3})$', full_size_code)
                    if match:
                        display_code = match.group(1)
                
                size_code = display_code or full_size_code
                
                # Try to get size name from multiple fields
                size_name = (
                    size_obj.get('name') or 
                    size_obj.get('displayName') or 
                    size_obj.get('label') or 
                    SIZE_CODE_MAP.get(size_code, size_code)
                )
                
                l2_to_size[l2_id] = size_name
                print(f"[ONLINE_CHECK_SIZE] l2_id={l2_id}, size_code={size_code}, size_name={size_name}")
            
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
            
            # Debug: Log size extraction
            print(f"[SIZE_DEBUG] l2_id={l2_id}, displayCode={display_code}, sizeCode={full_size_code}, final_size_code={size_code}")
            print(f"[SIZE_DEBUG] size_obj fields: name={size_obj.get('name')}, displayName={size_obj.get('displayName')}, label={size_obj.get('label')}")
            
            # Try multiple fields to get size name
            size_name = (
                size_obj.get('name') or 
                size_obj.get('displayName') or 
                size_obj.get('label') or 
                SIZE_CODE_MAP.get(size_code, size_code)
            )
            
            print(f"[SIZE_DEBUG] Final size_name={size_name} (from SIZE_CODE_MAP: {SIZE_CODE_MAP.get(size_code, 'NOT_FOUND')})")
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
                print(f"[STOCK_DEBUG] l2_id={l2_id}, status={stock_status}, quantity={stock_quantity}, size={size_name}, color={color_code}, store={store_name}")
            
            # Include variants with actual stock (quantity > 0) and status IN_STOCK or LOW_STOCK
            # LOW_STOCK with quantity > 0 means still available
            # STOCK_OUT or quantity = 0 means not available
            if stock_quantity > 0 and stock_status in ['IN_STOCK', 'LOW_STOCK']:
                print(f"[VARIANT_ADDED] ✅ {size_name} {color_code} - qty={stock_quantity}, status={stock_status}, store={store_name}")
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
            else:
                print(f"[VARIANT_SKIPPED] ❌ {size_name} {color_code} - qty={stock_quantity}, status={stock_status}, store={store_name}")
        
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

