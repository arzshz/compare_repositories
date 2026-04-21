import asyncio
from datetime import datetime as dt

from fastapi import APIRouter, HTTPException

from app.models.models import RepositoryRequest, GitHubAPIClient
from app.secrets.config import GITHUB_TOKEN
from app.services.functions import (
    fetch_repository_data,
    generate_markdown_table,
    parse_repository_url,
)

router = APIRouter()


@router.post("/compare-json")
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
    markdown_content, chart = generate_markdown_table(repos_data)
    markdown_content += f"\n![Star History Chart]({chart})"

    # Return JSON with markdown content
    return {
        "success": True,
        "markdown": markdown_content,
        "filename": f"repo_comparison_{dt.now().strftime('%Y%m%d_%H%M%S')}.md",
        "repo_count": len(repo_urls),
    }
