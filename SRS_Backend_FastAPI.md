# Software Requirements Specification (SRS)
## Backend FastAPI — AI Chat Server

> **Versi Dokumen:** 1.1.0  
> **Tanggal:** 2025-06-01  
> **Referensi Arsitektur:** Open WebUI v0.9.2 (github.com/open-webui/open-webui)  
> **Stack:** Python 3.11+, FastAPI, PostgreSQL, pgvector, SQLAlchemy, Redis (opsional)  
> **Deployment Target:** AWS (EC2 / ECS / Lambda + RDS)  
> **Arsitektur Komunikasi:** Flutter Client → FastAPI Backend (AWS) → AI Provider (OpenAI-compatible / vLLM)

---

## Daftar Isi

1. [Gambaran Umum Backend](#1-gambaran-umum-backend)
2. [Arsitektur & Struktur Direktori](#2-arsitektur--struktur-direktori)
3. [Unified API Layer & Multi-Provider Support](#3-unified-api-layer--multi-provider-support)
4. [Request Preprocessing Pipeline](#4-request-preprocessing-pipeline)
5. [SSE Streaming — Implementasi Backend](#5-sse-streaming--implementasi-backend)
6. [Stop Generation — Disconnect Detection](#6-stop-generation--disconnect-detection)
7. [Tool Calling & Parallel Execution](#7-tool-calling--parallel-execution)
8. [RAG Pipeline — Upload, Chunking, Embedding, Retrieval](#8-rag-pipeline--upload-chunking-embedding-retrieval)
9. [Web Search Integration](#9-web-search-integration)
10. [Model Routing & Discovery](#10-model-routing--discovery)
11. [Chat History Persistence (PostgreSQL)](#11-chat-history-persistence-postgresql)
12. [Authentication & Authorization](#12-authentication--authorization)
13. [PersistentConfig System](#13-persistentconfig-system)
14. [Background Tasks](#14-background-tasks)
15. [API Endpoints Lengkap](#15-api-endpoints-lengkap)
16. [Database Schema](#16-database-schema)
17. [Konfigurasi & Environment Variables](#17-konfigurasi--environment-variables)
18. [Keamanan Backend](#18-keamanan-backend)
19. [Monitoring & Logging](#19-monitoring--logging)
20. [Pengujian Backend](#20-pengujian-backend)
21. [Deployment di AWS](#21-deployment-di-aws)

---

## 1. Gambaran Umum Backend

### 1.1 Tujuan

Backend FastAPI berfungsi sebagai **orkestrasi AI** — menerima request dari Flutter client, menjalankan seluruh pipeline (auth, RAG, web search, tool execution, streaming), dan mengirim respons SSE kembali ke client. Backend juga bertanggung jawab atas penyimpanan data server-side dan sinkronisasi antar device.

### 1.2 Tanggung Jawab Backend

```
Backend MENGERJAKAN:
✅ Auth — JWT token issuance, validation, refresh
✅ AI Proxy — forward request ke OpenAI/vLLM, stream SSE balik ke client
✅ RAG Pipeline — upload, extract teks, chunking, embedding, pgvector storage & retrieval
✅ Web Search — call search API, extract konten halaman, inject context
✅ Tool Execution — eksekusi tools Python (web fetch, code sandbox, dll)
✅ Chat History — simpan di PostgreSQL, sync antar device
✅ Model Aggregation — satu /models endpoint untuk semua provider yang dikonfigurasi
✅ Background Tasks — title & tag generation setelah streaming selesai
✅ User Management — accounts, sessions, RBAC
✅ File Storage — simpan file upload ke S3/lokal, kelola lifecycle
✅ PersistentConfig — konfigurasi runtime yang bisa diubah tanpa restart
✅ Rate Limiting — cegah abuse per user/IP

Backend TIDAK mengerjakan:
❌ UI/UX rendering — ini tugas Flutter
❌ Local caching di device — ini tugas Flutter (SQLite)
❌ Client-side event bus — ini tugas Flutter (AppEventBus)
```

### 1.3 Dependensi Utama (requirements.txt)

```txt
# Framework
fastapi==0.111.0
uvicorn[standard]==0.30.1
pydantic==2.7.2
pydantic-settings==2.3.0

# Database
sqlalchemy==2.0.30
asyncpg==0.29.0
alembic==1.13.1
pgvector==0.3.1

# HTTP client (async)
aiohttp==3.9.5
httpx==0.27.0

# Auth
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.9

# RAG & Embeddings
langchain-text-splitters==0.2.0
sentence-transformers==3.0.1
openai==1.35.0             # Client untuk OpenAI-compatible APIs

# Web Search & Scraping
beautifulsoup4==4.12.3
playwright==1.44.0         # Opsional: JS-heavy sites

# File Processing
python-docx==1.1.2
pypdf==4.2.0
pillow==10.3.0
python-magic==0.4.27

# Task Queue (opsional, untuk scale)
celery==5.4.0
redis==5.0.6

# Monitoring
prometheus-fastapi-instrumentator==7.0.0
structlog==24.2.0

# Testing
pytest==8.2.2
pytest-asyncio==0.23.7
httpx==0.27.0              # TestClient async
```

---

## 2. Arsitektur & Struktur Direktori

### 2.1 Struktur Proyek

```
backend/
├── main.py                         # FastAPI app, mount routers & middleware
├── env.py                          # Environment variables (Pydantic Settings)
├── config.py                       # PersistentConfig system (DB-backed)
├── constants.py                    # Error codes, constants
│
├── routers/
│   ├── auth.py                     # Login, logout, refresh, me
│   ├── chat.py                     # Chat completion (entry point utama)
│   ├── chats.py                    # CRUD chat history
│   ├── models.py                   # Model list & management
│   ├── providers.py                # Provider CRUD & connection test
│   ├── files.py                    # File upload, metadata, delete
│   ├── retrieval.py                # RAG search, web search endpoints
│   └── tasks.py                    # Background task endpoints
│
├── utils/
│   ├── chat.py                     # generate_chat_completion() — orchestrator
│   ├── middleware.py               # process_chat_payload() — pipeline besar
│   ├── payload.py                  # Payload transformation utilities
│   ├── filter.py                   # Filter pipeline processor
│   ├── tools.py                    # Tool discovery & execution
│   ├── task.py                     # Task utilities (title gen, tag gen)
│   ├── models.py                   # Model aggregation logic
│   ├── auth.py                     # JWT, token validation
│   └── streaming.py                # SSE streaming helpers
│
├── models/                         # SQLAlchemy ORM models
│   ├── chats.py
│   ├── users.py
│   ├── files.py
│   ├── providers.py
│   └── config.py
│
├── retrieval/
│   ├── vector/
│   │   ├── pgvector.py             # pgvector adapter (PRIMARY)
│   │   └── base.py                 # Abstract base class
│   ├── web/
│   │   ├── searxng.py
│   │   ├── brave.py
│   │   ├── tavily.py
│   │   ├── duckduckgo.py
│   │   └── utils.py               # Content extraction
│   ├── loaders/
│   │   ├── pdf.py
│   │   ├── docx.py
│   │   ├── text.py
│   │   └── image.py               # OCR via tesseract/paddleocr
│   └── utils.py                   # Chunking, embedding utilities
│
├── migrations/                     # Alembic migrations
│   └── versions/
│
└── tests/
    ├── test_sse_streaming.py
    ├── test_rag_pipeline.py
    ├── test_auth.py
    └── test_chat_completion.py
```

### 2.2 Alur Request End-to-End

```
Flutter Client
     │
     │  POST /api/chat/completions
     │  Header: Authorization: Bearer <jwt>
     │  Body: { model, messages, files?, stream: true }
     ▼
FastAPI Router (routers/chat.py)
     │
     │  Validate JWT → extract user
     │  Delegate ke generate_chat_completion()
     ▼
utils/chat.py: generate_chat_completion()    ← Orchestrator utama
     │
     ├─ [1] Validasi user & akses model
     ├─ [2] Apply model params (temperature, system prompt)
     ├─ [3] Process filter functions (inlet)
     ├─ [4] process_chat_payload()            ← Pre-processing pipeline
     │       ├─ RAG: retrieve & inject (jika ada files)
     │       ├─ Web search: search & inject (jika aktif)
     │       ├─ Memory injection (jika aktif)
     │       └─ Tool specs injection
     ├─ [5] Tool calling loop                 ← Loop hingga finish_reason="stop"
     └─ [6] StreamingResponse → SSE ke Flutter
```

---

## 3. Unified API Layer & Multi-Provider Support

### 3.1 Konsep: Satu Format untuk Semua Provider

Backend mengadopsi **OpenAI Chat Completion API** sebagai format standar untuk semua provider. Ini keputusan arsitektur paling fundamental — Flutter selalu berbicara satu bahasa, backend yang mengurus translasi.

```python
# routers/chat.py

@router.post("/api/chat/completions")
async def generate_chat_completions(
    request: Request,
    form_data: dict,
    user: UserModel = Depends(get_verified_user),
):
    """
    Entry point utama. Semua request chat harus melalui endpoint ini
    karena melewati seluruh pipeline (RAG, tools, filters, dll).
    
    JANGAN gunakan /openai/v1/chat/completions secara langsung dari Flutter
    karena bypass middleware.
    """
    return await generate_chat_completion(request, form_data, user)
```

### 3.2 Multi-Provider Auth Support

```python
# utils/chat.py — Provider authentication

async def get_provider_headers(connection: dict, request: Request) -> dict:
    """
    Mendukung 5 metode autentikasi provider.
    Priority: explicit auth_type > default bearer
    """
    headers = {"Content-Type": "application/json"}
    api_key = connection.get("api_key", "")
    auth_type = connection.get("auth_type", "bearer")

    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"

    elif auth_type == "azure_ad":
        # Azure OpenAI dengan Microsoft Entra ID
        from azure.identity.aio import DefaultAzureCredential
        credential = DefaultAzureCredential()
        token = await credential.get_token(
            "https://cognitiveservices.azure.com/.default"
        )
        headers["Authorization"] = f"Bearer {token.token}"

    elif auth_type == "system_oauth":
        # OAuth token dari internal OAuth manager
        token = await get_oauth_token(connection)
        headers["Authorization"] = f"Bearer {token}"

    elif auth_type == "session":
        # Forward cookie session user (untuk provider internal)
        headers["Cookie"] = request.headers.get("cookie", "")

    elif auth_type == "none":
        # Tanpa auth (server lokal, vLLM tanpa auth)
        pass

    # Header custom tambahan dari konfigurasi
    for key, value in connection.get("extra_headers", {}).items():
        headers[key] = value

    return headers
```

### 3.3 Payload Transformation

```python
# utils/payload.py

def apply_system_prompt_to_body(params: dict, body: dict) -> dict:
    """
    Inject system prompt dengan priority:
    chat-level override > model-default > global-default
    """
    system = params.get("system")
    if system:
        # Cek apakah sudah ada system message
        existing_system = next(
            (m for m in body.get("messages", []) if m["role"] == "system"),
            None,
        )
        if existing_system:
            # Override system yang ada
            existing_system["content"] = system
        else:
            # Insert di awal
            body["messages"] = [
                {"role": "system", "content": system}
            ] + body.get("messages", [])
    return body


def apply_model_params_to_body(params: dict, body: dict) -> dict:
    """
    Apply parameter model: hanya inject yang ada nilainya (skip None).
    Ini mencegah override default provider yang mungkin lebih baik.
    """
    param_map = {
        "temperature": "temperature",
        "max_tokens": "max_tokens",
        "top_p": "top_p",
        "frequency_penalty": "frequency_penalty",
        "presence_penalty": "presence_penalty",
        "stop": "stop",
        "seed": "seed",
        "top_k": "top_k",          # Beberapa provider (Anthropic, Ollama)
    }
    for src, dst in param_map.items():
        value = params.get(src)
        if value is not None:
            body[dst] = value

    return body


def strip_unsupported_params(body: dict, model_capabilities: dict) -> dict:
    """
    Hapus parameter yang tidak didukung model tertentu.
    Contoh: 'tools' untuk model yang tidak support function calling.
    """
    if not model_capabilities.get("tools", False):
        body.pop("tools", None)
        body.pop("tool_choice", None)

    if not model_capabilities.get("vision", False):
        # Konversi multimodal messages ke teks saja
        for msg in body.get("messages", []):
            if isinstance(msg.get("content"), list):
                text_parts = [
                    p["text"]
                    for p in msg["content"]
                    if p.get("type") == "text"
                ]
                msg["content"] = " ".join(text_parts)

    return body
```

---

## 4. Request Preprocessing Pipeline

### 4.1 Gambaran Pipeline

```python
# utils/middleware.py

async def process_chat_payload(
    body: dict,
    user: UserModel,
    model: dict,
    extra_params: dict,
    event_emitter: Callable,
) -> dict:
    """
    Pipeline preprocessing sebelum request dikirim ke AI provider.
    Urutan eksekusi ini PENTING — jangan ubah urutan.
    """

    # [1] Apply system prompt & model params
    body = apply_system_prompt_to_body(model.get("params", {}), body)
    body = apply_model_params_to_body(model.get("params", {}), body)

    # [2] Filter functions (INLET)
    # Filter yang dikonfigurasi admin bisa modifikasi body sebelum ke AI
    filters = await get_active_filters_for_model(model["id"])
    body = await process_filter_functions(
        filters=filters,
        body=body,
        user=user,
        event_emitter=event_emitter,
        phase="inlet",
    )

    # [3] RAG: jika ada file_ids dalam request
    if body.get("files"):
        body = await chat_completion_files_handler(
            body=body,
            user=user,
            event_emitter=event_emitter,
        )

    # [4] Web search: jika fitur aktif dan mode otomatis
    web_search_mode = body.pop("web_search", False)  # hapus dari body sebelum kirim ke AI
    if web_search_mode or settings.ENABLE_WEB_SEARCH_AUTO:
        body = await chat_completion_web_search_handler(
            body=body,
            user=user,
            event_emitter=event_emitter,
        )

    # [5] Memory injection: jika user punya memories aktif
    if settings.ENABLE_MEMORY and user.settings.get("memory_enabled", False):
        body = await chat_completion_memory_handler(body=body, user=user)

    # [6] Inject tool specs
    body = await prepare_tools_for_request(
        body=body,
        model=model,
        user=user,
    )

    # [7] Strip parameter yang tidak didukung model
    capabilities = model.get("capabilities", {})
    body = strip_unsupported_params(body, capabilities)

    return body
```

### 4.2 Filter System (Inlet & Outlet)

```python
# utils/filter.py

async def process_filter_functions(
    filters: list,
    body: dict,
    user: UserModel,
    event_emitter: Callable,
    phase: str,  # "inlet" atau "outlet"
) -> dict:
    """
    Jalankan filter secara berurutan berdasarkan priority (ascending).
    Filter bisa:
    - Modifikasi messages (inject context, translate, dll)
    - Tambah/hapus tools
    - Ubah model yang dituju
    - Emit status events ke Flutter
    """
    sorted_filters = sorted(filters, key=lambda f: f.get("priority", 0))

    for filter_func in sorted_filters:
        try:
            if phase == "inlet":
                result = await filter_func["inlet"](
                    body=body, user=user, event_emitter=event_emitter
                )
            elif phase == "outlet":
                result = await filter_func["outlet"](
                    body=body, response=body, user=user
                )
            else:
                continue

            if result is not None:
                body = result

        except Exception as e:
            log.error(f"Filter '{filter_func.get('name')}' error: {e}")
            # JANGAN hentikan pipeline karena satu filter gagal
            continue

    return body
```

---

## 5. SSE Streaming — Implementasi Backend

### 5.1 StreamingResponse Setup

```python
# utils/chat.py

async def generate_chat_completion(
    request: Request,
    form_data: dict,
    user: UserModel,
    background_tasks: BackgroundTasks,
) -> StreamingResponse:

    # ... validasi & pre-processing ...

    preprocessed_body = await process_chat_payload(
        body=form_data,
        user=user,
        model=model,
        extra_params={},
        event_emitter=event_emitter,
    )

    return StreamingResponse(
        content=_stream_generator(
            request=request,
            body=preprocessed_body,
            provider_url=provider_url,
            provider_headers=provider_headers,
            user=user,
            chat_id=chat_id,
            message_id=message_id,
            background_tasks=background_tasks,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",    # KRITIS: disable Nginx buffering
            "Access-Control-Allow-Origin": "*",
        },
    )
```

### 5.2 Stream Generator

```python
async def _stream_generator(
    request: Request,
    body: dict,
    provider_url: str,
    provider_headers: dict,
    user: UserModel,
    chat_id: str,
    message_id: str,
    background_tasks: BackgroundTasks,
) -> AsyncGenerator[str, None]:
    """
    Generator async yang membaca stream dari AI provider
    dan meneruskannya ke Flutter client via SSE.
    """
    accumulated_content = ""
    accumulated_tool_calls = {}
    usage_data = None
    finish_reason = None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url=f"{provider_url}/chat/completions",
                headers=provider_headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=300),  # 5 menit max
            ) as response:

                if response.status != 200:
                    error_text = await response.text()
                    yield _format_sse_error(response.status, error_text)
                    return

                async for raw_line in response.content:
                    # Cek apakah Flutter sudah disconnect (klik Stop)
                    if await request.is_disconnected():
                        log.info(f"Client disconnected, stopping stream for {message_id}")
                        break

                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data: "):
                        continue

                    data = line[6:]  # Hapus "data: " prefix

                    if data == "[DONE]":
                        yield "data: [DONE]\n\n"
                        break

                    try:
                        chunk = json.loads(data)
                        choice = chunk.get("choices", [{}])[0]
                        delta = choice.get("delta", {})

                        # Akumulasi content untuk disimpan ke DB
                        if delta.get("content"):
                            accumulated_content += delta["content"]

                        # Akumulasi tool calls
                        if delta.get("tool_calls"):
                            for tc in delta["tool_calls"]:
                                idx = str(tc.get("index", 0))
                                if idx not in accumulated_tool_calls:
                                    accumulated_tool_calls[idx] = tc
                                else:
                                    # Merge parsial tool call
                                    existing = accumulated_tool_calls[idx]
                                    if tc.get("function", {}).get("arguments"):
                                        existing["function"]["arguments"] = (
                                            existing["function"].get("arguments", "") +
                                            tc["function"]["arguments"]
                                        )

                        # Track usage
                        if chunk.get("usage"):
                            usage_data = chunk["usage"]

                        finish_reason = choice.get("finish_reason")

                        # Forward chunk ke Flutter
                        yield f"data: {json.dumps(chunk)}\n\n"

                    except json.JSONDecodeError:
                        # Skip chunk malformed — JANGAN hentikan stream
                        log.warning(f"Malformed SSE chunk (skipped): {data[:100]}")
                        continue

    except aiohttp.ClientError as e:
        log.error(f"Provider connection error: {e}")
        yield _format_sse_error(503, str(e))

    finally:
        # Simpan ke DB — baik selesai normal maupun terpotong
        await _save_completion_to_db(
            chat_id=chat_id,
            message_id=message_id,
            content=accumulated_content,
            tool_calls=list(accumulated_tool_calls.values()),
            usage=usage_data,
            done=(finish_reason == "stop"),
            stopped=(finish_reason is None and accumulated_content),
        )

        # Trigger background tasks jika normal selesai
        if finish_reason == "stop":
            background_tasks.add_task(
                _run_post_completion_tasks,
                chat_id=chat_id,
                messages=body["messages"] + [{"role": "assistant", "content": accumulated_content}],
                model_id=body["model"],
                user=user,
            )


def _format_sse_error(status_code: int, message: str) -> str:
    """Format error sebagai SSE event — Flutter bisa handle secara konsisten."""
    error = {
        "error": {
            "code": status_code,
            "message": message,
            "type": "provider_error",
        }
    }
    return f"data: {json.dumps(error)}\n\n"
```

### 5.3 Status Event Emission

```python
# utils/streaming.py

async def create_event_emitter(chat_id: str, message_id: str) -> Callable:
    """
    Buat emitter yang mengirim status events via SSE.
    Events ini muncul di Flutter sebagai status banner (progress indicator).
    """
    # Dalam implementasi sederhana: simpan ke queue yang dibaca stream generator
    # Dalam implementasi production: gunakan in-memory queue per request

    event_queue: asyncio.Queue = asyncio.Queue()

    async def emit(event_data: dict) -> None:
        sse_event = {
            "type": event_data.get("type", "status"),
            "data": event_data.get("data", event_data),
        }
        await event_queue.put(f"data: {json.dumps(sse_event)}\n\n")

    return emit, event_queue


# Format status events yang dikirim ke Flutter:
# Web search sedang berjalan:
STATUS_SEARCHING = {
    "type": "status",
    "data": {
        "description": "Mencari di web...",
        "action": "web_search",
        "done": False,
    }
}

# RAG retrieval sedang berjalan:
STATUS_RETRIEVING = {
    "type": "status",
    "data": {
        "description": "Mengambil konteks dari dokumen...",
        "action": "knowledge_retrieval",
        "done": False,
    }
}

# Citation result:
CITATION_EVENT = {
    "type": "citation",
    "data": {
        "document": ["...chunk teks yang digunakan..."],
        "metadata": [{"source": "dokumen.pdf", "name": "dokumen.pdf"}],
        "source": {"name": "dokumen.pdf"},
    }
}
```

---

## 6. Stop Generation — Disconnect Detection

### 6.1 Mekanisme Utama

```python
# Di dalam _stream_generator() (lihat Section 5.2)

async for raw_line in response.content:
    # request.is_disconnected() akan return True ketika Flutter
    # menutup koneksi HTTP (cancel CancelToken Dio)
    if await request.is_disconnected():
        log.info(f"Flutter disconnected — stopping generation for {message_id}")
        # Keluar dari loop → context manager aiohttp menutup koneksi ke provider
        # AI provider berhenti generate karena koneksi terputus
        break
```

### 6.2 Partial Content Save

```python
# utils/chat.py — dalam blok finally

async def _save_completion_to_db(
    chat_id: str,
    message_id: str,
    content: str,
    tool_calls: list,
    usage: dict | None,
    done: bool,
    stopped: bool,
) -> None:
    """
    Simpan hasil ke DB bahkan jika streaming terpotong.
    Flutter akan menampilkan konten parsial dengan indikator "⏹ Dihentikan".
    """
    if not content and not tool_calls:
        return  # Tidak ada yang perlu disimpan

    message_data = {
        "id": message_id,
        "role": "assistant",
        "content": content,
        "tool_calls": tool_calls if tool_calls else None,
        "done": done,
        "stopped": stopped,
        "timestamp": int(time.time() * 1000),
    }

    if usage:
        message_data["usage"] = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    await Chats.upsert_message_to_chat(
        chat_id=chat_id,
        message_id=message_id,
        message_data=message_data,
    )
```

---

## 7. Tool Calling & Parallel Execution

### 7.1 Tool Discovery

```python
# utils/tools.py

async def prepare_tools_for_request(
    body: dict,
    model: dict,
    user: UserModel,
) -> dict:
    """
    Siapkan daftar tool specs berdasarkan:
    1. Built-in tools (berdasarkan fitur yang aktif)
    2. User-defined tools (dari DB)
    3. Filter berdasarkan model capabilities
    """
    if not model.get("capabilities", {}).get("tools", False):
        return body  # Model tidak support tools

    tools = []

    # Built-in tools
    if settings.ENABLE_WEB_SEARCH:
        tools.append(BUILTIN_TOOL_SPECS["search_web"])
        tools.append(BUILTIN_TOOL_SPECS["fetch_url"])

    if settings.ENABLE_CODE_INTERPRETER:
        tools.append(BUILTIN_TOOL_SPECS["execute_code"])

    if settings.ENABLE_IMAGE_GENERATION:
        tools.append(BUILTIN_TOOL_SPECS["generate_image"])

    # Selalu tersedia
    tools.extend([
        BUILTIN_TOOL_SPECS["get_current_timestamp"],
        BUILTIN_TOOL_SPECS["calculate_timestamp"],
    ])

    # User-defined tools dari DB
    user_tools = await Tools.get_tools_by_user_id(user.id)
    for ut in user_tools:
        if ut.active:
            tools.append(ut.to_openai_tool_spec())

    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    return body
```

### 7.2 Tool Calling Loop

```python
# utils/middleware.py

MAX_TOOL_CALL_ITERATIONS = int(os.getenv("CHAT_RESPONSE_MAX_TOOL_CALL_RETRIES", "10"))

async def execute_tool_calling_loop(
    request: Request,
    body: dict,
    provider_url: str,
    provider_headers: dict,
    event_emitter: Callable,
) -> AsyncGenerator[str, None]:
    """
    Loop utama tool calling.
    Terus iterasi hingga AI mengembalikan finish_reason="stop"
    atau mencapai batas maksimum iterasi.
    """
    iteration = 0
    total_tool_calls = 0

    while iteration < MAX_TOOL_CALL_ITERATIONS:
        accumulated_content = ""
        accumulated_tool_calls = {}
        finish_reason = None

        # Kirim ke AI provider
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url=f"{provider_url}/chat/completions",
                headers=provider_headers,
                json=body,
            ) as response:
                async for line in response.content:
                    if await request.is_disconnected():
                        return

                    line = line.decode("utf-8").strip()
                    if not line.startswith("data: "):
                        continue

                    data = line[6:]
                    if data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data)
                        choice = chunk.get("choices", [{}])[0]
                        delta = choice.get("delta", {})

                        if delta.get("content"):
                            accumulated_content += delta["content"]
                            yield f"data: {json.dumps(chunk)}\n\n"

                        if delta.get("tool_calls"):
                            for tc in delta["tool_calls"]:
                                idx = str(tc.get("index", 0))
                                accumulated_tool_calls.setdefault(idx, {}).update(tc)

                        finish_reason = choice.get("finish_reason")

                    except json.JSONDecodeError:
                        continue

        # Jika tidak ada tool calls → selesai
        if finish_reason != "tool_calls" or not accumulated_tool_calls:
            break

        # Execute semua tool calls (PARALLEL via asyncio.gather)
        tool_calls_list = list(accumulated_tool_calls.values())
        total_tool_calls += len(tool_calls_list)

        if total_tool_calls > MAX_TOOL_CALL_ITERATIONS:
            error_chunk = {
                "error": {"message": "Batas maksimum tool call tercapai"}
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
            break

        # Emit status ke Flutter
        await event_emitter({
            "type": "status",
            "data": {
                "description": f"Menjalankan {len(tool_calls_list)} tool(s)...",
                "done": False,
            }
        })

        # Parallel execution
        tool_results = await asyncio.gather(*[
            _execute_single_tool(tc, event_emitter)
            for tc in tool_calls_list
        ])

        await event_emitter({
            "type": "status",
            "data": {"description": "Tools selesai", "done": True}
        })

        # Update message history untuk iterasi berikutnya
        body["messages"].append({
            "role": "assistant",
            "content": accumulated_content or None,
            "tool_calls": tool_calls_list,
        })

        for result in tool_results:
            body["messages"].append({
                "role": "tool",
                "tool_call_id": result["tool_call_id"],
                "content": json.dumps(result["output"]),
            })

        iteration += 1
```

### 7.3 Single Tool Execution

```python
async def _execute_single_tool(
    tool_call: dict,
    event_emitter: Callable,
) -> dict:
    """
    Execute satu tool. Error dikembalikan sebagai string, bukan exception,
    sehingga AI bisa menangani tool failure secara graceful.
    """
    tool_name = tool_call.get("function", {}).get("name", "")
    raw_args = tool_call.get("function", {}).get("arguments", "{}")
    tool_call_id = tool_call.get("id", "")

    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError:
        return {
            "tool_call_id": tool_call_id,
            "output": f"Error: invalid JSON arguments: {raw_args}",
        }

    try:
        if tool_name == "search_web":
            result = await _tool_search_web(args.get("query", ""))
        elif tool_name == "fetch_url":
            result = await _tool_fetch_url(args.get("url", ""))
        elif tool_name == "execute_code":
            result = await _tool_execute_code(args.get("code", ""), args.get("language", "python"))
        elif tool_name == "get_current_timestamp":
            result = {"timestamp": datetime.utcnow().isoformat(), "timezone": "UTC"}
        else:
            result = {"error": f"Tool '{tool_name}' tidak tersedia di server"}

        return {"tool_call_id": tool_call_id, "output": result}

    except Exception as e:
        log.error(f"Tool '{tool_name}' execution error: {e}")
        return {
            "tool_call_id": tool_call_id,
            "output": {"error": f"Tool execution failed: {str(e)}"},
        }
```

---

## 8. RAG Pipeline — Upload, Chunking, Embedding, Retrieval

### 8.1 Upload & Indexing Pipeline

```python
# routers/files.py

@router.post("/api/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    user: UserModel = Depends(get_verified_user),
) -> FileResponse:
    """
    Pipeline upload file:
    1. Simpan ke storage (lokal atau S3)
    2. Extract teks
    3. Chunk
    4. Generate embeddings
    5. Simpan ke pgvector
    6. Return file_id ke Flutter
    """
    # Validasi tipe file
    allowed_types = {
        "application/pdf", "text/plain", "text/markdown",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/json", "text/csv",
    }
    if file.content_type not in allowed_types:
        raise HTTPException(415, f"Tipe file tidak didukung: {file.content_type}")

    # Validasi ukuran (max 50MB)
    MAX_FILE_SIZE = 50 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "File terlalu besar (max 50MB)")

    # Simpan ke storage
    file_id = str(uuid4())
    file_path = await storage.save(file_id, content, file.filename)

    # Extract teks
    try:
        text = await extract_text(file_path, file.content_type)
    except ExtractionError as e:
        await storage.delete(file_path)
        raise HTTPException(422, f"Gagal extract teks: {e}")

    if not text or len(text.strip()) < 10:
        raise HTTPException(422, "File tidak mengandung teks yang dapat diproses")

    # Chunking
    chunks = chunk_text(
        text=text,
        chunk_size=settings.CHUNK_SIZE.value,
        chunk_overlap=settings.CHUNK_OVERLAP.value,
    )

    # Generate embeddings (batch untuk efisiensi)
    collection_name = f"col_{file_id.replace('-', '')}"
    embeddings = await generate_embeddings_batch(
        texts=[c["text"] for c in chunks],
        model=settings.RAG_EMBEDDING_MODEL.value,
    )

    # Simpan ke pgvector
    await pgvector_client.upsert_collection(
        collection_name=collection_name,
        documents=[
            {
                "id": f"{file_id}_chunk_{i}",
                "text": chunk["text"],
                "embedding": embedding,
                "metadata": {
                    "file_id": file_id,
                    "chunk_index": i,
                    "source": file.filename,
                    "page": chunk.get("page"),
                },
            }
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
        ],
    )

    # Simpan metadata ke PostgreSQL
    db_file = await Files.create_file(
        id=file_id,
        user_id=user.id,
        filename=file.filename,
        content_type=file.content_type,
        file_path=file_path,
        collection_name=collection_name,
        chunk_count=len(chunks),
        size_bytes=len(content),
    )

    return FileResponse(
        id=file_id,
        filename=file.filename,
        collection_name=collection_name,
        size=len(content),
        created_at=db_file.created_at,
    )
```

### 8.2 Text Chunking

```python
# retrieval/utils.py

def chunk_text(
    text: str,
    chunk_size: int = 1500,
    chunk_overlap: int = 100,
) -> list[dict]:
    """
    RecursiveCharacterTextSplitter:
    Split rekursif berdasarkan hierarchy separator.
    Sweet spot: chunk_size=1000-1500, chunk_overlap=100-200.
    """
    SEPARATORS = ["\n\n", "\n", ". ", " ", ""]
    chunks = []

    def _split(text: str, separators: list[str]) -> list[str]:
        if not separators:
            # Fallback: hard split berdasarkan karakter
            return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size - chunk_overlap)]

        separator = separators[0]
        splits = text.split(separator)
        good_splits = []

        for split in splits:
            if len(split) <= chunk_size:
                good_splits.append(split)
            else:
                # Rekursif untuk bagian yang masih terlalu panjang
                good_splits.extend(_split(split, separators[1:]))

        # Merge split kecil dengan overlap
        return _merge_splits(good_splits, separator, chunk_size, chunk_overlap)

    raw_chunks = _split(text, SEPARATORS)
    return [{"text": c, "index": i} for i, c in enumerate(raw_chunks) if c.strip()]
```

### 8.3 Embedding Generation

```python
# retrieval/utils.py

async def generate_embeddings_batch(
    texts: list[str],
    model: str,
    batch_size: int = 100,
) -> list[list[float]]:
    """
    Generate embeddings secara batch untuk efisiensi.
    Mendukung OpenAI, Ollama, dan SentenceTransformers lokal.
    """
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]

        if settings.EMBEDDING_ENGINE == "openai":
            response = await openai_async_client.embeddings.create(
                model=model,  # misal: "text-embedding-3-small"
                input=batch,
            )
            batch_embeddings = [e.embedding for e in response.data]

        elif settings.EMBEDDING_ENGINE == "ollama":
            # Ollama tidak support batch — process satu per satu (paralel)
            batch_embeddings = await asyncio.gather(*[
                _embed_single_ollama(text, model) for text in batch
            ])

        elif settings.EMBEDDING_ENGINE == "local":
            # SentenceTransformers — berjalan di server, tidak butuh API
            import torch
            from sentence_transformers import SentenceTransformer
            st_model = SentenceTransformer(model)
            with torch.no_grad():
                batch_embeddings = st_model.encode(batch).tolist()

        else:
            raise ValueError(f"Unknown embedding engine: {settings.EMBEDDING_ENGINE}")

        all_embeddings.extend(batch_embeddings)

    return all_embeddings
```

### 8.4 RAG Retrieval di Pipeline Chat

```python
# utils/middleware.py

async def chat_completion_files_handler(
    body: dict,
    user: UserModel,
    event_emitter: Callable,
) -> dict:
    """
    Handler RAG: retrieve chunks relevan dan inject ke messages.
    """
    file_ids = [f["id"] for f in body.get("files", []) if f.get("type") == "file"]
    if not file_ids:
        return body

    # Emit status ke Flutter
    await event_emitter({
        "type": "status",
        "data": {"description": "Mengambil konteks dari dokumen...", "done": False}
    })

    # Dapatkan koleksi dari file_ids
    collections = await Files.get_collection_names_by_ids(file_ids)

    # [Opsional] Generate retrieval query yang lebih baik via LLM
    user_query = _extract_last_user_message(body["messages"])
    if settings.ENABLE_RAG_QUERY_GENERATION:
        optimized_queries = await generate_retrieval_queries(
            messages=body["messages"],
            task_model=settings.TASK_MODEL.value or body["model"],
        )
    else:
        optimized_queries = [user_query]

    # Similarity search di pgvector
    all_chunks = []
    for collection in collections:
        for query in optimized_queries:
            query_embedding = await generate_embeddings_batch([query], settings.RAG_EMBEDDING_MODEL.value)
            chunks = await pgvector_client.similarity_search(
                collection_name=collection,
                query_embedding=query_embedding[0],
                top_k=settings.RAG_TOP_K.value,
                score_threshold=settings.RAG_RELEVANCE_THRESHOLD.value,
            )
            all_chunks.extend(chunks)

    # [Opsional] Reranking via cross-encoder
    if settings.ENABLE_RAG_RERANKING and len(all_chunks) > settings.RAG_TOP_K.value:
        all_chunks = await rerank_chunks(user_query, all_chunks)

    # Deduplikasi berdasarkan content hash
    seen = set()
    unique_chunks = []
    for chunk in all_chunks:
        h = hash(chunk["text"])
        if h not in seen:
            seen.add(h)
            unique_chunks.append(chunk)

    # Inject sebagai context ke messages
    if unique_chunks:
        context_str = _format_rag_context(unique_chunks)
        body = _inject_context_to_messages(body, context_str)

        # Emit citation events ke Flutter
        for chunk in unique_chunks:
            await event_emitter({
                "type": "citation",
                "data": {
                    "document": [chunk["text"]],
                    "metadata": [chunk["metadata"]],
                    "source": {"name": chunk["metadata"].get("source", "Unknown")},
                }
            })

    await event_emitter({
        "type": "status",
        "data": {
            "description": f"Ditemukan {len(unique_chunks)} konteks relevan",
            "done": True,
        }
    })

    # Hapus 'files' dari body sebelum dikirim ke AI provider
    body.pop("files", None)
    return body


def _format_rag_context(chunks: list[dict]) -> str:
    """
    Format chunks sebagai context yang diinjeksikan ke prompt.
    Format XML membantu model memahami batasan konteks.
    """
    parts = ["[Informasi Konteks yang Relevan]"]
    for i, chunk in enumerate(chunks, 1):
        parts.append(
            f"<source>\n"
            f"  <source_id>{i}</source_id>\n"
            f"  <content>{chunk['text']}</content>\n"
            f"  <metadata>Sumber: {chunk['metadata'].get('source', 'unknown')}</metadata>\n"
            f"</source>"
        )
    parts.append("[Akhir Konteks]")
    return "\n".join(parts)
```

---

## 9. Web Search Integration

### 9.1 Full Web Search Pipeline

```python
# utils/middleware.py

async def chat_completion_web_search_handler(
    body: dict,
    user: UserModel,
    event_emitter: Callable,
) -> dict:
    """
    Pipeline web search end-to-end:
    1. Generate optimized queries via LLM
    2. Execute search (parallel)
    3. Extract full page content (opsional)
    4. Format & inject sebagai context
    5. Emit citation events
    """

    await event_emitter({
        "type": "status",
        "data": {"description": "Membuat query pencarian...", "done": False}
    })

    # [1] Generate query yang lebih baik dari input user
    queries = await generate_web_search_queries(
        messages=body["messages"],
        task_model=settings.TASK_MODEL.value or body["model"],
    )

    await event_emitter({
        "type": "status",
        "data": {
            "description": f"Mencari: {queries[0]}",
            "done": False,
        }
    })

    # [2] Execute search untuk semua queries (parallel)
    search_tasks = [
        search_web(
            engine=settings.WEB_SEARCH_ENGINE.value,
            query=q,
            count=settings.SEARCH_RESULT_COUNT.value,
        )
        for q in queries
    ]
    all_results = await asyncio.gather(*search_tasks, return_exceptions=True)

    # Filter hasil error
    valid_results = [
        r for r in all_results
        if not isinstance(r, Exception) and r
    ]

    if not valid_results:
        await event_emitter({
            "type": "status",
            "data": {"description": "Pencarian tidak menghasilkan hasil", "done": True}
        })
        return body

    # [3] Extract konten penuh dari URL (opsional, bergantung config)
    all_content = []
    if settings.ENABLE_WEB_CONTENT_EXTRACTION:
        await event_emitter({
            "type": "status",
            "data": {"description": "Membaca halaman web...", "done": False}
        })

        urls_to_fetch = [
            r["url"]
            for results in valid_results
            for r in results[:3]  # Top 3 per query
        ]

        fetch_tasks = [extract_web_content(url) for url in urls_to_fetch]
        contents = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for url, content in zip(urls_to_fetch, contents):
            if not isinstance(content, Exception):
                all_content.append({"url": url, "content": content})

    # [4] Format context
    context_str = _format_search_context(valid_results, all_content)
    body = _inject_context_to_messages(body, context_str)

    # [5] Emit citations
    for results in valid_results:
        for result in results:
            await event_emitter({
                "type": "citation",
                "data": {
                    "document": [result.get("snippet", "")],
                    "metadata": [{"source": result["url"], "name": result.get("title", result["url"])}],
                    "source": {"name": result.get("title", result["url"]), "url": result["url"]},
                }
            })

    await event_emitter({
        "type": "status",
        "data": {
            "description": f"Pencarian selesai ({sum(len(r) for r in valid_results)} hasil)",
            "done": True,
        }
    })

    return body
```

### 9.2 Search Provider Abstraction

```python
# retrieval/web/

SEARCH_PROVIDERS = {
    "searxng":      search_searxng,
    "brave":        search_brave,
    "tavily":       search_tavily,
    "duckduckgo":   search_duckduckgo,
    "bing":         search_bing,
    "serper":       search_serper,
    "google_pse":   search_google_pse,
    "kagi":         search_kagi,
    "perplexity":   search_perplexity,
}

async def search_web(engine: str, query: str, count: int = 5) -> list[dict]:
    """
    Abstraksi untuk semua search provider.
    Semua provider mengembalikan format yang sama:
    [{"title": str, "url": str, "snippet": str}]
    """
    provider_func = SEARCH_PROVIDERS.get(engine)
    if not provider_func:
        raise ValueError(f"Search engine tidak dikenal: {engine}")

    api_key = settings.get_search_api_key(engine)
    results = await provider_func(
        api_key=api_key,
        query=query,
        count=count,
    )

    # Normalize format
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url") or r.get("link", ""),
            "snippet": r.get("snippet") or r.get("description", ""),
        }
        for r in results
        if r.get("url") or r.get("link")
    ]
```

---

## 10. Model Routing & Discovery

### 10.1 Model Aggregation

```python
# utils/models.py

MODEL_CACHE: dict[str, list] = {}
MODEL_CACHE_TIMESTAMPS: dict[str, float] = {}
MODEL_CACHE_TTL = 300  # 5 menit

async def get_all_models(user: UserModel) -> list[dict]:
    """
    Fetch dan agregasi model dari semua provider yang dikonfigurasi.
    Menggunakan cache TTL 5 menit untuk mencegah hammering provider APIs.
    """
    now = time.time()
    cache_key = f"user_{user.role}"  # Cache per role (admin vs user)

    if (
        cache_key in MODEL_CACHE
        and now - MODEL_CACHE_TIMESTAMPS.get(cache_key, 0) < MODEL_CACHE_TTL
    ):
        return MODEL_CACHE[cache_key]

    all_models = []

    # Fetch dari semua OpenAI-compatible endpoints secara parallel
    providers = await Providers.get_active_providers()
    fetch_tasks = [
        _fetch_models_from_provider(provider)
        for provider in providers
    ]
    provider_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    for provider, result in zip(providers, provider_results):
        if isinstance(result, Exception):
            log.warning(f"Provider '{provider.name}' tidak bisa diakses: {result}")
            continue  # Skip provider yang error — jangan gagal total

        for model in result:
            # Tambahkan prefix jika dikonfigurasi
            if provider.prefix:
                model["id"] = f"{provider.prefix}.{model['id']}"

            # Enrich dengan metadata dari DB
            db_model = await Models.get_model_by_id(model["id"])
            if db_model:
                model.update({
                    "description": db_model.meta.get("description"),
                    "tags": db_model.meta.get("tags", []),
                    "capabilities": {
                        "vision": db_model.meta.get("capabilities", {}).get("vision", False),
                        "tools": db_model.meta.get("capabilities", {}).get("tools", False),
                    },
                    "context_length": db_model.params.get("max_tokens"),
                })

            model["provider"] = provider.name
            all_models.append(model)

    # Filter berdasarkan RBAC
    if user.role != "admin":
        allowed_model_ids = await Users.get_allowed_model_ids(user.id)
        if allowed_model_ids:
            all_models = [m for m in all_models if m["id"] in allowed_model_ids]

    MODEL_CACHE[cache_key] = all_models
    MODEL_CACHE_TIMESTAMPS[cache_key] = now
    return all_models


async def _fetch_models_from_provider(provider) -> list[dict]:
    """Fetch model list dari satu provider dengan timeout."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{provider.base_url}/models",
            headers={"Authorization": f"Bearer {provider.api_key}"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            if response.status != 200:
                raise Exception(f"HTTP {response.status}")
            data = await response.json()
            return data.get("data", [])
```

---

## 11. Chat History Persistence (PostgreSQL)

### 11.1 Operasi CRUD Chat

```python
# models/chats.py

class ChatModel:

    @staticmethod
    async def create_chat(
        user_id: str,
        title: str = "Chat Baru",
        model: str | None = None,
    ) -> Chat:
        chat = Chat(
            id=str(uuid4()),
            user_id=user_id,
            title=title,
            chat={
                "title": title,
                "history": {"messages": {}, "currentId": None},
                "models": [model] if model else [],
                "tags": [],
                "files": [],
            },
            created_at=time_ns(),
            updated_at=time_ns(),
        )
        session.add(chat)
        await session.commit()
        return chat

    @staticmethod
    async def get_chat_list_paginated(
        user_id: str,
        page: int = 1,
        limit: int = 60,  # Default 60 per halaman (mengikuti Open WebUI)
        archived: bool = False,
    ) -> list[ChatMetadata]:
        """
        PENTING: Hanya ambil metadata — BUKAN seluruh JSON blob.
        Ini kritis untuk performa saat ratusan chat.
        """
        offset = (page - 1) * limit
        query = (
            select(
                Chat.id,
                Chat.title,
                Chat.updated_at,
                Chat.is_pinned,
                Chat.folder_id,
            )
            .where(
                Chat.user_id == user_id,
                Chat.is_archived == archived,
            )
            .order_by(Chat.is_pinned.desc(), Chat.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(query)
        return [ChatMetadata(*row) for row in result.all()]

    @staticmethod
    async def upsert_message_to_chat(
        chat_id: str,
        message_id: str,
        message_data: dict,
    ) -> Chat | None:
        """
        Update satu message dalam history JSON blob.
        Dipanggil saat streaming untuk real-time save.
        Menggunakan PostgreSQL JSONB update untuk efisiensi.
        """
        # Gunakan PostgreSQL JSONB path untuk atomic update
        await session.execute(
            text("""
                UPDATE chat
                SET
                    chat = jsonb_set(
                        jsonb_set(
                            chat,
                            '{history,messages,:message_id}',
                            :message_data::jsonb,
                            true
                        ),
                        '{history,currentId}',
                        :current_id::jsonb,
                        true
                    ),
                    updated_at = :updated_at
                WHERE id = :chat_id
            """),
            {
                "message_id": message_id,
                "message_data": json.dumps(message_data),
                "current_id": json.dumps(message_id),
                "chat_id": chat_id,
                "updated_at": time_ns(),
            }
        )
        await session.commit()
```

---

## 12. Authentication & Authorization

### 12.1 JWT Token Management

```python
# utils/auth.py

SECRET_KEY = settings.SECRET_KEY  # Dari environment, min 32 karakter
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 hari
REFRESH_TOKEN_EXPIRE_DAYS = 30

def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        "type": "refresh",
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

async def get_verified_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> UserModel:
    """FastAPI dependency untuk validasi token."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(401, "Invalid token type")
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(401, "Invalid token payload")
    except JWTError as e:
        raise HTTPException(401, f"Token tidak valid: {e}")

    user = await Users.get_user_by_id(user_id)
    if not user:
        raise HTTPException(401, "User tidak ditemukan")
    if not user.is_active:
        raise HTTPException(403, "Akun dinonaktifkan")

    return user
```

### 12.2 Auth Endpoints

```python
# routers/auth.py

@router.post("/auth/login")
async def login(form_data: LoginRequest) -> TokenResponse:
    user = await Users.get_user_by_email(form_data.email)
    if not user or not verify_password(form_data.password, user.hashed_password):
        # Delay untuk mencegah timing attack
        await asyncio.sleep(0.5)
        raise HTTPException(401, "Email atau password salah")

    return TokenResponse(
        access_token=create_access_token(user.id, user.email, user.role),
        refresh_token=create_refresh_token(user.id),
        token_type="bearer",
        user=UserResponse.from_orm(user),
    )

@router.post("/auth/refresh")
async def refresh_token(body: RefreshRequest) -> TokenResponse:
    try:
        payload = jwt.decode(body.refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(401, "Invalid token type")
    except JWTError:
        raise HTTPException(401, "Refresh token tidak valid")

    user = await Users.get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(401, "User tidak ditemukan")

    return TokenResponse(
        access_token=create_access_token(user.id, user.email, user.role),
        refresh_token=create_refresh_token(user.id),
        token_type="bearer",
        user=UserResponse.from_orm(user),
    )
```

---

## 13. PersistentConfig System

### 13.1 Konsep & Implementasi

```python
# config.py

class PersistentConfig:
    """
    Konfigurasi yang:
    1. Dibaca dari environment variable saat startup (priority tertinggi)
    2. Jika tidak ada env var, dibaca dari database
    3. Jika tidak ada di DB, gunakan default value
    4. Perubahan via Admin API langsung efektif tanpa restart server
    """

    def __init__(self, env_name: str, config_path: str, default_value):
        self.env_name = env_name
        self.config_path = config_path
        self.default_value = default_value
        self._value = self._load_initial_value()

    def _load_initial_value(self):
        # Priority 1: Environment variable
        env_value = os.environ.get(self.env_name)
        if env_value is not None:
            return self._parse(env_value)

        # Priority 2: Database
        db_value = self._load_from_db()
        if db_value is not None:
            return db_value

        # Priority 3: Default
        return self.default_value

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, new_value):
        self._value = new_value
        self._save_to_db(new_value)  # Langsung persist, efektif tanpa restart


# Semua konfigurasi yang bisa diubah runtime

# RAG
CHUNK_SIZE = PersistentConfig("CHUNK_SIZE", "rag.chunk_size", 1500)
CHUNK_OVERLAP = PersistentConfig("CHUNK_OVERLAP", "rag.chunk_overlap", 100)
RAG_TOP_K = PersistentConfig("RAG_TOP_K", "rag.top_k", 5)
RAG_RELEVANCE_THRESHOLD = PersistentConfig("RAG_RELEVANCE_THRESHOLD", "rag.threshold", 0.3)
RAG_EMBEDDING_MODEL = PersistentConfig("RAG_EMBEDDING_MODEL", "rag.embedding_model", "text-embedding-3-small")
ENABLE_RAG_QUERY_GENERATION = PersistentConfig("ENABLE_RAG_QUERY_GENERATION", "rag.query_gen", True)
ENABLE_RAG_RERANKING = PersistentConfig("ENABLE_RAG_RERANKING", "rag.reranking", False)

# Web Search
ENABLE_WEB_SEARCH = PersistentConfig("ENABLE_WEB_SEARCH", "websearch.enabled", False)
WEB_SEARCH_ENGINE = PersistentConfig("WEB_SEARCH_ENGINE", "websearch.engine", "duckduckgo")
SEARCH_RESULT_COUNT = PersistentConfig("SEARCH_RESULT_COUNT", "websearch.count", 5)
ENABLE_WEB_CONTENT_EXTRACTION = PersistentConfig("ENABLE_WEB_CONTENT_EXTRACTION", "websearch.extract", True)

# Tasks
TASK_MODEL = PersistentConfig("TASK_MODEL", "tasks.model", "")
TITLE_GENERATION_PROMPT = PersistentConfig("TITLE_GENERATION_PROMPT", "tasks.title_prompt", DEFAULT_TITLE_PROMPT)
ENABLE_TITLE_GENERATION = PersistentConfig("ENABLE_TITLE_GENERATION", "tasks.title_gen", True)
ENABLE_TAG_GENERATION = PersistentConfig("ENABLE_TAG_GENERATION", "tasks.tag_gen", True)

# Features
ENABLE_IMAGE_GENERATION = PersistentConfig("ENABLE_IMAGE_GENERATION", "features.image_gen", False)
ENABLE_CODE_INTERPRETER = PersistentConfig("ENABLE_CODE_INTERPRETER", "features.code_interpreter", False)
ENABLE_MEMORY = PersistentConfig("ENABLE_MEMORY", "features.memory", False)
```

---

## 14. Background Tasks

### 14.1 Title Generation

```python
# utils/task.py

DEFAULT_TITLE_PROMPT = """Berdasarkan percakapan di bawah, buat judul yang singkat (maksimal 6 kata), 
deskriptif, dan dalam bahasa yang sama dengan percakapan. 
Hanya kembalikan judulnya saja, tanpa penjelasan atau tanda kutip.

Percakapan:
{messages}

Judul:"""

async def generate_chat_title(
    chat_id: str,
    messages: list[dict],
    model_id: str,
    user: UserModel,
) -> str:
    """
    Generate judul chat via LLM secara background.
    Dipanggil setelah streaming selesai — TIDAK blocking response.
    """
    # Ambil hanya 2 pesan pertama (cukup untuk context judul)
    context = messages[:2]

    formatted = "\n".join([
        f"{m['role'].upper()}: {m['content'][:500]}"  # Batasi 500 karakter per pesan
        for m in context
    ])

    prompt = settings.TITLE_GENERATION_PROMPT.value.format(messages=formatted)

    try:
        # Gunakan model task ringan jika dikonfigurasi
        task_model = settings.TASK_MODEL.value or model_id
        response = await call_provider_sync(
            model=task_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
            stream=False,
        )
        title = response.choices[0].message.content.strip()

        # Sanitasi: hapus tanda kutip, batasi panjang
        title = title.strip('"\'').strip()
        if len(title) > 100:
            title = title[:97] + "..."

    except Exception as e:
        log.warning(f"Title generation gagal: {e}")
        # Fallback: ambil 50 karakter pertama pesan user
        user_msg = next((m["content"] for m in messages if m["role"] == "user"), "Chat Baru")
        title = user_msg[:50] + ("..." if len(user_msg) > 50 else "")

    # Update DB
    await Chats.update_chat_title(chat_id, title)

    log.info(f"Title generated for chat {chat_id}: '{title}'")
    return title


async def _run_post_completion_tasks(
    chat_id: str,
    messages: list[dict],
    model_id: str,
    user: UserModel,
    is_new_chat: bool,
) -> None:
    """
    Runner untuk semua background tasks setelah streaming selesai.
    Dipanggil via FastAPI BackgroundTasks — tidak blocking.
    """
    tasks = []

    if is_new_chat and settings.ENABLE_TITLE_GENERATION.value:
        tasks.append(generate_chat_title(chat_id, messages, model_id, user))

    if settings.ENABLE_TAG_GENERATION.value:
        tasks.append(generate_chat_tags(chat_id, messages, model_id))

    # Jalankan semua tasks parallel
    await asyncio.gather(*tasks, return_exceptions=True)
```

---

## 15. API Endpoints Lengkap

### 15.1 Daftar Endpoint

```
# ── Authentication ──────────────────────────────────────────────
POST   /auth/login                 # Login dengan email & password
POST   /auth/logout                # Logout (invalidate token)
POST   /auth/refresh               # Refresh access token
GET    /auth/me                    # Get current user profile
POST   /auth/register              # Register user baru (jika diizinkan)
PUT    /auth/me/password           # Ganti password

# ── Provider Management ─────────────────────────────────────────
GET    /api/providers              # List semua provider yang dikonfigurasi
POST   /api/providers              # Tambah provider baru
GET    /api/providers/{id}         # Detail provider
PUT    /api/providers/{id}         # Update provider
DELETE /api/providers/{id}         # Hapus provider
POST   /api/providers/{id}/test    # Test koneksi ke provider

# ── Models ─────────────────────────────────────────────────────
GET    /api/models                 # Aggregated list dari semua provider
POST   /api/models/refresh         # Force refresh cache model list
GET    /api/models/{id}            # Detail model specific

# ── Chat Completion (UTAMA) ────────────────────────────────────
POST   /api/chat/completions       # SSE streaming, full pipeline

# ── Chat History ───────────────────────────────────────────────
GET    /api/chats                  # List chat (paginated, metadata only)
POST   /api/chats                  # Buat chat baru
GET    /api/chats/{id}             # Get chat dengan full history
PUT    /api/chats/{id}             # Update chat (title, tags, pinned)
DELETE /api/chats/{id}             # Hapus chat
DELETE /api/chats                  # Hapus semua chat user

GET    /api/chats/{id}/messages    # Get messages dari chat
POST   /api/chats/{id}/messages    # Tambah/update message

POST   /api/chats/{id}/archive     # Archive chat
POST   /api/chats/{id}/pin         # Pin/unpin chat

# ── Files & RAG ────────────────────────────────────────────────
POST   /api/files/upload           # Upload file (multipart/form-data)
GET    /api/files                  # List file milik user
GET    /api/files/{id}             # Get file metadata
DELETE /api/files/{id}             # Hapus file + koleksi vector

# ── Web Search (test/manual) ──────────────────────────────────
POST   /api/retrieval/web/search   # Manual web search (testing)

# ── Background Tasks ──────────────────────────────────────────
POST   /api/tasks/title            # Manual generate title
POST   /api/tasks/tags             # Manual generate tags

# ── Admin Only ────────────────────────────────────────────────
GET    /api/admin/users            # List users
POST   /api/admin/users            # Buat user (tanpa self-register)
PUT    /api/admin/users/{id}       # Update user
DELETE /api/admin/users/{id}       # Hapus user
GET    /api/admin/config           # Get all PersistentConfig
PUT    /api/admin/config           # Update PersistentConfig

# ── Health & Monitoring ────────────────────────────────────────
GET    /health                     # Health check
GET    /metrics                    # Prometheus metrics
```

### 15.2 Request/Response Format

```python
# POST /api/chat/completions — Request dari Flutter
{
    "model": "gpt-4o",
    "messages": [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "Halo!"}
    ],
    "stream": true,                 # HARUS true untuk SSE
    "files": [                      # Opsional — untuk RAG
        {"type": "file", "id": "uuid-file"}
    ],
    "web_search": false,            # Opsional — aktifkan web search
    "temperature": 0.7,             # Opsional — override parameter
    "max_tokens": 2048              # Opsional
}

# GET /api/chats — Response
{
    "data": [
        {
            "id": "uuid",
            "title": "Diskusi tentang AI",
            "model_id": "gpt-4o",
            "is_pinned": false,
            "updated_at": 1717200000000,
            "folder_id": null
        }
    ],
    "total": 150,
    "page": 1,
    "has_more": true
}
```

---

## 16. Database Schema

### 16.1 Tabel Utama

```sql
-- Users
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    hashed_password TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'user',  -- 'admin' | 'user'
    is_active       BOOLEAN DEFAULT TRUE,
    settings        JSONB DEFAULT '{}',            -- model preferences, dll
    created_at      BIGINT NOT NULL,               -- Unix timestamp nanoseconds
    updated_at      BIGINT NOT NULL
);

-- Chat (history sebagai JSONB blob)
CREATE TABLE chats (
    id          UUID PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL DEFAULT 'Chat Baru',
    chat        JSONB NOT NULL DEFAULT '{}',       -- Seluruh tree history
    is_shared   BOOLEAN DEFAULT FALSE,
    share_id    TEXT UNIQUE,                       -- Untuk share link
    is_archived BOOLEAN DEFAULT FALSE,
    is_pinned   BOOLEAN DEFAULT FALSE,
    folder_id   UUID,
    created_at  BIGINT NOT NULL,
    updated_at  BIGINT NOT NULL
);

-- Providers (AI provider connections)
CREATE TABLE providers (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    base_url    TEXT NOT NULL,
    api_key     TEXT,                              -- Encrypted di aplikasi
    auth_type   TEXT DEFAULT 'bearer',
    prefix      TEXT,                              -- Model ID prefix
    is_active   BOOLEAN DEFAULT TRUE,
    extra_config JSONB DEFAULT '{}',
    created_at  BIGINT NOT NULL,
    updated_at  BIGINT NOT NULL
);

-- Files (metadata upload)
CREATE TABLE files (
    id               UUID PRIMARY KEY,
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename         TEXT NOT NULL,
    content_type     TEXT NOT NULL,
    file_path        TEXT NOT NULL,
    collection_name  TEXT NOT NULL,               -- Nama koleksi di pgvector
    chunk_count      INTEGER DEFAULT 0,
    size_bytes       BIGINT DEFAULT 0,
    created_at       BIGINT NOT NULL
);

-- App config (PersistentConfig storage)
CREATE TABLE app_config (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_path TEXT UNIQUE NOT NULL,
    value       JSONB NOT NULL,
    updated_at  BIGINT NOT NULL
);

-- Index untuk performa
CREATE INDEX idx_chats_user_updated ON chats(user_id, updated_at DESC);
CREATE INDEX idx_chats_user_archived ON chats(user_id, is_archived);
CREATE INDEX idx_chats_pinned ON chats(user_id, is_pinned, updated_at DESC);
CREATE INDEX idx_files_user ON files(user_id, created_at DESC);
```

### 16.2 pgvector Schema

```sql
-- Aktifkan extension pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Tabel vector (satu per koleksi, atau shared dengan collection_name filter)
CREATE TABLE vector_store (
    id              TEXT PRIMARY KEY,
    collection_name TEXT NOT NULL,
    content         TEXT NOT NULL,
    embedding       VECTOR(1536),                  -- Dimensi sesuai model embedding
    metadata        JSONB DEFAULT '{}',
    created_at      BIGINT NOT NULL
);

-- Index IVFFlat untuk similarity search yang cepat
-- lists = sqrt(jumlah rows) adalah rule of thumb
CREATE INDEX idx_vector_embedding ON vector_store
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX idx_vector_collection ON vector_store(collection_name);

-- Fungsi similarity search
CREATE OR REPLACE FUNCTION search_vectors(
    collection TEXT,
    query_embedding VECTOR(1536),
    top_k INTEGER DEFAULT 5,
    score_threshold FLOAT DEFAULT 0.3
)
RETURNS TABLE(id TEXT, content TEXT, metadata JSONB, score FLOAT)
AS $$
    SELECT
        id,
        content,
        metadata,
        1 - (embedding <=> query_embedding) AS score
    FROM vector_store
    WHERE collection_name = collection
      AND 1 - (embedding <=> query_embedding) >= score_threshold
    ORDER BY embedding <=> query_embedding
    LIMIT top_k;
$$ LANGUAGE SQL;
```

---

## 17. Konfigurasi & Environment Variables

```bash
# ── Core ────────────────────────────────────────────────────────
SECRET_KEY=<min-32-char-random-string>      # JWT signing key — WAJIB
DATABASE_URL=postgresql+asyncpg://user:pass@host/dbname
ENVIRONMENT=production                       # production | development

# ── Server ──────────────────────────────────────────────────────
HOST=0.0.0.0
PORT=8000
WORKERS=4                                    # Uvicorn workers
LOG_LEVEL=info

# ── Auth ────────────────────────────────────────────────────────
ENABLE_SIGNUP=false                          # Matikan self-register di produksi
ACCESS_TOKEN_EXPIRE_MINUTES=10080           # 7 hari
ALLOWED_CORS_ORIGINS=*                      # Atau spesifik: https://app.example.com

# ── Embedding ────────────────────────────────────────────────────
EMBEDDING_ENGINE=openai                     # openai | ollama | local
RAG_EMBEDDING_MODEL=text-embedding-3-small

# ── Chunking (bisa di-override via Admin UI) ────────────────────
CHUNK_SIZE=1500
CHUNK_OVERLAP=100
RAG_TOP_K=5
RAG_RELEVANCE_THRESHOLD=0.3

# ── Web Search ──────────────────────────────────────────────────
ENABLE_WEB_SEARCH=false
WEB_SEARCH_ENGINE=duckduckgo
BRAVE_SEARCH_API_KEY=
TAVILY_API_KEY=
SEARXNG_QUERY_URL=

# ── File Storage ────────────────────────────────────────────────
STORAGE_PROVIDER=local                      # local | s3
UPLOAD_DIR=/app/uploads
AWS_S3_BUCKET_NAME=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=ap-southeast-1

# ── Task Model ──────────────────────────────────────────────────
TASK_MODEL=                                  # Kosong = gunakan model yang sama
ENABLE_TITLE_GENERATION=true
ENABLE_TAG_GENERATION=true

# ── Redis (opsional, untuk caching & task queue) ─────────────────
REDIS_URL=redis://localhost:6379/0

# ── Monitoring ──────────────────────────────────────────────────
ENABLE_METRICS=true
SENTRY_DSN=                                  # Opsional
```

---

## 18. Keamanan Backend

### 18.1 Checklist Keamanan

```
AUTENTIKASI:
✅ JWT dengan secret key kuat (min 32 karakter, random)
✅ Token expire time yang masuk akal (7 hari access, 30 hari refresh)
✅ Password di-hash menggunakan bcrypt (cost factor 12)
✅ Rate limiting pada endpoint auth (max 5 login attempt/menit/IP)
✅ Delay response pada login gagal (anti timing attack)

OTORISASI:
✅ RBAC: admin vs user roles
✅ User hanya bisa akses chat/file milik sendiri
✅ Admin endpoint dilindungi role check
✅ Model filtering berdasarkan role

INPUT VALIDATION:
✅ Validasi tipe file upload (whitelist, bukan blacklist)
✅ Validasi ukuran file (max 50MB default)
✅ Sanitasi nama file (path traversal prevention)
✅ Validasi panjang message (cegah context flooding)
✅ Pydantic model untuk semua request body

API SECURITY:
✅ CORS dikonfigurasi eksplisit (bukan *)
✅ HTTPS only di produksi (TLS termination di load balancer)
✅ Request rate limiting (max 60 request/menit/user)
✅ SSE timeout (max 5 menit streaming)

DATA:
✅ API key provider dienkripsi di DB (tidak disimpan plain text)
✅ Log tidak mengandung API key atau token
✅ Database connection menggunakan SSL

DEPENDENCY:
✅ Dependency scanning reguler (safety, snyk)
✅ Docker image dari base image official yang terupdate
```

### 18.2 Rate Limiting

```python
# main.py — Middleware rate limiting

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.on_event("startup")
async def startup():
    app.state.limiter = limiter

# Di router endpoints:
@router.post("/auth/login")
@limiter.limit("5/minute")
async def login(request: Request, ...):
    ...

@router.post("/api/chat/completions")
@limiter.limit("60/minute")
async def chat_completions(request: Request, ...):
    ...
```

---

## 19. Monitoring & Logging

### 19.1 Structured Logging

```python
# main.py

import structlog

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

log = structlog.get_logger()

# Contoh penggunaan di endpoint:
log.info(
    "chat_completion_started",
    chat_id=chat_id,
    model=model_id,
    user_id=user.id,
    has_files=bool(file_ids),
    web_search=web_search_mode,
)
```

### 19.2 Prometheus Metrics

```python
# main.py

from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)

# Custom metrics:
from prometheus_client import Counter, Histogram

chat_requests_total = Counter(
    "chat_requests_total",
    "Total chat completion requests",
    ["model", "user_role", "has_files"],
)

streaming_duration_seconds = Histogram(
    "streaming_duration_seconds",
    "Duration of SSE streaming in seconds",
    ["model"],
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

rag_chunks_retrieved = Histogram(
    "rag_chunks_retrieved",
    "Number of RAG chunks retrieved per request",
    buckets=[0, 1, 2, 5, 10, 20],
)
```

---

## 20. Pengujian Backend

### 20.1 Test SSE Streaming

```python
# tests/test_sse_streaming.py

import pytest
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_streaming_returns_sse_format():
    """Verifikasi format SSE yang diterima Flutter."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        async with client.stream(
            "POST",
            "/api/chat/completions",
            headers={"Authorization": f"Bearer {test_token}"},
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Halo"}],
                "stream": True,
            },
        ) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            assert response.headers.get("x-accel-buffering") == "no"

            chunks = []
            async for line in response.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    data = json.loads(line[6:])
                    chunks.append(data)

            assert len(chunks) > 0
            # Verifikasi format chunk OpenAI
            assert "choices" in chunks[0]
            assert "delta" in chunks[0]["choices"][0]


@pytest.mark.asyncio
async def test_disconnect_stops_generation():
    """Verifikasi bahwa disconnect client menghentikan generasi."""
    started = asyncio.Event()
    stopped = asyncio.Event()

    # Implementasi test dengan mock provider yang detects disconnect
    ...
```

### 20.2 Test RAG Pipeline

```python
# tests/test_rag_pipeline.py

@pytest.mark.asyncio
async def test_file_upload_and_retrieval():
    """Full RAG pipeline: upload → index → retrieve."""
    # Upload file
    test_file = b"Ini adalah dokumen test tentang kecerdasan buatan."
    response = await client.post(
        "/api/files/upload",
        files={"file": ("test.txt", test_file, "text/plain")},
        headers=auth_headers,
    )
    assert response.status_code == 200
    file_id = response.json()["id"]

    # Verifikasi file terindex di pgvector
    collection = response.json()["collection_name"]
    count = await pgvector_client.count_documents(collection)
    assert count > 0

    # Chat dengan file → verifikasi RAG dijalankan
    sse_events = []
    async with client.stream(
        "POST",
        "/api/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "Apa yang ada di dokumen?"}],
            "files": [{"type": "file", "id": file_id}],
            "stream": True,
        },
        headers=auth_headers,
    ) as response:
        async for line in response.aiter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                data = json.loads(line[6:])
                if data.get("type") == "citation":
                    sse_events.append(data)

    # Verifikasi citation event dikirim
    assert len(sse_events) > 0
    assert "kecerdasan buatan" in sse_events[0]["data"]["document"][0]
```

---

## 21. Deployment di AWS

### 21.1 Arsitektur AWS yang Direkomendasikan

```
Internet
    │
    ▼
[CloudFront]          ← CDN (opsional, untuk static assets)
    │
    ▼
[Application Load Balancer]
    │
    ├─── [ECS / EC2 Auto Scaling Group]
    │         │
    │         ├── FastAPI Backend (container)
    │         └── FastAPI Backend (container)
    │
    ├─── [RDS PostgreSQL]    ← Database utama + pgvector
    │
    ├─── [ElastiCache Redis] ← Caching model list, session (opsional)
    │
    └─── [S3]               ← File storage (upload)
```

### 21.2 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Buat user non-root
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### 21.3 Nginx Config (SSE Critical)

```nginx
# nginx.conf — Konfigurasi kritis untuk SSE streaming

upstream fastapi {
    server backend:8000;
}

server {
    listen 443 ssl;
    server_name api.example.com;

    location /api/chat/completions {
        proxy_pass http://fastapi;
        proxy_http_version 1.1;

        # KRITIS: Disable buffering untuk SSE
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;        # 5 menit untuk stream panjang
        proxy_send_timeout 300s;

        # Header SSE
        add_header Cache-Control no-cache;
        add_header X-Accel-Buffering no;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Authorization $http_authorization;
    }

    location / {
        proxy_pass http://fastapi;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 60s;
    }
}
```

---

## Poin Implementasi Kritis (Lessons from Open WebUI)

### Tentang SSE
- **Selalu kirim** `X-Accel-Buffering: no` — kalau tidak, Nginx buffer response dan streaming terasa tersendat atau bahkan tidak muncul sampai selesai.
- **Handle disconnect** via `request.is_disconnected()` — ini cara FastAPI mendeteksi Flutter menutup koneksi (klik Stop).
- **Simpan partial content** ke DB bahkan saat streaming terpotong — ini penting untuk UX.
- **Skip chunk malformed** — jangan hentikan stream karena satu chunk gagal di-parse JSON.

### Tentang RAG
- **Index sekali, query berkali-kali** — jangan proses ulang file per request, ini sangat mahal.
- **Generate retrieval query via LLM** sebelum similarity search — meningkatkan recall secara signifikan dibanding langsung query dengan teks user.
- **Chunk size 1000-1500 karakter dengan overlap 100-200** adalah sweet spot yang terbukti.
- **Gunakan PostgreSQL JSONB path update** untuk upsert message — lebih efisien dari load + modify + save seluruh blob.

### Tentang Tool Calling
- **Batasi max iterasi** (10-30) — tanpa batas menyebabkan infinite loop yang menguras token dan biaya.
- **Tool error dikembalikan ke AI** sebagai `role: "tool"` message — ini memberi AI kesempatan recover.
- **Eksekusi parallel** via `asyncio.gather` — penting untuk multiple tool calls yang tidak bergantung satu sama lain.

### Tentang Background Tasks
- **JANGAN await** title generation sebelum return StreamingResponse — gunakan `BackgroundTasks` FastAPI.
- **Gunakan model ringan** untuk title/tag generation — tidak perlu model besar untuk tugas sederhana ini.
- **Fallback title** jika generation gagal: ambil 50 karakter pertama pesan user.

### Tentang Model Discovery
- **Cache dengan TTL 5 menit** — cegah hammering provider API setiap request.
- **Jangan gagal total** jika satu provider error — log warning, skip, lanjutkan dengan provider lain.
- **Parallel fetch** model dari semua provider dengan `asyncio.gather` + `return_exceptions=True`.

---

*Dokumen ini adalah spesifikasi teknis untuk pengembangan FastAPI Backend dari sistem AI Chat. Referensi arsitektur: Open WebUI v0.9.2. Semua contoh kode menggunakan Python 3.11+ dengan FastAPI, SQLAlchemy async, dan aiohttp.*
