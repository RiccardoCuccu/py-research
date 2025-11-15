"""
DOI/Title to Scopus ID Extractor - Enhanced Version
Using Scopus Developer API (FREE tier available)

Features:
- Data validation (DOI format, title length)
- Duplicate detection
- Response caching
- Batch processing with parallel requests
- Resume from checkpoint
- API key testing

SETUP:
1. Register at https://dev.elsevier.com
2. Get FREE API key (5000 requests/week)
3. Run script and enter API key when prompted
"""

import pandas as pd
import requests
import time
import os
import sys
import signal
import argparse
import logging
import getpass
import json
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from typing import Optional, Tuple, List, Dict

logging.basicConfig(level=logging.INFO, format='%(message)s')
logging.getLogger('requests').setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DOI_INPUT_FILE = os.path.join(SCRIPT_DIR, "dois.txt")
TITLE_INPUT_FILE = os.path.join(SCRIPT_DIR, "titles.txt")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "scopus_results.csv")
CHECKPOINT_FILE = os.path.join(SCRIPT_DIR, "checkpoint.json")
CACHE_FILE = os.path.join(SCRIPT_DIR, ".scopus_cache.json")
SCOPUS_KEY_FILE = os.path.join(SCRIPT_DIR, ".scopus_api_key")
VALIDATION_REPORT_FILE = os.path.join(SCRIPT_DIR, "validation_report.txt")

SCOPUS_SEARCH_API = "https://api.elsevier.com/content/search/scopus"

DELAY_BETWEEN_REQUESTS = 1
TIMEOUT = 30
MAX_WORKERS = 3

DOI_PATTERN = re.compile(r'^10\.\d{4,9}/[-._;()/:A-Z0-9]+$', re.IGNORECASE)
MIN_TITLE_LENGTH = 10

interrupt_flag = False
requests_made = 0
errors_count = 0
cache_hits = 0

# ============================================================
# VALIDATION
# ============================================================

class InputValidator:
    """Validate DOIs and titles before processing"""
    
    @staticmethod
    def validate_doi(doi: str) -> Tuple[bool, str]:
        """Validate DOI format"""
        doi = doi.strip()
        if not doi:
            return False, "Empty DOI"
        if not DOI_PATTERN.match(doi):
            return False, f"Invalid DOI format: {doi}"
        return True, ""
    
    @staticmethod
    def validate_title(title: str) -> Tuple[bool, str]:
        """Validate title"""
        title = title.strip()
        if not title:
            return False, "Empty title"
        if len(title) < MIN_TITLE_LENGTH:
            return False, f"Title too short (min {MIN_TITLE_LENGTH} chars): {title[:50]}"
        return True, ""
    
    @staticmethod
    def detect_duplicates(items: List[str]) -> Tuple[List[str], List[Tuple[int, str, int]]]:
        """Detect duplicates and return (unique_items, duplicates_info)"""
        seen = {}
        unique = []
        duplicates = []
        
        for i, item in enumerate(items):
            normalized = item.lower().strip()
            if normalized in seen:
                duplicates.append((i + 1, item, seen[normalized] + 1))
            else:
                seen[normalized] = i
                unique.append(item)
        
        return unique, duplicates
    
    @staticmethod
    def validate_batch(items: List[str], search_mode: str) -> Dict:
        """Validate batch of items and return report"""
        validate_fn = InputValidator.validate_doi if search_mode == 'doi' else InputValidator.validate_title
        
        valid_items = []
        invalid_items = []
        
        for i, item in enumerate(items):
            is_valid, error_msg = validate_fn(item)
            if is_valid:
                valid_items.append(item)
            else:
                invalid_items.append((i + 1, item, error_msg))
        
        unique_items, duplicates = InputValidator.detect_duplicates(valid_items)
        
        return {
            'total': len(items),
            'valid': len(valid_items),
            'invalid': len(invalid_items),
            'invalid_items': invalid_items,
            'unique': len(unique_items),
            'duplicates': len(duplicates),
            'duplicate_items': duplicates,
            'unique_items': unique_items
        }

# ============================================================
# CACHE SYSTEM
# ============================================================

class ResultCache:
    """Cache Scopus API responses"""
    
    def __init__(self, cache_file: str):
        self.cache_file = cache_file
        self.cache = self._load_cache()
        self.lock = threading.Lock()
    
    def _load_cache(self) -> Dict:
        """Load cache from file"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load cache: {e}")
        return {}
    
    def _save_cache(self):
        """Save cache to file"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Could not save cache: {e}")
    
    def get(self, key: str) -> Optional[Dict]:
        """Get cached result"""
        with self.lock:
            normalized_key = key.lower().strip()
            return self.cache.get(normalized_key)
    
    def set(self, key: str, value: Dict):
        """Store result in cache"""
        with self.lock:
            normalized_key = key.lower().strip()
            value['cached_at'] = datetime.now().isoformat()
            self.cache[normalized_key] = value
            self._save_cache()
    
    def clear(self):
        """Clear all cache"""
        with self.lock:
            self.cache = {}
            self._save_cache()
    
    def stats(self) -> Dict:
        """Get cache statistics"""
        with self.lock:
            return {
                'total_entries': len(self.cache),
                'cache_file': self.cache_file,
                'file_exists': os.path.exists(self.cache_file)
            }

# ============================================================
# SCOPUS API KEY MANAGEMENT
# ============================================================

def load_or_prompt_scopus_key():
    """Load Scopus API key from file or prompt user"""
    if os.path.exists(SCOPUS_KEY_FILE):
        try:
            with open(SCOPUS_KEY_FILE, 'r') as f:
                key = f.read().strip()
                if key:
                    print(f"✅ Scopus API key loaded from {SCOPUS_KEY_FILE}")
                    return key
        except IOError as e:
            logger.warning(f"Could not read API key file: {e}")
    
    print("\n" + "=" * 60)
    print("SCOPUS API KEY SETUP")
    print("=" * 60)
    print("Free API key available at: https://dev.elsevier.com")
    print("Quota: 5,000 requests per week (FREE)")
    print()
    
    api_key = getpass.getpass("Enter your Scopus API key (will be saved): ").strip()
    
    if api_key:
        try:
            with open(SCOPUS_KEY_FILE, 'w') as f:
                f.write(api_key)
            os.chmod(SCOPUS_KEY_FILE, 0o600)
            print(f"✅ API key saved to {SCOPUS_KEY_FILE}")
        except IOError as e:
            logger.warning(f"Could not save API key: {e}")
    
    return api_key

def test_api_key(api_key: str) -> Tuple[bool, str]:
    """Test API key with a known DOI"""
    test_doi = "10.1016/j.softx.2019.100263"
    
    print("\n🔍 Testing API key...")
    print(f"   Using test DOI: {test_doi}")
    
    try:
        params = {
            'query': f'DOI({test_doi})',
            'apiKey': api_key,
            'httpAccept': 'application/json'
        }
        response = requests.get(SCOPUS_SEARCH_API, params=params, timeout=TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('search-results', {}).get('entry'):
                entry = data['search-results']['entry'][0]
                title = entry.get('dc:title', 'N/A')
                scopus_id = entry.get('eid', 'N/A')
                print(f"   ✅ Found: {title[:60]}...")
                print(f"   ✅ Scopus ID: {scopus_id}")
                return True, "API key is valid and working"
            return False, "API key works but test query returned no results"
        elif response.status_code == 401:
            return False, "API key is invalid or unauthorized"
        elif response.status_code == 429:
            return False, "API key is valid but rate limited"
        else:
            return False, f"Unexpected status code: {response.status_code}"
    except Exception as e:
        return False, f"API key test failed: {str(e)}"

def create_gitignore_entry():
    """Add cache and API key files to .gitignore"""
    gitignore_path = os.path.join(SCRIPT_DIR, ".gitignore")
    entries = [".scopus_api_key", ".scopus_cache.json"]
    
    try:
        existing_content = ""
        if os.path.exists(gitignore_path):
            with open(gitignore_path, 'r') as f:
                existing_content = f.read()
        
        new_entries = []
        for entry in entries:
            if entry not in existing_content:
                new_entries.append(entry)
        
        if new_entries:
            with open(gitignore_path, 'a') as f:
                if existing_content and not existing_content.endswith('\n'):
                    f.write('\n')
                for entry in new_entries:
                    f.write(f"{entry}\n")
            print(f"✅ Updated .gitignore with: {', '.join(new_entries)}")
    except IOError as e:
        logger.warning(f"Could not update .gitignore: {e}")

# ============================================================
# API FUNCTIONS
# ============================================================

def signal_handler(sig, frame):
    """Handle Ctrl+C"""
    global interrupt_flag
    interrupt_flag = True
    print("\n\n⚠️ INTERRUPT")
    sys.exit(0)

def search_scopus_api(doi: str, api_key: str) -> Tuple[Optional[str], Optional[str]]:
    """Search Scopus API by DOI - Returns title and Scopus ID"""
    global requests_made, errors_count
    
    if interrupt_flag:
        raise KeyboardInterrupt()
    
    try:
        requests_made += 1
        params = {
            'query': f'DOI({doi})',
            'apiKey': api_key,
            'httpAccept': 'application/json'
        }
        response = requests.get(SCOPUS_SEARCH_API, params=params, timeout=TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('search-results', {}).get('entry'):
                entry = data['search-results']['entry'][0]
                title = entry.get('dc:title')
                scopus_id = entry.get('eid')
                return title, scopus_id
        elif response.status_code == 401:
            logger.error("Unauthorized - check Scopus API key")
        elif response.status_code == 429:
            logger.warning("Rate limited - waiting...")
            time.sleep(5)
        
        errors_count += 1
        return None, None
    except requests.RequestException as e:
        logger.debug(f"Scopus API error: {e}")
        errors_count += 1
        return None, None

def search_openalex_doi(doi: str) -> Optional[str]:
    """Search OpenAlex by DOI - Returns only title for logging purposes"""
    global requests_made, errors_count
    
    if interrupt_flag:
        raise KeyboardInterrupt()
    
    try:
        requests_made += 1
        url = f"https://api.openalex.org/works/https://doi.org/{doi}"
        response = requests.get(url, timeout=TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('title')
        
        errors_count += 1
        return None
    except requests.RequestException as e:
        logger.debug(f"OpenAlex API error: {e}")
        errors_count += 1
        return None

def search_scopus_api_title(title: str, api_key: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Search Scopus API by title"""
    global requests_made, errors_count
    
    if interrupt_flag:
        raise KeyboardInterrupt()
    
    try:
        requests_made += 1
        params = {
            'query': f'TITLE({title})',
            'apiKey': api_key,
            'httpAccept': 'application/json',
            'count': 1
        }
        response = requests.get(SCOPUS_SEARCH_API, params=params, timeout=TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('search-results', {}).get('entry'):
                entry = data['search-results']['entry'][0]
                title_found = entry.get('dc:title')
                scopus_id = entry.get('eid')
                doi = entry.get('prism:doi')
                return title_found, scopus_id, doi
        elif response.status_code == 401:
            logger.error("Unauthorized - check Scopus API key")
        elif response.status_code == 429:
            logger.warning("Rate limited - waiting...")
            time.sleep(5)
        
        errors_count += 1
        return None, None, None
    except requests.RequestException as e:
        logger.debug(f"Scopus API error: {e}")
        errors_count += 1
        return None, None, None

def search_openalex_title(title: str) -> Tuple[Optional[str], Optional[str]]:
    """Search OpenAlex by title - Returns title and DOI for matching"""
    global requests_made, errors_count
    
    if interrupt_flag:
        raise KeyboardInterrupt()
    
    try:
        requests_made += 1
        params = {
            'search': title,
            'per-page': 1
        }
        response = requests.get("https://api.openalex.org/works", params=params, timeout=TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('results'):
                result = data['results'][0]
                title_found = result.get('title')
                doi = None
                if result.get('ids') and 'doi' in result['ids']:
                    doi = result['ids']['doi'].replace('https://doi.org/', '')
                return title_found, doi
        
        errors_count += 1
        return None, None
    except requests.RequestException as e:
        logger.debug(f"OpenAlex API error: {e}")
        errors_count += 1
        return None, None

# ============================================================
# PROCESSING FUNCTIONS
# ============================================================

def load_items_from_file(filepath: str) -> List[str]:
    """Load items from file"""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File {filepath} not found!")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        items = [line.strip() for line in f if line.strip()]
    
    return items

def save_validation_report(report: Dict, search_mode: str):
    """Save validation report to file"""
    try:
        with open(VALIDATION_REPORT_FILE, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("VALIDATION REPORT\n")
            f.write("=" * 60 + "\n")
            f.write(f"Search mode: {search_mode.upper()}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n\n")
            
            f.write(f"Total items: {report['total']}\n")
            f.write(f"Valid items: {report['valid']}\n")
            f.write(f"Invalid items: {report['invalid']}\n")
            f.write(f"Unique items: {report['unique']}\n")
            f.write(f"Duplicates: {report['duplicates']}\n\n")
            
            if report['invalid_items']:
                f.write("INVALID ITEMS:\n")
                f.write("-" * 60 + "\n")
                for line_num, item, error in report['invalid_items']:
                    f.write(f"Line {line_num}: {error}\n")
                    f.write(f"  → {item[:100]}\n\n")
            
            if report['duplicate_items']:
                f.write("\nDUPLICATE ITEMS:\n")
                f.write("-" * 60 + "\n")
                for line_num, item, first_seen in report['duplicate_items']:
                    f.write(f"Line {line_num}: Duplicate of line {first_seen}\n")
                    f.write(f"  → {item[:100]}\n\n")
        
        print(f"📝 Validation report saved to {VALIDATION_REPORT_FILE}")
    except IOError as e:
        logger.warning(f"Could not save validation report: {e}")

def load_checkpoint() -> Optional[Dict]:
    """Load checkpoint from file"""
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load checkpoint: {e}")
    return None

def save_checkpoint(metadata: Dict, results: List[Dict]):
    """Save checkpoint to file"""
    try:
        checkpoint = {
            'metadata': metadata,
            'results': results
        }
        with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
            json.dump(checkpoint, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.warning(f"Could not save checkpoint: {e}")

def save_final_results(results: List[Dict], search_mode: str):
    """Save final results to CSV"""
    try:
        df = pd.DataFrame(results)
        df.to_csv(OUTPUT_FILE, index=False, encoding='utf-8')
        print(f"✅ Results saved to {os.path.basename(OUTPUT_FILE)}")
        
        successful = df[df['scopus_id'].notna()].shape[0]
        failed = df[df['scopus_id'].isna()].shape[0]
        
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Search mode: {search_mode.upper()}")
        print(f"Total: {len(results)} | Found: {successful} | Not found: {failed}")
        if len(results) > 0:
            print(f"Success rate: {(successful/len(results)*100):.1f}%")
        print(f"API requests: {requests_made}")
        print(f"Cache hits: {cache_hits}")
        print(f"Errors: {errors_count}")
        print("=" * 60)
    except IOError as e:
        logger.error(f"Error saving results: {e}")

def process_doi_item(item: str, api_key: str, cache: ResultCache, use_cache: bool) -> Dict:
    """Process a single DOI item"""
    global cache_hits
    
    cached_result = cache.get(item) if use_cache else None
    if cached_result:
        cache_hits += 1
        return {
            'doi': item,
            'title': cached_result.get('title'),
            'scopus_id': cached_result.get('scopus_id'),
            'cached': True
        }
    
    title, scopus_id = search_scopus_api(item, api_key)
    
    if not scopus_id:
        title = search_openalex_doi(item)
    
    result = {
        'doi': item,
        'title': title,
        'scopus_id': scopus_id,
        'cached': False
    }
    
    if scopus_id and use_cache:
        cache.set(item, {'title': title, 'scopus_id': scopus_id, 'source': 'scopus'})
    
    time.sleep(DELAY_BETWEEN_REQUESTS)
    return result

def process_title_item(item: str, api_key: str, cache: ResultCache, use_cache: bool) -> Dict:
    """Process a single title item"""
    global cache_hits
    
    cached_result = cache.get(item) if use_cache else None
    if cached_result:
        cache_hits += 1
        return {
            'search_title': item,
            'found_title': cached_result.get('title'),
            'scopus_id': cached_result.get('scopus_id'),
            'doi': cached_result.get('doi'),
            'cached': True
        }
    
    title_found, scopus_id, doi = search_scopus_api_title(item, api_key)
    
    if not scopus_id:
        title_found, doi = search_openalex_title(item)
    
    result = {
        'search_title': item,
        'found_title': title_found,
        'scopus_id': scopus_id,
        'doi': doi,
        'cached': False
    }
    
    if scopus_id and use_cache:
        cache.set(item, {'title': title_found, 'scopus_id': scopus_id, 'doi': doi, 'source': 'scopus'})
    
    time.sleep(DELAY_BETWEEN_REQUESTS)
    return result

# ============================================================
# MAIN
# ============================================================

def main():
    """Main execution"""
    global interrupt_flag
    
    parser = argparse.ArgumentParser(
        description='Extract Scopus ID from DOI/Title',
        epilog="""
Examples:
  %(prog)s --doi              Search using dois.txt
  %(prog)s --title            Search using titles.txt
  %(prog)s --doi --limit 10   Search first 10 DOIs
  %(prog)s --doi --resume     Resume from last checkpoint
  %(prog)s --test-key         Test your Scopus API key
  %(prog)s --cache-stats      Show cache statistics
  %(prog)s --clear-cache      Clear response cache

Input files: dois.txt or titles.txt (one per line)
Output: scopus_results.csv
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    search_group = parser.add_mutually_exclusive_group(required=False)
    search_group.add_argument('--doi', action='store_true', help='Search by DOI (requires dois.txt)')
    search_group.add_argument('--title', action='store_true', help='Search by title (requires titles.txt)')
    
    parser.add_argument('--limit', type=int, default=None, help='Limit number of items to process')
    parser.add_argument('--workers', type=int, default=MAX_WORKERS, help=f'Number of parallel workers (default: {MAX_WORKERS})')
    parser.add_argument('--resume', action='store_true', help='Resume from last checkpoint')
    parser.add_argument('--skip-duplicates', action='store_true', help='Skip duplicate entries')
    parser.add_argument('--no-cache', action='store_true', help='Bypass response cache')
    parser.add_argument('--dry-run', action='store_true', help='Validate only, do not process')
    
    parser.add_argument('--test-key', action='store_true', help='Test Scopus API key')
    parser.add_argument('--reset-key', action='store_true', help='Delete saved Scopus API key')
    parser.add_argument('--cache-stats', action='store_true', help='Show cache statistics')
    parser.add_argument('--clear-cache', action='store_true', help='Clear response cache')
    
    args = parser.parse_args()
    
    signal.signal(signal.SIGINT, signal_handler)
    create_gitignore_entry()
    
    cache = ResultCache(CACHE_FILE)
    
    if args.cache_stats:
        stats = cache.stats()
        print("\n" + "=" * 60)
        print("CACHE STATISTICS")
        print("=" * 60)
        print(f"Total entries: {stats['total_entries']}")
        print(f"Cache file: {stats['cache_file']}")
        print(f"File exists: {stats['file_exists']}")
        print("=" * 60)
        return
    
    if args.clear_cache:
        cache.clear()
        print("✅ Cache cleared")
        return
    
    if args.reset_key:
        if os.path.exists(SCOPUS_KEY_FILE):
            os.remove(SCOPUS_KEY_FILE)
            print(f"✅ Scopus API key deleted")
        else:
            print("ℹ️ No API key file found")
        return
    
    api_key = load_or_prompt_scopus_key()
    
    if not api_key:
        print("\n❌ Scopus API key is required")
        print("💡 Get free key at: https://dev.elsevier.com")
        return
    
    if args.test_key:
        success, message = test_api_key(api_key)
        print(f"\n{'✅' if success else '❌'} {message}")
        return
    
    if not args.doi and not args.title:
        parser.print_help()
        return
    
    search_mode = 'title' if args.title else 'doi'
    input_file = TITLE_INPUT_FILE if args.title else DOI_INPUT_FILE
    
    print("=" * 60)
    print("DOI/Title to Scopus ID Extractor")
    print("=" * 60)
    print(f"Mode: {search_mode.upper()}")
    print(f"Primary: Scopus API (FREE tier)")
    print(f"Fallback: OpenAlex (title/DOI lookup only)")
    print(f"Cache: {'Disabled' if args.no_cache else 'Enabled'}")
    print(f"Workers: {args.workers}")
    if args.limit:
        print(f"Limit: {args.limit} items")
    if args.resume:
        print(f"Resume: Enabled")
    print()
    
    items = load_items_from_file(input_file)
    original_count = len(items)
    
    print(f"📥 Loaded {original_count} items")
    
    print("\n🔍 Validating input...")
    validation_report = InputValidator.validate_batch(items, search_mode)
    
    print(f"   Valid: {validation_report['valid']}/{validation_report['total']}")
    print(f"   Invalid: {validation_report['invalid']}")
    print(f"   Duplicates: {validation_report['duplicates']}")
    
    if validation_report['invalid'] > 0 or validation_report['duplicates'] > 0:
        save_validation_report(validation_report, search_mode)
    
    if validation_report['invalid'] > 0:
        print(f"   ⚠️ {validation_report['invalid']} invalid items will be skipped")
    
    if args.skip_duplicates and validation_report['duplicates'] > 0:
        items = validation_report['unique_items']
        print(f"   ✅ Using {len(items)} unique items (removed {validation_report['duplicates']} duplicates)")
    else:
        items = validation_report['unique_items']
    
    if args.dry_run:
        print("\n✅ Dry run complete (no API calls made)")
        return
    
    start_index = 0
    existing_results = []
    
    if args.resume:
        checkpoint = load_checkpoint()
        if checkpoint:
            start_index = checkpoint['metadata']['last_processed_index']
            existing_results = checkpoint['results']
            print(f"📂 Resuming from checkpoint: {start_index}/{len(items)} items already processed")
    
    if args.limit:
        items = items[start_index:start_index + args.limit]
    else:
        items = items[start_index:]
    
    if not items:
        print("\n✅ No items to process")
        if existing_results:
            save_final_results(existing_results, search_mode)
        return
    
    print(f"\n🚀 Processing {len(items)} items...\n")
    
    results = existing_results.copy()
    
    try:
        for i, item in enumerate(items, 1):
            if interrupt_flag:
                raise KeyboardInterrupt()
            
            absolute_index = start_index + i
            
            if search_mode == 'doi':
                print(f"[{absolute_index}/{original_count}] DOI: {item}")
                result = process_doi_item(item, api_key, cache, not args.no_cache)
                
                if result.get('cached'):
                    print(f"    💾 Cached result")
                else:
                    print(f"    🔍 Scopus API...")
                
                if result.get('title'):
                    print(f"    ✅ Title: {result['title'][:100]}...")
                if result.get('scopus_id'):
                    print(f"    ✅ Scopus ID: {result['scopus_id']}")
                else:
                    print(f"    ⚠️ Scopus ID not found")
                
                results.append({
                    'doi': result['doi'],
                    'title': result['title'],
                    'scopus_id': result['scopus_id']
                })
            else:
                print(f"[{absolute_index}/{original_count}] Title: {item[:80]}...")
                result = process_title_item(item, api_key, cache, not args.no_cache)
                
                if result.get('cached'):
                    print(f"    💾 Cached result")
                else:
                    print(f"    🔍 Scopus API...")
                
                if result.get('found_title'):
                    print(f"    ✅ Found: {result['found_title'][:100]}...")
                if result.get('scopus_id'):
                    print(f"    ✅ Scopus ID: {result['scopus_id']}")
                else:
                    print(f"    ⚠️ Scopus ID not found")
                if result.get('doi'):
                    print(f"    🔗 DOI: {result['doi']}")
                
                results.append({
                    'search_title': result['search_title'],
                    'found_title': result['found_title'],
                    'scopus_id': result['scopus_id'],
                    'doi': result['doi']
                })
            
            if i % 10 == 0:
                metadata = {
                    'search_mode': search_mode,
                    'total_items': original_count,
                    'last_processed_index': absolute_index,
                    'timestamp': datetime.now().isoformat()
                }
                save_checkpoint(metadata, results)
                successful = sum(1 for r in results if r.get('scopus_id'))
                print(f"    💾 Checkpoint: {absolute_index}/{original_count} | Found: {successful}/{len(results)}")
            
            print()
    
    except KeyboardInterrupt:
        print("\n⚠️ INTERRUPTED")
    finally:
        print("\n💾 Saving results...")
        save_final_results(results, search_mode)
        print("✅ Done")

if __name__ == "__main__":
    main()