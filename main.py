import asyncio
import os
import re
from datetime import datetime
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from lxml import html
from pydantic import BaseModel

from config import GITHUB_TOKEN
from get_contributers import GitHubScraperSelenium

app = FastAPI(title="GitHub Repository Comparison API")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/images/favicon.png")


class RepositoryRequest(BaseModel):
    repositories: str  # One repository URL per line


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
        QUERY = """
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
                        "query": QUERY,
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


def parse_repository_url(url: str) -> tuple[str, str] | None:
    try:
        # remove scheme
        if "://" in url:
            url = url.split("://", 1)[1]
        # remove leading www.
        if url.lower().startswith("www."):
            url = url[4:]
        # ensure domain is github.com
        if not url.lower().startswith("github.com/"):
            ValueError(f"Invalid GitHub URL. It must starts with github.com: {url}")
        # strip domain and split path
        path = url[len("github.com/") :]
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2:
            ValueError(
                f"Invalid GitHub URL. It must contain owner and repo like github.com/[owner]/[repo]: {url}"
            )
        owner, repo = parts[0], parts[1]
        # strip possible .git suffix from repo
        if repo.endswith(".git"):
            repo = repo[:-4]
        return owner, repo
    except Exception:
        ValueError(f"Invalid GitHub URL: {url}")


def calculate_programming_language(languages: dict) -> str:
    """Calculate programming language display based on the algorithm"""
    if not languages:
        return "N/A"

    # Calculate total bytes
    total_bytes = sum(languages.values())
    if total_bytes == 0:
        return "N/A"

    # Calculate percentages
    lang_percentages = [
        (lang, (bytes_count / total_bytes) * 100)
        for lang, bytes_count in languages.items()
    ]

    # Sort by percentage descending
    lang_percentages.sort(key=lambda x: x[1], reverse=True)

    if not lang_percentages:
        return "N/A"

    # Rule 1: If largest > 80%, show only that language
    if lang_percentages[0][1] > 80:
        return f"{lang_percentages[0][0]} {lang_percentages[0][1]:.1f}%"

    # Rule 2 & 3: Show top 2 languages
    if len(lang_percentages) >= 2:
        top_two_sum = lang_percentages[0][1] + lang_percentages[1][1]

        if top_two_sum > 80:
            # Rule 2: Just show top 2
            return f"{lang_percentages[0][0]} {lang_percentages[0][1]:.1f}%, {lang_percentages[1][0]} {lang_percentages[1][1]:.1f}%"
        else:
            # Rule 3: Show top 2 + others
            others_percent = 100 - top_two_sum
            return f"{lang_percentages[0][0]} {lang_percentages[0][1]:.1f}%, {lang_percentages[1][0]} {lang_percentages[1][1]:.1f}%, others {others_percent:.1f}%"

    # Only one language
    return f"{lang_percentages[0][0]} {lang_percentages[0][1]:.1f}%"


def format_relative_date(date_str: Optional[str]) -> str:
    """Format date as relative time (e.g., '2 days ago')"""
    if not date_str:
        return "N/A"

    try:
        date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        now = datetime.now(date.tzinfo)
        diff = now - date

        seconds = diff.total_seconds()

        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif seconds < 2592000:  # 30 days
            days = int(seconds / 86400)
            return f"{days} day{'s' if days != 1 else ''} ago"
        elif seconds < 31536000:  # 365 days
            months = int(seconds / 2592000)
            return f"{months} month{'s' if months != 1 else ''} ago"
        else:
            years = int(seconds / 31536000)
            return f"{years} year{'s' if years != 1 else ''} ago"
    except Exception:
        return "N/A"


def format_date(date_str: Optional[str]) -> str:
    """Format date as YYYY-MM-DD"""
    if not date_str:
        return "N/A"

    try:
        date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return date.strftime("%Y-%m-%d")
    except Exception:
        return "N/A"


async def fetch_repository_data(
    github_client: GitHubAPIClient, owner: str, repo: str, url: str
) -> dict:
    """Fetch all data for a single repository"""
    try:
        # Fetch all data concurrently
        # (
        #     repo_info,
        #     languages,
        #     commits_info,
        #     releases_info,
        #     readme_status,
        #     issues_count,
        #     used_by_count,
        # ) = await asyncio.gather(
        #     github_client.get_repo_info(owner, repo),
        #     github_client.get_languages(owner, repo),
        #     github_client.get_commits_info(owner, repo),
        #     github_client.get_releases_info(owner, repo),
        #     github_client.get_readme_status(owner, repo),
        #     github_client.issues_count(owner, repo),
        #     github_client.count_used_by(owner, repo),
        # )

        # Get contributors count separately
        # with GitHubScraperSelenium(headless=True) as scraper:
        #     contributors_count = await scraper.get_contributors_count(owner, repo)
        # contributors_count = await github_client.get_contributors_count(owner, repo)

        with GitHubScraperSelenium(headless=True) as scraper:
            (
                contributors_count,
                repo_info,
                languages,
                commits_info,
                releases_info,
                readme_status,
                issues_count,
                used_by_count,
            ) = await asyncio.gather(
                scraper.get_contributors_count(owner, repo),
                github_client.get_repo_info(owner, repo),
                github_client.get_languages(owner, repo),
                github_client.get_commits_info(owner, repo),
                github_client.get_releases_info(owner, repo),
                github_client.get_readme_status(owner, repo),
                github_client.issues_count(owner, repo),
                github_client.count_used_by(owner, repo),
            )

        # Get last commit across all branches
        last_commit_all_branches = await github_client.get_all_branches_last_commit(
            owner, repo
        )

        return {
            "url": url,
            "name": repo_info["name"],
            "owner": repo_info["owner"]["login"],
            "is_forked": "Yes" if repo_info.get("fork", False) else "No",
            "stars": repo_info["stargazers_count"],
            "forks": repo_info["forks_count"],
            "watchers": repo_info["subscribers_count"],
            "license": repo_info.get("license", {}).get("spdx_id", "N/A")
            if repo_info.get("license")
            else "N/A",
            "language": calculate_programming_language(languages),
            "contributors": contributors_count,
            "open_issues": issues_count["open"],
            "closed_issues": issues_count["closed"],
            "used_by": used_by_count,
            "commits": commits_info["commits_count"],
            "first_commit": format_date(commits_info["first_commit_date"]),
            "last_commit_main": format_relative_date(commits_info["last_commit_date"]),
            "last_commit_all": format_relative_date(last_commit_all_branches),
            "releases": releases_info["releases_count"],
            "last_release": format_date(releases_info["last_release_date"]),
            "readme": readme_status,
        }
    except Exception as e:
        # Return error data
        return {"url": url, "name": repo, "error": str(e)}


def generate_markdown_table(repos_data: List[dict]) -> str:
    """Generate markdown comparison table"""
    # Build table header
    markdown = "# GitHub Repository Comparison\n\n"
    markdown += "| Repo Name | Owner Name | Is Forked? | Stars Count | Forks Count | Watchers Count | License | Programming Language | Contributors Count | Open Issues  | Closed Issues | Used By | Commits Count | First Commit Date | Last Commit Date (main branch) | Last Commit Date (all branches) | Releases Count | Last Release Date | Has README |\n"
    markdown += "|-----------|------------|------------|-------------|-------------|----------------|---------|---------------------|-------------------|---------------|---------------|---------|---------------|-------------------|-------------------------------|--------------------------------|----------------|-------------------|------------|\n"

    # Add rows
    for repo in repos_data:
        if "error" in repo:
            # Show error row
            markdown += f"| [{repo['name']}]({repo['url']}) | ERROR | {repo['error']} | - | - | - | - | - | - | - | - | - | - | - | - | - |\n"
        else:
            markdown += f"| [{repo['name']}]({repo['url']}) | {repo['owner']} | {repo['is_forked']} | {repo['stars']} | {repo['forks']} | {repo['watchers']} | {repo['license']} | {repo['language']} | {repo['contributors']} | {repo['open_issues']} | {repo['closed_issues']} | {repo['used_by']} | {repo['commits']} | {repo['first_commit']} | {repo['last_commit_main']} | {repo['last_commit_all']} | {repo['releases']} | {repo['last_release']} | {repo['readme']} |\n"

    return markdown


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the web interface"""
    html_file = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_file, "r") as f:
        return f.read()


@app.get("/api/info")
async def api_info():
    """API information endpoint"""
    return {
        "message": "GitHub Repository Comparison API",
        "usage": "POST /compare with repositories (one URL per line)",
        "example": {
            "repositories": "https://github.com/owner1/repo1\nhttps://github.com/owner2/repo2"
        },
    }


@app.post("/compare")
async def compare_repositories(request: RepositoryRequest):
    """
    Compare GitHub repositories and return a markdown comparison table.

    Input: List of GitHub repository URLs (one per line)
    Output: Markdown file with comparison table
    """
    # Parse repository URLs
    repo_urls = [url.strip() for url in request.repositories.split("\n") if url.strip()]

    if not repo_urls:
        raise HTTPException(status_code=400, detail="No repository URLs provided")

    if len(repo_urls) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 repositories allowed")

    # Parse URLs
    repos_to_fetch = []
    for url in repo_urls:
        try:
            owner, repo = parse_repository_url(url)
            repos_to_fetch.append((owner, repo, url))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Initialize GitHub client
    github_client = GitHubAPIClient(GITHUB_TOKEN)

    # Fetch data for all repositories
    tasks = [
        fetch_repository_data(github_client, owner, repo, url)
        for owner, repo, url in repos_to_fetch
    ]

    repos_data = await asyncio.gather(*tasks)

    # Generate markdown
    markdown_content = generate_markdown_table(repos_data)

    # Save to file
    filename = f"repo_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    filepath = f"/tmp/{filename}"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(markdown_content)

    # Return file
    return FileResponse(filepath, media_type="text/markdown", filename=filename)


@app.post("/compare-json")
async def compare_repositories_json(request: RepositoryRequest):
    """
    Compare GitHub repositories and return JSON with markdown content.
    Used by the web interface to show preview and download options.
    """
    # Parse repository URLs
    repo_urls = [url.strip() for url in request.repositories.split("\n") if url.strip()]

    if not repo_urls:
        raise HTTPException(status_code=400, detail="No repository URLs provided")

    if len(repo_urls) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 repositories allowed")

    # Parse URLs
    repos_to_fetch = []
    for url in repo_urls:
        try:
            owner, repo = parse_repository_url(url)
            repos_to_fetch.append((owner, repo, url))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Initialize GitHub client
    github_client = GitHubAPIClient(GITHUB_TOKEN)

    # Fetch data for all repositories
    tasks = [
        fetch_repository_data(github_client, owner, repo, url)
        for owner, repo, url in repos_to_fetch
    ]

    repos_data = await asyncio.gather(*tasks)

    # Generate markdown
    markdown_content = generate_markdown_table(repos_data)

    # Return JSON with markdown content
    return {
        "success": True,
        "markdown": markdown_content,
        "filename": f"repo_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
        "repo_count": len(repo_urls),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
