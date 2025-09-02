"""
Advanced stealth utilities for Sci-Hub CLI
Implements anti-detection measures for robust paper downloading
"""

import random
import time
import json
import os
from typing import List, Dict, Optional
import requests
from urllib.parse import urlparse

class StealthConfig:
    """Configuration for stealth downloading"""
    
    # Realistic User-Agent rotation pool
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/121.0.0.0',
    ]
    
    # Realistic browser headers
    COMMON_HEADERS = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'sec-ch-ua': '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }
    
    # Rate limiting settings
    MIN_DELAY = 2.0  # Minimum delay between requests (seconds)
    MAX_DELAY = 8.0  # Maximum delay between requests (seconds)
    BURST_DELAY = 15.0  # Delay after burst detection (seconds)
    MAX_REQUESTS_PER_MINUTE = 8  # Max requests per minute per mirror
    
    # Session settings
    MAX_REQUESTS_PER_SESSION = 25  # Rotate session after this many requests
    SESSION_COOLDOWN = 30  # Seconds to wait between session rotations

class StealthSession:
    """Enhanced session with anti-detection features"""
    
    def __init__(self):
        self.session = requests.Session()
        self.request_count = 0
        self.last_request_time = 0
        self.requests_this_minute = []
        self.current_ua_index = random.randint(0, len(StealthConfig.USER_AGENTS) - 1)
        self._setup_session()
    
    def _setup_session(self):
        """Configure session with realistic headers"""
        headers = StealthConfig.COMMON_HEADERS.copy()
        headers['User-Agent'] = StealthConfig.USER_AGENTS[self.current_ua_index]
        self.session.headers.update(headers)
        
        # Configure session settings
        self.session.max_redirects = 5
        
        # Add some entropy to TLS fingerprinting
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=3
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
    
    def _should_rotate_session(self) -> bool:
        """Check if session should be rotated"""
        return self.request_count >= StealthConfig.MAX_REQUESTS_PER_SESSION
    
    def _wait_for_rate_limit(self, mirror_url: str):
        """Implement intelligent rate limiting"""
        current_time = time.time()
        
        # Clean old requests from the tracking list
        self.requests_this_minute = [
            req_time for req_time in self.requests_this_minute 
            if current_time - req_time < 60
        ]
        
        # Check if we're hitting rate limits
        if len(self.requests_this_minute) >= StealthConfig.MAX_REQUESTS_PER_MINUTE:
            print(f"Rate limit reached for {mirror_url}, waiting...")
            time.sleep(StealthConfig.BURST_DELAY)
            self.requests_this_minute = []
        
        # Calculate delay since last request
        time_since_last = current_time - self.last_request_time
        min_delay = random.uniform(StealthConfig.MIN_DELAY, StealthConfig.MAX_DELAY)
        
        if time_since_last < min_delay:
            wait_time = min_delay - time_since_last
            time.sleep(wait_time)
        
        self.last_request_time = time.time()
        self.requests_this_minute.append(self.last_request_time)
    
    def get(self, url: str, **kwargs) -> requests.Response:
        """Enhanced GET request with stealth features"""
        # Extract mirror URL for rate limiting
        mirror_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        
        # Apply rate limiting
        self._wait_for_rate_limit(mirror_url)
        
        # Rotate session if needed
        if self._should_rotate_session():
            print("Rotating session for better stealth...")
            time.sleep(StealthConfig.SESSION_COOLDOWN)
            self._rotate_session()
        
        # Add some request-specific headers
        headers = kwargs.get('headers', {})
        headers['Referer'] = f"{mirror_url}/"
        kwargs['headers'] = headers
        
        # Make the request
        response = self.session.get(url, **kwargs)
        self.request_count += 1
        
        return response
    
    def _rotate_session(self):
        """Rotate session with new fingerprint"""
        self.session.close()
        self.session = requests.Session()
        self.request_count = 0
        self.current_ua_index = (self.current_ua_index + 1) % len(StealthConfig.USER_AGENTS)
        self._setup_session()

class CloudflareBypass:
    """Handles Cloudflare and other anti-bot measures"""
    
    @staticmethod
    def detect_cloudflare_challenge(html_content: str, status_code: int = 200) -> bool:
        """Detect if page contains Cloudflare challenge or protection"""
        # 403 status code often indicates Cloudflare protection
        if status_code == 403:
            return True
            
        if not html_content:
            return False
            
        cloudflare_indicators = [
            'cf-browser-verification',
            'cf-challenge-page',
            'Checking your browser',
            'DDoS protection by Cloudflare',
            'Just a moment',
            'cf-spinner-redirecting',
            'Please wait while your request is being verified',
            'Ray ID:',
            'cloudflare',
            'Access denied',
            'Error 1020'
        ]
        
        return any(indicator.lower() in html_content.lower() for indicator in cloudflare_indicators)
    
    @staticmethod
    def detect_captcha(html_content: str) -> bool:
        """Detect if page contains CAPTCHA"""
        captcha_indicators = [
            'recaptcha',
            'h-captcha',
            'hcaptcha',
            'captcha',
            'verify you are human',
            'I\'m not a robot'
        ]
        
        return any(indicator.lower() in html_content.lower() for indicator in captcha_indicators)
    
    @staticmethod
    def should_try_selenium(html_content: str) -> bool:
        """Determine if Selenium should be used"""
        return (CloudflareBypass.detect_cloudflare_challenge(html_content) or 
                CloudflareBypass.detect_captcha(html_content))

def get_selenium_driver():
    """Get a stealth Selenium WebDriver if available"""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        
        # Try to use undetected-chromedriver if available
        try:
            import undetected_chromedriver as uc
            options = uc.ChromeOptions()
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            driver = uc.Chrome(options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            return driver
            
        except ImportError:
            # Fallback to regular Chrome with stealth settings
            options = Options()
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            # Random window size to avoid detection
            width = random.randint(1200, 1920)
            height = random.randint(800, 1080)
            options.add_argument(f'--window-size={width},{height}')
            
            driver = webdriver.Chrome(options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            return driver
            
    except ImportError:
        print("Selenium not available. Install with: pip install selenium undetected-chromedriver")
        return None

class ProxyRotator:
    """Handles proxy rotation for IP obfuscation"""
    
    def __init__(self, proxy_list: Optional[List[str]] = None):
        self.proxy_list = proxy_list or []
        self.current_proxy_index = 0
        self.failed_proxies = set()
    
    def get_next_proxy(self) -> Optional[Dict[str, str]]:
        """Get next working proxy"""
        if not self.proxy_list:
            return None
        
        available_proxies = [p for p in self.proxy_list if p not in self.failed_proxies]
        if not available_proxies:
            # Reset failed proxies if all failed
            self.failed_proxies.clear()
            available_proxies = self.proxy_list
        
        if not available_proxies:
            return None
        
        proxy = available_proxies[self.current_proxy_index % len(available_proxies)]
        self.current_proxy_index += 1
        
        return {
            'http': proxy,
            'https': proxy
        }
    
    def mark_proxy_failed(self, proxy: str):
        """Mark a proxy as failed"""
        self.failed_proxies.add(proxy)