"""
Error codes, constants, dan built-in tool specifications.
"""

import time
import uuid
from datetime import datetime, timedelta

# ============================================================================
# Error Codes
# ============================================================================

ERROR_CODES = {
    # Auth Errors (A001-A099)
    "INVALID_CREDENTIALS": {
        "code": "A001",
        "status": 401,
        "message": "Email atau password salah",
    },
    "INVALID_TOKEN": {
        "code": "A002",
        "status": 401,
        "message": "Token tidak valid",
    },
    "TOKEN_EXPIRED": {
        "code": "A003",
        "status": 401,
        "message": "Token telah kadaluarsa",
    },
    "ACCOUNT_DISABLED": {
        "code": "A004",
        "status": 403,
        "message": "Akun dinonaktifkan",
    },
    "USER_NOT_FOUND": {
        "code": "A005",
        "status": 404,
        "message": "User tidak ditemukan",
    },

    # Validation Errors (V001-V099)
    "FILE_TYPE_NOT_SUPPORTED": {
        "code": "V001",
        "status": 415,
        "message": "Tipe file tidak didukung",
    },
    "FILE_TOO_LARGE": {
        "code": "V002",
        "status": 413,
        "message": "File terlalu besar (max 50MB)",
    },
    "NO_TEXT_EXTRACTED": {
        "code": "V003",
        "status": 422,
        "message": "File tidak mengandung teks yang dapat diproses",
    },
    "INVALID_MESSAGE_FORMAT": {
        "code": "V004",
        "status": 422,
        "message": "Format pesan tidak valid",
    },

    # Provider Errors (P001-P099)
    "PROVIDER_CONNECTION_FAILED": {
        "code": "P001",
        "status": 503,
        "message": "Provider tidak dapat dihubungi",
    },
    "PROVIDER_RATE_LIMITED": {
        "code": "P002",
        "status": 429,
        "message": "Provider rate limit tercapai",
    },
    "PROVIDER_ERROR": {
        "code": "P003",
        "status": 503,
        "message": "Error dari provider AI",
    },

    # RAG Errors (R001-R099)
    "RAG_INDEXING_FAILED": {
        "code": "R001",
        "status": 500,
        "message": "Gagal mengindex dokumen",
    },
    "EMBEDDING_GENERATION_FAILED": {
        "code": "R002",
        "status": 500,
        "message": "Gagal generate embedding",
    },

    # System Errors (S001-S099)
    "INTERNAL_ERROR": {
        "code": "S001",
        "status": 500,
        "message": "Terjadi kesalahan internal",
    },
    "SERVICE_UNAVAILABLE": {
        "code": "S002",
        "status": 503,
        "message": "Layanan sedang tidak tersedia",
    },
}

# ============================================================================
# Constants
# ============================================================================

# File upload limits
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

ALLOWED_FILE_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/json",
    "text/csv",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}

ALLOWED_FILE_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".json", ".csv", ".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Streaming limits
SSE_TIMEOUT_SECONDS = 300  # 5 menit max
MAX_TOOL_CALL_ITERATIONS = 10
DEFAULT_MODEL_CACHE_TTL = 300  # 5 menit

# Token expiry
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 hari
REFRESH_TOKEN_EXPIRE_DAYS = 30

# Auth
DEFAULT_BCRYPT_COST_FACTOR = 12
LOGIN_FAIL_DELAY_SECONDS = 0.5

# Rate limiting
LOGIN_RATE_LIMIT = "5/minute"
CHAT_RATE_LIMIT = "60/minute"

# Chat defaults
DEFAULT_CHAT_TITLE = "Chat Baru"
DEFAULT_SYSTEM_PROMPT = ""
DEFAULT_TEMPERATURE = 1.0
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TOP_P = 1.0

# Title generation
DEFAULT_TITLE_PROMPT = """Berdasarkan percakapan di bawah, buat judul yang singkat (maksimal 6 kata), 
deskriptif, dan dalam bahasa yang sama dengan percakapan. 
Hanya kembalikan judulnya saja, tanpa penjelasan atau tanda kutip.

Percakapan:
{messages}

Judul:"""

DEFAULT_TITLE_MAX_CHARS = 100

# ============================================================================
# Utility Functions
# ============================================================================


def time_ns() -> int:
    """Return current Unix timestamp in seconds (stored as int in DB INTEGER)."""
    return int(time.time())


def time_ms() -> int:
    """Return current Unix timestamp in milliseconds."""
    return int(time.time() * 1000)


def generate_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


def mask_api_key(api_key: str, visible_chars: int = 4) -> str:
    """Mask API key for logging."""
    if not api_key or len(api_key) <= visible_chars:
        return "****"
    return api_key[:visible_chars] + "*" * (len(api_key) - visible_chars)
