from fastapi import APIRouter

router = APIRouter()


@router.get("/api/info")
async def api_info():
    """API information endpoint"""
    return {
        "message": "GitHub Repository Comparison API",
        "usage": "POST /compare with repositories (one URL per line)",
        "example": {
            "repositories": "https://github.com/owner1/repo1\nhttps://github.com/owner2/repo2"
        },
    }
