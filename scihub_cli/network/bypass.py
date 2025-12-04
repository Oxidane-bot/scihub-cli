"""
Cloudflare bypass utilities and detection.
"""

from ..utils.logging import get_logger

logger = get_logger(__name__)


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
            "cf-browser-verification",
            "cf-challenge-page",
            "Checking your browser",
            "DDoS protection by Cloudflare",
            "Just a moment",
            "cf-spinner-redirecting",
            "Please wait while your request is being verified",
            "Ray ID:",
            "cloudflare",
            "Access denied",
            "Error 1020",
        ]

        return any(indicator.lower() in html_content.lower() for indicator in cloudflare_indicators)

    @staticmethod
    def detect_captcha(html_content: str) -> bool:
        """Detect if page contains CAPTCHA"""
        captcha_indicators = [
            "recaptcha",
            "h-captcha",
            "hcaptcha",
            "captcha",
            "verify you are human",
            "I'm not a robot",
        ]

        return any(indicator.lower() in html_content.lower() for indicator in captcha_indicators)

    @staticmethod
    def should_try_selenium(html_content: str) -> bool:
        """Determine if Selenium should be used"""
        return CloudflareBypass.detect_cloudflare_challenge(
            html_content
        ) or CloudflareBypass.detect_captcha(html_content)


def get_selenium_driver():
    """Get a stealth Selenium WebDriver if available"""
    try:
        import random

        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        # Try to use undetected-chromedriver if available
        try:
            import undetected_chromedriver as uc

            options = uc.ChromeOptions()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)

            driver = uc.Chrome(options=options)
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            return driver

        except ImportError:
            # Fallback to regular Chrome with stealth settings
            options = Options()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)

            # Random window size to avoid detection
            width = random.randint(1200, 1920)
            height = random.randint(800, 1080)
            options.add_argument(f"--window-size={width},{height}")

            driver = webdriver.Chrome(options=options)
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            return driver

    except ImportError:
        logger.warning(
            "Selenium not available. Install with: pip install selenium undetected-chromedriver"
        )
        return None
