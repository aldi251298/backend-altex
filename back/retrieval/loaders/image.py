"""
Image OCR extraction using tesseract/paddleocr.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Custom exception for extraction errors."""
    pass


async def extract_text_from_image(file_path: str) -> str:
    """
    Extract text from an image using OCR.
    
    Args:
        file_path: Path to image file
    
    Returns:
        Extracted text content
    """
    try:
        # Try tesseract first
        return await _extract_with_tesseract(file_path)
    except Exception:
        # Fallback to paddleocr
        return await _extract_with_paddleocr(file_path)


async def _extract_with_tesseract(file_path: str) -> str:
    """Extract text using pytesseract."""
    try:
        # Use try/except to handle missing import gracefully
        try:
            import pytesseract  # pyright: ignore[reportMissingImports]
            from PIL import Image
            
            image = Image.open(file_path)
            text = pytesseract.image_to_string(image, lang="eng+ind")
            return text.strip()
        except ImportError as e:
            raise ExtractionError(f"pytesseract not installed: {e}")
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(f"Tesseract error: {e}")


async def _extract_with_paddleocr(file_path: str) -> str:
    """Extract text using paddleocr."""
    try:
        # Use try/except to handle missing import gracefully
        try:
            from paddleocr import PaddleOCR  # pyright: ignore[reportMissingImports]
            
            ocr = PaddleOCR(use_angle_cls=True, lang="en")
            result = ocr.ocr(file_path, cls=True)
            
            texts = []
            for line in result[0]:
                if line and len(line) >= 2:
                    texts.append(line[1][0])
            
            return "\n".join(texts)
        except ImportError as e:
            raise ExtractionError(f"paddleocr not installed: {e}")
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(f"PaddleOCR error: {e}")
