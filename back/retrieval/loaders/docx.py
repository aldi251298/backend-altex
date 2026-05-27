"""
DOCX text extraction using python-docx.
"""

import logging
from typing import Any

from docx import Document

logger = logging.getLogger(__name__)


async def extract_text_from_docx(file_path: str) -> str:
    """
    Extract text from a DOCX file.
    
    Args:
        file_path: Path to DOCX file
    
    Returns:
        Extracted text content
    """
    try:
        doc = Document(file_path)
        paragraphs = [para.text for para in doc.paragraphs if para.text]
        return "\n\n".join(paragraphs)
    except Exception as e:
        logger.error(f"DOCX extraction error: {e}")
        raise ExtractionError(f"Failed to extract text from DOCX: {e}")


class ExtractionError(Exception):
    """Error during text extraction."""
    pass
