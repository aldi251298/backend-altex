"""
Plain text file extraction.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def extract_text_from_text(file_path: str) -> str:
    """
    Extract text from a plain text file.
    
    Args:
        file_path: Path to text file
    
    Returns:
        File content as string
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Text extraction error: {e}")
        raise ExtractionError(f"Failed to extract text: {e}")


class ExtractionError(Exception):
    """Error during text extraction."""
    pass
