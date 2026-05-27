"""
PDF text extraction using pypdf.
"""

import io
import logging
from typing import Any

from pypdf import PdfReader

logger = logging.getLogger(__name__)


async def extract_text_from_pdf(file_path: str | bytes) -> str:
    """
    Extract text from a PDF file.
    
    Args:
        file_path: Path to PDF file or bytes content
    
    Returns:
        Extracted text content
    """
    try:
        if isinstance(file_path, bytes):
            reader = PdfReader(io.BytesIO(file_path))
        else:
            reader = PdfReader(file_path)
        
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        
        return "\n\n".join(pages)
    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        raise ExtractionError(f"Failed to extract text from PDF: {e}")


class ExtractionError(Exception):
    """Error during text extraction."""
    pass
