# GitHub Repository Comparison API

A FastAPI-based REST API that compares multiple GitHub repositories and generates a comprehensive markdown comparison table.

## Features

- **Comprehensive Repository Analysis**: Fetches detailed information from GitHub API including:
  - Basic info (owner, stars, forks, watchers)
  - Language breakdown with intelligent aggregation
  - Contributor and commit statistics
  - Release information
  - README quality detection
  - Fork status and license information

- **Smart Language Detection**: Uses a three-tier algorithm to display programming languages:
  1. Single language if > 80% of codebase
  2. Top 2 languages if combined > 80%
  3. Top 2 languages + "others" percentage

- **README Quality Detection**: Three states:
  - "No README": No README file exists
  - "Default content": README contains only default/minimal content
  - "Has README": README has meaningful content

- **Markdown Output**: Generates a clean, formatted markdown table with clickable repository links

## Installation

### Prerequisites

- Python 3.8 or higher
- pip package manager

### Setup

1. **Clone or download the repository**

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **(Optional) Set GitHub Personal Access Token:**

   For higher rate limits (5000 requests/hour vs 60 for unauthenticated):

   ```bash
   export GITHUB_TOKEN="your_github_token_here"
   ```

   You can create a token at: https://github.com/settings/tokens

## Usage

### Starting the API Server

Run the FastAPI server:

```bash
python main.py
```

Or using uvicorn directly:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at: `http://localhost:8000`

### Web Interface (Recommended)

**Simply open your browser and visit: `http://localhost:8000`**

You'll see a beautiful, fully responsive web interface with:

#### Features:
- ✨ **Modern, responsive design** - Works perfectly on iPhone, Android, tablets, and laptops
- 📝 **Easy input** - Enter repository URLs or click example sets
- 🔄 **Real-time feedback** - Loading spinner and status updates
- ✅ **Success screen** - Clear confirmation when comparison is complete
- 👁️ **View Markdown** - Preview the comparison table directly in your browser
- ⬇️ **Download File** - Save the markdown file to your device
- 🔁 **Compare More** - Easily start a new comparison

#### How to Use:
1. Enter GitHub repository URLs (one per line)
2. Or click one of the example sets to try it out
3. Click "Compare Repositories"
4. Wait for the comparison to complete
5. Click "View Markdown" to see the formatted table
6. Click "Download File" to save the .md file
7. Click "Compare New Repositories" to start over

### Alternative: API Documentation

Once the server is running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### API Endpoint

**POST** `/compare`

#### Request Body

```json
{
  "repositories": "https://github.com/owner1/repo1\nhttps://github.com/owner2/repo2\nhttps://github.com/owner3/repo3"
}
```

The `repositories` field should contain GitHub repository URLs separated by newlines (`\n`).

#### Example using cURL

```bash
curl -X POST "http://localhost:8000/compare" \
  -H "Content-Type: application/json" \
  -d '{
    "repositories": "https://github.com/fastapi/fastapi\nhttps://github.com/django/django\nhttps://github.com/pallets/flask"
  }'
```

#### Example using Python requests

```python
import requests

repos = """
https://github.com/fastapi/fastapi
https://github.com/django/django
https://github.com/pallets/flask
""".strip()

response = requests.post(
    "http://localhost:8000/compare",
    json={"repositories": repos}
)

# Save the markdown file
with open("comparison.md", "wb") as f:
    f.write(response.content)

print("Comparison saved to comparison.md")
```

### Response

The API returns a markdown file (`.md`) that can be downloaded. The filename format is: `repo_comparison_YYYYMMDD_HHMMSS.md`

### Sample Output

The generated markdown table looks like this:

| Repo Name | Owner Name | Is Forked? | Stars Count | Forks Count | Watchers Count | License | Programming Language | Contributors Count | Open Issues | Closed Issues | Used By | Commits Count | First Commit Date | Last Commit Date (main branch) | Last Commit Date (all branches) | Releases Count  | Last Release Date | Has README |
|-----------|------------|------------|-------------|-------------|----------------|---------|---------------------|--------------------|------------|---------------|---------|---------------|-------------------|-------------------------------|---------------------------------|-----------------|-------------------|------------|
| [fastapi](https://github.com/fastapi/fastapi) | fastapi | No | 95129 | 8690 | 730 | MIT | Python 100.0% | 898 | 12 | 3491 | 844998 | 6789 | 2018-12-05 | 2 days ago | 2 days ago | 258 | 2026-02-12 | Has README |

## Comparison Table Columns

| Column                          | Description                                                |
|---------------------------------|------------------------------------------------------------|
| Repo Name                       | Clickable link to the GitHub repository                    |
| Owner Name                      | Name of the repository owner                               |
| Is Forked?                      | Whether this repo is forked from another repo (Yes/No)     |
| Stars Count                     | Number of stars                                            |
| Forks Count                     | Number of forks                                            |
| Watchers Count                  | Number of watchers                                         |
| License                         | License type (e.g., MIT, Apache-2.0)                       |
| Programming Language            | Calculated using the smart algorithm                       |
| Contributors Count              | Number of contributors                                     |
| Open Issues                     | Number of open issues                                      |
| Closed Issues                   | Number of closed issues                                    |
| Used By                         | Number of repositories that depend on the repo             |
| Commits Count                   | Total number of commits                                    |
| First Commit Date               | Date of first commit (YYYY-MM-DD)                          |
| Last Commit Date (main branch)  | Most recent commit on main/master branch (relative format) |
| Last Commit Date (all branches) | Most recent commit across all branches (relative format)   |
| Releases Count                  | Number of published releases                               |
| Last Release Date               | Date of last release (YYYY-MM-DD)                          |
| Has README                      | README status (No README / Default content / Has README)   |

## Limitations

- **Rate Limits**: GitHub API has rate limits:
  - Unauthenticated: 60 requests/hour
  - Authenticated: 5000 requests/hour
- **Maximum Repositories**: Limited to 20 repositories per request to avoid timeouts

## Error Handling

The API includes comprehensive error handling:

- Invalid repository URLs return 400 Bad Request
- Non-existent repositories return 404 Not Found
- GitHub API errors are properly propagated
- Network timeouts are handled gracefully

## Troubleshooting

### Rate Limit Exceeded

If you hit GitHub's rate limit:

1. Use a Personal Access Token (see installation section)
2. Wait for the rate limit to reset (check `X-RateLimit-Reset` header)
3. Reduce the number of repositories per request

### Slow Response Times

For repositories with many commits/contributors:

- The API may take 10-30 seconds to process
- Consider using fewer repositories per request
- Use authenticated requests for better performance

## Technical Details

### Architecture

- **FastAPI**: Modern Python web framework with automatic OpenAPI docs
- **httpx**: Async HTTP client for concurrent GitHub API requests

## API Endpoints Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API information and usage |
| GET | `/docs` | Interactive Swagger documentation |
| GET | `/redoc` | Alternative ReDoc documentation |
| POST | `/compare` | Compare repositories and get markdown file |
