import asyncio
import re

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


class GitHubScraperSelenium:
    """GitHub scraper using Selenium for JavaScript rendering"""

    def __init__(self, headless: bool = True):
        """
        Initialize Selenium scraper

        Args:
            headless: Run browser in headless mode (no GUI)
        """
        self.headless = headless
        self.driver = None

    def _setup_driver(self):
        """Setup Chrome driver with options"""
        chrome_options = Options()

        if self.headless:
            chrome_options.add_argument("--headless")

        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )

        # Initialize driver
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        # self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.implicitly_wait(10)

    def _close_driver(self):
        """Close the driver"""
        if self.driver:
            self.driver.quit()
            self.driver = None

    async def get_contributors_count(self, owner: str, repo: str) -> int:
        """
        Fetch contributors count using Selenium

        This method loads the GitHub page with JavaScript rendering
        and extracts the contributors count.
        """
        url = f"https://github.com/{owner}/{repo}"

        # Setup driver if not already setup
        if not self.driver:
            self._setup_driver()

        try:
            print(f"Loading {url}...")
            self.driver.get(url)

            # Wait for page to load
            await asyncio.sleep(2)

            # Method 1: Find by XPath - Contributors link with Counter span
            try:
                # Wait for the contributors section to load
                contributors_link = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//a[contains(@href, '/graphs/contributors')]")
                    )
                )

                # Find the Counter span near the Contributors link
                # The Counter span should be in the same parent or nearby
                try:
                    counter_span = self.driver.find_element(
                        By.XPATH,
                        "//a[contains(@href, '/graphs/contributors')]//following-sibling::span[contains(@class, 'Counter')]",
                    )

                    # Get the title attribute (most reliable)
                    title_value = counter_span.get_attribute("title")
                    if title_value:
                        count_str = title_value.replace(",", "")
                        return int(count_str)

                    # Fallback to text content
                    text_value = counter_span.text.strip()
                    if text_value:
                        count_str = text_value.replace(",", "")
                        return int(count_str)

                except:
                    # Try parent element approach
                    parent = contributors_link.find_element(By.XPATH, "..")
                    counter_span = parent.find_element(By.CSS_SELECTOR, "span.Counter")

                    title_value = counter_span.get_attribute("title")
                    if title_value:
                        count_str = title_value.replace(",", "")
                        return int(count_str)

            except Exception as e:
                print(f"Method 1 failed: {str(e)}")

            # Method 2: Find all Counter spans and check context
            try:
                counter_spans = self.driver.find_elements(
                    By.CSS_SELECTOR, "span.Counter[title]"
                )

                for span in counter_spans:
                    # Get parent text to verify it's the contributors counter
                    parent = span.find_element(By.XPATH, "..")
                    parent_text = parent.text.lower()

                    if "contributor" in parent_text:
                        title_value = span.get_attribute("title")
                        if title_value:
                            count_str = title_value.replace(",", "")
                            return int(count_str)

            except Exception as e:
                print(f"Method 2 failed: {str(e)}")

            # Method 3: Search in page source
            try:
                page_source = self.driver.page_source

                # Pattern: Looking for title="NUMBER" in Counter spans near "contributor"
                pattern = (
                    r'<span[^>]*title="(\d+(?:,\d+)*)"[^>]*class="[^"]*Counter[^"]*"'
                )
                matches = re.finditer(pattern, page_source, re.IGNORECASE)

                for match in matches:
                    # Get surrounding context
                    start = max(0, match.start() - 500)
                    end = min(len(page_source), match.end() + 500)
                    context = page_source[start:end].lower()

                    if "contributor" in context:
                        count_str = match.group(1).replace(",", "")
                        return int(count_str)

            except Exception as e:
                print(f"Method 3 failed: {str(e)}")

            print(f"Could not find contributors count for {owner}/{repo}")
            return 0

        except Exception as e:
            print(f"Error with Selenium for {owner}/{repo}: {str(e)}")
            return 0

    def __enter__(self):
        """Context manager entry"""
        self._setup_driver()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self._close_driver()
