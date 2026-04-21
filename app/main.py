import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.compare import router as compare_route
from app.api.compare_json import router as compare_json_route
from app.api.generate_pdf import router as generate_pdf_route
from app.api.info import router as info_route

app = FastAPI(title="GitHub Repository Comparison API")
file_path = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=file_path), name="static")
app.include_router(compare_route)
app.include_router(compare_json_route)
app.include_router(generate_pdf_route)
app.include_router(info_route)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    file_path = os.path.join(os.path.dirname(__file__), "static/images/favicon.png")
    return FileResponse(file_path)


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the web interface"""
    html_file = os.path.join(os.path.dirname(__file__), "template/index.html")
    with open(html_file, "r") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
