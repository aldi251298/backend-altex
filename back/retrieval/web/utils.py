"""
Web search utilities: content extraction from URLs.
"""

import logging
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


async def extract_web_content(
    url: str,
    use_playwright: bool = False,
) -> str:
    """
    Extract readable content from a URL.
    
    Args:
        url: URL to extract content from
        use_playwright: If True, use Playwright for JS-heavy sites
    
    Returns:
        Extracted text content
    """
    if use_playwright:
        return await _extract_with_playwright(url)
    return await _extract_with_http(url)


async def _extract_with_http(url: str) -> str:
    """Extract content using aiohttp + BeautifulSoup."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    return ""
                
                html = await response.text(errors="replace")
                soup = BeautifulSoup(html, "html.parser")
                
                # Remove scripts and styles
                for script in soup(["script", "style", "nav", "footer", "header"]):
                    script.decompose()
                
                # Get text
                text = soup.get_text(separator="\n", strip=True)
                
                # Clean up whitespace
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                return "\n".join(lines)
    except Exception as e:
        logger.error(f"Content extraction error for {url}: {e}")
        return ""


async def _extract_with_playwright(url: str) -> str:
    """Extract content using Playwright for JS-heavy sites."""
    try:
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                text = await page.evaluate("""() => {
                    const el = document.body;
                    return el.innerText || el.textContent || '';
                }""")
                return text.strip()
            finally:
                await browser.close()
    except Exception as e:
        logger.error(f"Playwright extraction error for {url}: {e}")
        return ""
