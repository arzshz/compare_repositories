import asyncio
import re
from typing import Optional

import httpx
from fastapi import HTTPException
from lxml import html
from pydantic import BaseModel


class RepositoryRequest(BaseModel):
    repositories: str  # One repository URL per line


class PDFRequest(BaseModel):
    markdown: str
    filename: str


class GitHubAPIClient:
    """Client for interacting with GitHub API"""

    def __init__(self, token: Optional[str] = None):
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        if token:
            self.headers["Authorization"] = f"token {token}"

    async def get_repo_info(self, owner: str, repo: str) -> dict:
        """Fetch basic repository information"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}",
                headers=self.headers,
                timeout=30.0,
            )

            if response.status_code == 404:
                raise HTTPException(
                    status_code=404, detail=f"Repository {owner}/{repo} not found"
                )
            elif response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"GitHub API error: {response.text}",
                )
            return response.json()

    async def get_languages(self, owner: str, repo: str) -> dict:
        """Fetch repository languages"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/languages",
                headers=self.headers,
                timeout=30.0,
            )
            if response.status_code == 200:
                return response.json()
            return {}

    async def get_contributors_count(self, owner: str, repo: str) -> int:
        """Fetch contributors count by scraping the repo page with lxml."""
        url = f"https://github.com/{owner}/{repo}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self.headers, timeout=30.0)
            if resp.status_code != 200:
                return 0
            doc = html.fromstring(resp.text)

            # 1) Prefer the <span title="N" class="Counter ..."> inside the Contributors link
            span_title = doc.xpath(
                '//h2[.//a[contains(@href,"/graphs/contributors") and contains(.,"Contributors")]]'
                '//span[contains(@class,"Counter") and @title]/@title'
            )
            if span_title:
                try:
                    return int(span_title[0].replace(",", ""))
                except ValueError:
                    pass

            # 2) Fallback: the "+ N contributors" link text
            alt_text = doc.xpath(
                '//a[contains(@href,"/graphs/contributors") and contains(normalize-space(.),"+")]/text()'
            )
            if alt_text:
                m = re.search(r"(\d[\d,]*)", alt_text[0])
                if m:
                    return int(m.group(1).replace(",", ""))
            return 0

    async def get_commits_info(self, owner: str, repo: str) -> dict:
        """Fetch commit information including total count and dates"""
        async with httpx.AsyncClient() as client:
            first_commit_date = await self.get_first_commit_date(owner, repo)

            # Get latest commit on default branch
            response_latest = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits?per_page=1",
                headers=self.headers,
                timeout=30.0,
            )

            last_commit_date = None

            if response_latest.status_code == 200 and response_latest.json():
                latest_commit = response_latest.json()[0]
                last_commit_date = latest_commit["commit"]["author"]["date"]

            # Get total commits count from first request
            commits_count = 0
            if response_latest.status_code == 200:
                link_header = response_latest.headers.get("Link", "")
                if "last" in link_header:
                    match = re.search(r'page=(\d+)>; rel="last"', link_header)
                    if match:
                        commits_count = int(match.group(1))
                else:
                    # Small repo, count directly
                    count_response = await client.get(
                        f"{self.base_url}/repos/{owner}/{repo}/commits?per_page=100",
                        headers=self.headers,
                        timeout=30.0,
                    )
                    if count_response.status_code == 200:
                        commits_count = len(count_response.json())

            return {
                "first_commit_date": first_commit_date,
                "last_commit_date": last_commit_date,
                "commits_count": commits_count,
            }

    async def get_first_commit_date(self, owner: str, repo: str) -> Optional[str]:
        async with httpx.AsyncClient(headers=self.headers, timeout=30.0) as client:
            # repo to get default branch
            r = await client.get(f"{self.base_url}/repos/{owner}/{repo}")
            if r.status_code != 200:
                return None
            default_branch = r.json().get("default_branch", "master")

            # request first page with per_page=1 to inspect Link header
            r = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits",
                params={"sha": default_branch, "per_page": 1},
            )
            if r.status_code != 200:
                return None

            link = r.headers.get("Link", "")
            if 'rel="last"' in link:
                m = re.search(r'<[^>]*[?&]page=(\d+)[^>]*>; rel="last"', link)
                if m:
                    last_page = int(m.group(1))
                else:
                    return None
                # fetch the last page with per_page=1 to get the oldest commit
                r = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}/commits",
                    params={"sha": default_branch, "per_page": 1, "page": last_page},
                )
                if r.status_code != 200:
                    return None
                commits = r.json()
                if not commits:
                    return None
                # commit date (committer.date if available, else author.date)
                c = commits[0].get("commit", {})
                date = c.get("committer", {}).get("date") or c.get("author", {}).get(
                    "date"
                )
                return date
            else:
                # single page only: that response contains newest commit; to get oldest, request with per_page=100 and take last item
                r = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}/commits",
                    params={"sha": default_branch, "per_page": 100},
                )
                if r.status_code != 200:
                    return None
                commits = r.json()
                if not commits:
                    return None
                c = commits[-1].get("commit", {})
                return c.get("committer", {}).get("date") or c.get("author", {}).get(
                    "date"
                )

    async def get_all_branches_last_commit(
        self, owner: str, repo: str
    ) -> Optional[str]:
        query = """
        query($owner:String!, $name:String!, $after:String) {
          repository(owner:$owner, name:$name) {
            refs(refPrefix:"refs/heads/", first:100, after:$after, orderBy:{field:TAG_COMMIT_DATE, direction:DESC}) {
              nodes {
                name
                target {
                  ... on Commit {
                    committedDate
                  }
                }
              }
              pageInfo { hasNextPage endCursor }
            }
          }
        }
        """
        async with httpx.AsyncClient(headers=self.headers, timeout=30.0) as client:
            after = None
            newest = None
            while True:
                resp = await client.post(
                    f"{self.base_url}/graphql",
                    json={
                        "query": query,
                        "variables": {"owner": owner, "name": repo, "after": after},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                refs = data["data"]["repository"]["refs"]
                for node in refs["nodes"]:
                    date = node.get("target", {}).get("committedDate")
                    if date:
                        if newest is None or date > newest:
                            newest = date
                if not refs["pageInfo"]["hasNextPage"]:
                    break
                after = refs["pageInfo"]["endCursor"]
            return newest

    async def get_releases_info(self, owner: str, repo: str) -> dict:
        """Fetch releases information"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/releases?per_page=1",
                headers=self.headers,
                timeout=30.0,
            )

            releases_count = 0
            last_release_date = None

            if response.status_code == 200:
                releases = response.json()

                # Get count from Link header
                link_header = response.headers.get("Link", "")
                if "last" in link_header:
                    match = re.search(r'page=(\d+)>; rel="last"', link_header)
                    if match:
                        releases_count = int(match.group(1))
                elif releases:
                    releases_count = len(releases)

                # Get last release date
                if releases:
                    last_release_date = releases[0].get("published_at")

            return {
                "releases_count": releases_count,
                "last_release_date": last_release_date,
            }

    async def get_readme_status(self, owner: str, repo: str) -> str:
        """Check README status"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/readme",
                headers=self.headers,
                timeout=30.0,
            )

            if response.status_code == 404:
                return "No README"

            if response.status_code == 200:
                readme_data = response.json()
                # Get actual content
                content_response = await client.get(
                    readme_data["download_url"], timeout=30.0
                )

                if content_response.status_code == 200:
                    content = content_response.text.strip()

                    # Check if it's default content (only repo name or very short)
                    if len(content) < 50 or content.lower() == repo.lower():
                        return "Default content"

                    return "Has README"

            return "No README"

    async def issues_count(self, owner: str, repo: str) -> dict:
        async with httpx.AsyncClient(headers=self.headers, timeout=30.0) as client:

            async def _count(state: str) -> int:
                q = f"repo:{owner}/{repo} is:issue is:{state}"
                params = {"q": q, "per_page": 1}
                r = await client.get(f"{self.base_url}/search/issues", params=params)
                r.raise_for_status()
                return r.json().get("total_count", 0)

            open_count, closed_count = await asyncio.gather(
                _count("open"), _count("closed")
            )
            return {"open": open_count, "closed": closed_count}

    async def get_pull_requests_count(self, owner: str, repo: str) -> dict:
        """Fetch UI-style open and closed pull request counts in one GraphQL request."""
        query = f"""
        {{
          open: search(query: "repo:{owner}/{repo} is:pr is:open", type: ISSUE) {{
            issueCount
          }}
          closed: search(query: "repo:{owner}/{repo} is:pr is:closed", type: ISSUE) {{
            issueCount
          }}
        }}
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/graphql",
                headers=self.headers,
                json={"query": query},
                timeout=30.0,
            )

            if response.status_code == 404:
                raise HTTPException(
                    status_code=404, detail=f"Repository {owner}/{repo} not found"
                )
            elif response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"GitHub API error: {response.text}",
                )

            data = response.json().get("data") or {}
            open_count = data.get("open", {}).get("issueCount", 0)
            closed_count = data.get("closed", {}).get("issueCount", 0)
            return {"open": open_count, "closed": closed_count}

    @staticmethod
    async def count_used_by(owner: str, repo: str) -> Optional[int]:
        url = f"https://github.com/{owner}/{repo}/network/dependents?dependent_type=REPOSITORY"
        headers = {"User-Agent": "python-httpx"}
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return 0
            doc = html.fromstring(r.text)
            # find the selected link under the Box-header that shows the Repositories count
            texts = doc.xpath(
                '//div[@class="Box-header"]//a[contains(@href,"/network/dependents") and contains(.,"Repositories") and contains(@class,"selected")]//text()'
            )
            if not texts:
                # fallback: any dependents repo link
                texts = doc.xpath(
                    '//a[contains(@href,"/network/dependents") and contains(.,"Repositories")]//text()'
                )
            combined = " ".join(t.strip() for t in texts if t.strip())
            m = re.search(r"([\d,]+)\s*Repositories", combined)
            if not m:
                m = re.search(r"([\d,]+)", combined)
            return int(m.group(1).replace(",", "")) if m else 0


# from selenium import webdriver
# from selenium.webdriver.chrome.options import Options
# from selenium.webdriver.chrome.service import Service
# from selenium.webdriver.common.by import By
# from selenium.webdriver.support import expected_conditions as EC
# from selenium.webdriver.support.ui import WebDriverWait
# from webdriver_manager.chrome import ChromeDriverManager
#
#
# class GitHubScraperSelenium:
#     """GitHub scraper using Selenium for JavaScript rendering"""
#
#     def __init__(self, headless: bool = True):
#         """
#         Initialize Selenium scraper
#
#         Args:
#             headless: Run browser in headless mode (no GUI)
#         """
#         self.headless = headless
#         self.driver = None
#
#     def _setup_driver(self):
#         """Setup Chrome driver with options"""
#         chrome_options = Options()
#
#         if self.headless:
#             chrome_options.add_argument("--headless")
#
#         chrome_options.add_argument("--no-sandbox")
#         chrome_options.add_argument("--disable-dev-shm-usage")
#         chrome_options.add_argument("--disable-gpu")
#         chrome_options.add_argument("--window-size=1920,1080")
#         chrome_options.add_argument(
#             "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
#         )
#
#         # Initialize driver
#         service = Service(ChromeDriverManager().install())
#         self.driver = webdriver.Chrome(service=service, options=chrome_options)
#         # self.driver = webdriver.Chrome(options=chrome_options)
#         self.driver.implicitly_wait(10)
#
#     def _close_driver(self):
#         """Close the driver"""
#         if self.driver:
#             self.driver.quit()
#             self.driver = None
#
#     async def get_contributors_count(self, owner: str, repo: str) -> int:
#         """
#         Fetch contributors count using Selenium
#
#         This method loads the GitHub page with JavaScript rendering
#         and extracts the contributors count.
#         """
#         return 0
#         url = f"https://github.com/{owner}/{repo}"
#
#         # Setup driver if not already setup
#         if not self.driver:
#             self._setup_driver()
#
#         try:
#             print(f"Loading {url}...")
#             self.driver.get(url)
#
#             # Wait for page to load
#             await asyncio.sleep(2)
#
#             # Method 1: Find by XPath - Contributors link with Counter span
#             try:
#                 # Wait for the contributors section to load
#                 contributors_link = WebDriverWait(self.driver, 10).until(
#                     EC.presence_of_element_located(
#                         (By.XPATH, "//a[contains(@href, '/graphs/contributors')]")
#                     )
#                 )
#
#                 # Find the Counter span near the Contributors link
#                 # The Counter span should be in the same parent or nearby
#                 try:
#                     counter_span = self.driver.find_element(
#                         By.XPATH,
#                         "//a[contains(@href, '/graphs/contributors')]//following-sibling::span[contains(@class, 'Counter')]",
#                     )
#
#                     # Get the title attribute (most reliable)
#                     title_value = counter_span.get_attribute("title")
#                     if title_value:
#                         count_str = title_value.replace(",", "")
#                         return int(count_str)
#
#                     # Fallback to text content
#                     text_value = counter_span.text.strip()
#                     if text_value:
#                         count_str = text_value.replace(",", "")
#                         return int(count_str)
#
#                 except:
#                     # Try parent element approach
#                     parent = contributors_link.find_element(By.XPATH, "..")
#                     counter_span = parent.find_element(By.CSS_SELECTOR, "span.Counter")
#
#                     title_value = counter_span.get_attribute("title")
#                     if title_value:
#                         count_str = title_value.replace(",", "")
#                         return int(count_str)
#
#             except Exception as e:
#                 print(f"Method 1 failed: {str(e)}")
#
#             # Method 2: Find all Counter spans and check context
#             try:
#                 counter_spans = self.driver.find_elements(
#                     By.CSS_SELECTOR, "span.Counter[title]"
#                 )
#
#                 for span in counter_spans:
#                     # Get parent text to verify it's the contributors counter
#                     parent = span.find_element(By.XPATH, "..")
#                     parent_text = parent.text.lower()
#
#                     if "contributor" in parent_text:
#                         title_value = span.get_attribute("title")
#                         if title_value:
#                             count_str = title_value.replace(",", "")
#                             return int(count_str)
#
#             except Exception as e:
#                 print(f"Method 2 failed: {str(e)}")
#
#             # Method 3: Search in page source
#             try:
#                 page_source = self.driver.page_source
#
#                 # Pattern: Looking for title="NUMBER" in Counter spans near "contributor"
#                 pattern = (
#                     r'<span[^>]*title="(\d+(?:,\d+)*)"[^>]*class="[^"]*Counter[^"]*"'
#                 )
#                 matches = re.finditer(pattern, page_source, re.IGNORECASE)
#
#                 for match in matches:
#                     # Get surrounding context
#                     start = max(0, match.start() - 500)
#                     end = min(len(page_source), match.end() + 500)
#                     context = page_source[start:end].lower()
#
#                     if "contributor" in context:
#                         count_str = match.group(1).replace(",", "")
#                         return int(count_str)
#
#             except Exception as e:
#                 print(f"Method 3 failed: {str(e)}")
#
#             print(f"Could not find contributors count for {owner}/{repo}")
#             return 0
#
#         except Exception as e:
#             print(f"Error with Selenium for {owner}/{repo}: {str(e)}")
#             return 0
#
#     def __enter__(self):
#         """Context manager entry"""
#         self._setup_driver()
#         return self
#
#     def __exit__(self, exc_type, exc_val, exc_tb):
#         """Context manager exit"""
#         self._close_driver()
