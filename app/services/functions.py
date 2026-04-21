import asyncio
import io
import xml.etree.ElementTree as ET
from datetime import datetime as dt
from pathlib import Path
from typing import List, Tuple
from typing import Optional

import cairosvg
import requests
from PIL import Image
from weasyprint import HTML

from app.models.models import GitHubAPIClient


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
    except Exception as e:
        ValueError(f"Invalid GitHub URL: {url}\nException:\n{e}")


def _escape(cell: object) -> str:
    if cell is None:
        return ""
    text = str(cell)
    # escape pipe to avoid breaking markdown table
    return text.replace("|", "\\|")


def generate_markdown_table(repos_data: List[dict]) -> Tuple[str, str]:
    """Generate transposed markdown comparison table (repos as columns)."""
    # Define the ordered attributes and friendly labels
    fields = [
        ("name", "Repo Name"),
        ("owner", "Owner Name"),
        ("is_forked", "Is Forked?"),
        ("stars", "Stars Count"),
        ("forks", "Forks Count"),
        ("watchers", "Watchers Count"),
        ("license", "License"),
        ("language", "Programming Language"),
        ("contributors", "Contributors Count"),
        ("open_issues", "Open Issues"),
        ("closed_issues", "Closed Issues"),
        ("open_pr", "Open Pull Requests"),
        ("closed_pr", "Closed Pull Requests"),
        ("used_by", "Used By"),
        ("commits", "Commits Count"),
        ("first_commit", "First Commit Date"),
        ("last_commit_main", "Last Commit Date (main branch)"),
        ("last_commit_all", "Last Commit Date (all branches)"),
        ("releases", "Releases Count"),
        ("last_release", "Last Release Date"),
        ("readme", "Has README"),
    ]

    # Build header row: first empty cell for attribute labels, then one column per repo
    header = ["Attribute"] + [
        _escape(repo.get("name", f"repo_{i}"))
        if "error" not in repo
        else _escape(repo.get("name", f"repo_{i}"))
        for i, repo in enumerate(repos_data)
    ]
    markdown_lines = ["| " + " | ".join(header) + " |"]

    # Separator line: align left for attribute column and center for repo columns
    separator = ["---"] + ["---"] * len(repos_data)
    markdown_lines.append("| " + " | ".join(separator) + " |")

    # For each field, build a row with the field label followed by each repo's value
    for key, label in fields:
        row = [f"**{label}**"]
        for repo in repos_data:
            if "error" in repo:
                # show the error message in the repo column if present
                val = repo.get("error") if key == "name" or key == "url" else "-"
            else:
                if key == "name":
                    # show URL as link using repo name if available
                    name = repo.get("name", "")
                    url = repo.get("url", "")
                    val = f"[{_escape(name)}]({url})" if url else _escape(name)
                else:
                    val = repo.get(key, "-")
            row.append(_escape(val))
        markdown_lines.append("| " + " | ".join(row) + " |")

    # Build star-history chart query (concatenated repos)
    chart = "https://api.star-history.com/chart?repos="
    chart += "%2C".join(
        f"{repo['owner']}/{repo['name']}"
        for repo in repos_data
        if "error" not in repo and repo.get("owner") and repo.get("name")
    )
    chart += "&type=date&legend=top-left"

    markdown = "# GitHub Repository Comparison\n\n" + "\n".join(markdown_lines) + "\n"
    return markdown, chart


async def fetch_repository_data(
    github_client: GitHubAPIClient, owner: str, repo: str, url: str
) -> dict:
    """Fetch all data for a single repository"""
    try:
        # Fetch all data concurrently
        (
            repo_info,
            languages,
            commits_info,
            releases_info,
            readme_status,
            issues_count,
            pull_requests_count,
            used_by_count,
        ) = await asyncio.gather(
            github_client.get_repo_info(owner, repo),
            github_client.get_languages(owner, repo),
            github_client.get_commits_info(owner, repo),
            github_client.get_releases_info(owner, repo),
            github_client.get_readme_status(owner, repo),
            github_client.issues_count(owner, repo),
            github_client.get_pull_requests_count(owner, repo),
            github_client.count_used_by(owner, repo),
        )

        # Get contributors count separately
        # with GitHubScraperSelenium(headless=True) as scraper:
        #     contributors_count = await scraper.get_contributors_count(owner, repo)
        contributors_count = await github_client.get_contributors_count(owner, repo)

        # with GitHubScraperSelenium(headless=True) as scraper:
        #     (
        #         contributors_count,
        #         repo_info,
        #         languages,
        #         commits_info,
        #         releases_info,
        #         readme_status,
        #         issues_count,
        #         pull_requests_count,
        #         used_by_count,
        #     ) = await asyncio.gather(
        #         scraper.get_contributors_count(owner, repo),
        #         github_client.get_repo_info(owner, repo),
        #         github_client.get_languages(owner, repo),
        #         github_client.get_commits_info(owner, repo),
        #         github_client.get_releases_info(owner, repo),
        #         github_client.get_readme_status(owner, repo),
        #         github_client.issues_count(owner, repo),
        #         github_client.get_pull_requests_count(owner, repo),
        #         github_client.count_used_by(owner, repo),
        #     )

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
            "open_pr": pull_requests_count["open"],
            "closed_pr": pull_requests_count["closed"],
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


def format_date(date_str: Optional[str]) -> str:
    """Format date as YYYY-MM-DD"""
    if not date_str:
        return "N/A"

    try:
        date = dt.fromisoformat(date_str.replace("Z", "+00:00"))
        return date.strftime("%Y-%m-%d")
    except Exception:
        return "N/A"


def format_relative_date(date_str: Optional[str]) -> str:
    """Format date as relative time (e.g., '2 days ago')"""
    if not date_str:
        return "N/A"

    try:
        date = dt.fromisoformat(date_str.replace("Z", "+00:00"))
        now = dt.now(date.tzinfo)
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


def download_png(url: str, png_filename: str) -> str:
    dest = Path(__file__).resolve().parent / "images" / png_filename
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Fetch SVG
    headers = {"User-Agent": "python-requests/2.x"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    svg_bytes = r.content
    if b"<svg" not in svg_bytes[:1000].lower():
        raise ValueError("Downloaded content does not look like an SVG.")

    # Parse SVG preserving namespaces
    parser = ET.XMLParser()
    root = ET.fromstring(svg_bytes, parser=parser)

    def local_name(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    def style_to_dict(style: str) -> dict:
        kv = {}
        for part in style.split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                kv[k.strip()] = v.strip()
        return kv

    # Remove matching <text> and <image> nodes
    for parent in list(root.iter()):
        for child in list(parent):
            lname = local_name(child.tag)
            attrib = child.attrib

            if lname == "text":
                style = attrib.get("style", "")
                text_anchor = attrib.get("text-anchor", "")
                transform = attrib.get("transform", "")
                y_attr = attrib.get("y", "")
                style_kv = style_to_dict(style)
                font_size = style_kv.get("font-size", "")
                font_weight = style_kv.get("font-weight", "")
                fill = style_kv.get("fill", "")
                text_content = (child.text or "").strip().lower()

                # Match big centered title (example)
                if (
                    text_anchor == "middle"
                    and (font_weight == "700" or font_weight == "bold")
                    and (font_size.startswith("20") or font_size == "20px")
                ):
                    if (
                        not y_attr
                        or y_attr.strip() == "30"
                        or y_attr.strip().startswith("30")
                    ):
                        parent.remove(child)
                        continue

                # Match small gray label with transform (example)
                if (
                    transform
                    and (font_size.startswith("16") or font_size == "16px")
                    and fill in ("#666", "#666666", "rgb(102,102,102)")
                ):
                    parent.remove(child)
                    continue

                # Fallback: exact text content "star"
                if text_content == "star":
                    parent.remove(child)
                    continue

            # Remove the specific <image> element (data URI + transform example)
            if lname == "image":
                width = attrib.get("width", "")
                height = attrib.get("height", "")
                href = (
                    attrib.get("{http://www.w3.org/1999/xlink}href")
                    or attrib.get("href")
                    or attrib.get("xlink:href")
                )
                transform = attrib.get("transform", "")
                # Match by width/height and data: URI (base64) presence and transform
                if (
                    width == "20"
                    and height == "20"
                    and href
                    and href.startswith("data:image/png;base64,")
                    and transform
                ):
                    parent.remove(child)
                    continue

    # Serialize modified SVG back to bytes
    modified_svg = ET.tostring(root, encoding="utf-8", method="xml")

    # Render SVG to PNG at higher resolution then save
    png_bytes = cairosvg.svg2png(bytestring=modified_svg, scale=3.0)
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    img.save(dest, format="PNG", optimize=True)

    return str(dest)


def markdown_to_pdf(html, output_path="output.pdf", image_path=""):
    # html = markdown.markdown(md_text, extensions=["tables"])

    # Wrap the FIRST table + the title in a landscape wrapper
    html = html.replace("<h1>", '<div class="landscape-wrapper"><h1>', 1)
    html = html.replace("</table>", "</table></div>", 1)

    html_template = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <style>

            /* Default portrait pages */
            @page {{
                size: A4 landscape;
                margin: 20mm;
            }}

            /* Landscape page for the first wrapper */
            @page landscape-page {{
                size: A4 landscape;
                margin: 15mm;
            }}

            /* Apply landscape to the wrapper */
            .landscape-wrapper {{
                page: landscape-page;
                page-break-before: always;
                page-break-after: always;
            }}

            body {{
                font-family: sans-serif;
                margin: 20px;
            }}

            h1 {{
                color: #333;
                margin-bottom: 15px;
                font-size: 22px;
                text-align: center;
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 20px auto;
                page-break-inside: avoid;
                font-size: 12px;
                table-layout: auto;
            }}

            table + table {{
                page-break-before: always;
            }}

            th, td {{
                border: 1px solid #ccc;
                padding: 6px 4px;
                text-align: left;
                font-size: 14px;
            }}

            th {{
                background: #667eea;
                color: white;
                font-weight: 600;
            }}

            tr:nth-child(even) td {{
                background: #f8f9fa;
            }}

            img {{
                max-width: 100%;
            }}

            /* Compact styling ONLY for the first table */
            .landscape-wrapper table {{
                table-layout: fixed;
                width: 100%;
                font-size: 10px;
            }}

            .landscape-wrapper th,
            .landscape-wrapper td {{
                padding: 4px 3px;
                font-size: 9px;
                border: 1px solid #bbb;
                word-wrap: break-word;
            }}

            .landscape-wrapper th {{
                font-size: 9px;
            }}

        </style>
    </head>
    <body>
        {html}
        <img src="{image_path}"
            style="display:block; max-width:100%; page-break-before: always;">

    </body>
    </html>
    """

    HTML(string=html_template, base_url=".").write_pdf(output_path)
