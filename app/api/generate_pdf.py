import os
from pathlib import Path

import markdown
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import FileResponse

from app.models.models import PDFRequest
from app.services.functions import download_png, markdown_to_pdf

router = APIRouter()


@router.post("/generate-pdf")
async def generate_pdf(request: PDFRequest):
    """
    Generate PDF from markdown content and save it to files/ directory.
    """
    pdf_path, chart_path = "", ""
    try:
        # Convert markdown to HTML
        markdown_parts = request.markdown.split("![Star History Chart]")
        html_content = markdown.markdown(markdown_parts[0], extensions=["tables"])

        # Generate PDF filename and full path in files dir
        pdf_filename = request.filename.replace(".md", ".pdf")
        pdf_path = os.path.join(
            f"{Path(__file__).resolve().parent.parent}/services/files", pdf_filename
        )

        # Download Chart
        png_filename = request.filename.replace(".md", ".png")
        chart_path = download_png(markdown_parts[1][1:-1], png_filename)

        # Generate PDF into pdf_path
        markdown_to_pdf(html_content, pdf_path, chart_path)

        # Return saved PDF file
        return FileResponse(
            pdf_path, media_type="application/pdf", filename=pdf_filename
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {str(e)}")
    finally:
        try:
            if os.path.exists(chart_path):
                os.remove(chart_path)
            # if os.path.exists(pdf_path):
            #     os.remove(pdf_path)
        except:
            pass
