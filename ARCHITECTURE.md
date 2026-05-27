# Arsitektur Teknis — Backend AI Chat (FastAPI)

> **Berdasarkan:** SRS_Backend_FastAPI.md v1.1.0  
> **Tanggal:** 2026-05-27  
> **Stack:** Python 3.11+, FastAPI 0.111.0, PostgreSQL + pgvector, SQLAlchemy 2.0 (async)  
> **Deployment:** AWS (ECS/EC2 + RDS PostgreSQL + ElastiCache Redis + S3)

---

## Daftar Isi

1. [Ringkasan Sistem](#1-ringkasan-sistem)
2. [Arsitektur Tinggi](#2-arsitektur-tinggi)
3. [Struktur Direktori](#3-struktur-direktori)
4. [Database Schema](#4-database-schema)
5. [API Endpoints](#5-api-endpoints)
6. [Module Responsibilities](#6-module-responsibilities)
7. [Data Flow Diagrams](#7-data-flow-diagrams)
8. [Konfigurasi & Environment Variables](#8-konfigurasi--environment-variables)
9. [Error Handling Strategy](#9-error-handling-strategy)
10. [Security Considerations](#10-security-considerations)
11. [Monitoring & Logging](#11-monitoring--logging)
12. [Deployment Architecture](#12-deployment-architecture)

---

## 1. Ringkasan Sistem

### 1.1 Tujuan

Backend FastAPI berfungsi sebagai **orkestrasi AI** yang menerima request dari Flutter client, menjalankan seluruh pipeline (auth, RAG, web search, tool execution, streaming), dan mengirim respons SSE balik ke client. Backend juga bertanggung jawab atas penyimpanan data server-side dan sinkronisasi antar device.

### 1.2 Tanggung Jawab Backend

| Tanggung Jawab | Deskripsi |
|---|---|
| **Auth** | JWT token issuance, validation, refresh |
| **AI Proxy** | Forward request ke OpenAI/vLLM, stream SSE balik ke client |
| **RAG Pipeline** | Upload, extract teks, chunking, embedding, pgvector storage & retrieval |
| **Web Search** | Call search API, extract konten halaman, inject context |
| **Tool Execution** | Eksekusi tools Python (web fetch, code sandbox, dll) |
| **Chat History** | Simpan di PostgreSQL, sync antar device |
| **Model Aggregation** | Satu `/models` endpoint untuk semua provider yang dikonfigurasi |
| **Background Tasks** | Title & tag generation setelah streaming selesai |
| **User Management** | Accounts, sessions, RBAC |
| **File Storage** | Simpan file upload ke S3/lokal, kelola lifecycle |
| **PersistentConfig** | Konfigurasi runtime yang bisa diubah tanpa restart |
| **Rate Limiting** | Cegah abuse per user/IP |

### 1.3 Tanggung Jawab Flutter Client (Bukan Backend)

- UI/UX rendering
- Local caching di device (SQLite)
- Client-side event bus (AppEventBus)

---

## 2. Arsitektur Tinggi

### 2.1 Komponen Utama

```mermaid
graph TB
    subgraph Client["Flutter Client"]
        FC[Flutter App]
        CB[Cache SQLite]
        EB[EventBus]
    end

    subgraph AWS["AWS Infrastructure"]
        ALB[Application Load Balancer]
        subgraph Compute["ECS / EC2 Auto Scaling"]
            API1[FastAPI Worker 1]
            API2[FastAPI Worker 2]
        end
    end

    subgraph Storage["AWS Storage"]
        RDS[(RDS PostgreSQL<br/>+ pgvector)]
        ELASTI[(ElastiCache Redis)]
        S3[(S3 Bucket)]
    end

    subgraph External["External Providers"]
        OPENAI[OpenAI / Compatible APIs]
        SEARCH[Brave / Tavily / SearXNG]
        EMBED[Embedding API / Local Model]
    end

    FC -->|HTTPS + JWT| ALB
    ALB --> API1
    ALB --> API2
    API1 --> RDS
    API1 --> ELASTI
    API1 --> S3
    API1 --> OPENAI
    API1 --> SEARCH
    API1 --> EMBED
    API2 --> RDS
    API2 --> ELASTI
    API2 --> S3
    API2 --> OPENAI
    API2 --> SEARCH
    API2 --> EMBED
    CB -.->|Offline| FC
    FC --- EB
```

### 2.2 Lapisan Arsitektur

```
┌─────────────────────────────────────────────────────────────┐
│                    Flutter Client                           │
├─────────────────────────────────────────────────────────────┤
│  Lapisan 5: Presentation                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Routers / API Layer                                   │  │
│  │ - AuthRouter, ChatRouter, ChatsRouter, etc.           │  │
│  │ - Input validation (Pydantic)                         │  │
│  │ - Rate limiting                                       │  │
│  └───────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  Lapisan 4: Orchestration                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ utils/chat.py — generate_chat_completion()            │  │
│  │ - Pipeline coordinator                                  │  │
│  │ - SSE streaming controller                              │  │
│  │ - Tool calling loop                                     │  │
│  └───────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  Lapisan 3: Domain Utilities                                │
│  ┌──────────┬──────────┬──────────┬──────────────────────┐  │
│  │ RAG      │ Web      │ Tool     │ Model Aggregation    │  │
│  │ Pipeline │ Search   │ Exec     │                      │  │
│  └──────────┴──────────┴──────────┴──────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  Lapisan 2: Data Access                                     │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ SQLAlchemy ORM (async)                                │  │
│  │ - ORM Models (users, chats, files, providers, config) │  │
│  │ - pgvector adapter                                    │  │
│  │ - Storage adapter (local/S3)                           │  │
│  └───────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  Lapisan 1: Infrastructure                                  │
│  ┌──────────┬──────────┬──────────┬──────────────────────┐  │
│  │ PostgreSQL│ Redis    │ S3/Local│ External APIs        │  │
│  │ + pgvector│          │          │ (OpenAI, Search)     │  │
│  └──────────┴──────────┴──────────┴──────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Struktur Direktori

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
│   ├── chats.py                    # Chat model
│   ├── users.py                    # User model
│   ├── files.py                    # File model
│   ├── providers.py                # Provider model
│   └── config.py                   # AppConfig model
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

---

## 4. Database Schema

### 4.1 Entity Relationship Diagram

```mermaid
erDiagram
    USERS {
        UUID id PK
        TEXT email UK
        TEXT name
        TEXT hashed_password
        TEXT role "admin | user"
        BOOLEAN is_active
        JSONB settings
        BIGINT created_at
        BIGINT updated_at
    }

    CHATS {
        UUID id PK
        UUID user_id FK
        TEXT title
        JSONB chat "history, messages, files, tags"
        BOOLEAN is_shared
        TEXT share_id UK
        BOOLEAN is_archived
        BOOLEAN is_pinned
        UUID folder_id
        BIGINT created_at
        BIGINT updated_at
    }

    PROVIDERS {
        UUID id PK
        TEXT name
        TEXT base_url
        TEXT api_key "encrypted"
        TEXT auth_type
        TEXT prefix
        BOOLEAN is_active
        JSONB extra_config
        BIGINT created_at
        BIGINT updated_at
    }

    FILES {
        UUID id PK
        UUID user_id FK
        TEXT filename
        TEXT content_type
        TEXT file_path
        TEXT collection_name
        INTEGER chunk_count
        BIGINT size_bytes
        BIGINT created_at
    }

    APP_CONFIG {
        UUID id PK
        TEXT config_path UK
        JSONB value
        BIGINT updated_at
    }

    USERS ||--o{ CHATS : "owns"
    USERS ||--o{ FILES : "owns"
```

### 4.2 Detail Tabel

#### 4.2.1 Tabel `users`

Tabel utama untuk autentikasi dan otorisasi.

```sql
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    hashed_password TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'user',
    is_active       BOOLEAN DEFAULT TRUE,
    settings        JSONB DEFAULT '{}',
    created_at      BIGINT NOT NULL,
    updated_at      BIGINT NOT NULL
);
```

| Kolom | Tipe | Constraint | Deskripsi |
|---|---|---|---|
| `id` | UUID | PK, gen_random_uuid() | Identifier unik pengguna |
| `email` | TEXT | UNIQUE, NOT NULL | Email untuk login |
| `name` | TEXT | NOT NULL | Nama tampilan pengguna |
| `hashed_password` | TEXT | NOT NULL | Password yang di-hash bcrypt |
| `role` | TEXT | DEFAULT 'user' | 'admin' atau 'user' |
| `is_active` | BOOLEAN | DEFAULT TRUE | Status aktif/nonaktif akun |
| `settings` | JSONB | DEFAULT '{}' | Preferensi user (model, dll) |
| `created_at` | BIGINT | NOT NULL | Unix timestamp (nanosecond) |
| `updated_at` | BIGINT | NOT NULL | Unix timestamp (nanosecond) |

**Indeks:**
```sql
CREATE INDEX idx_users_email ON users(email);
```

#### 4.2.2 Tabel `chats`

Menyimpan seluruh history percakapan dalam format JSONB.

```sql
CREATE TABLE chats (
    id          UUID PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL DEFAULT 'Chat Baru',
    chat        JSONB NOT NULL DEFAULT '{}',
    is_shared   BOOLEAN DEFAULT FALSE,
    share_id    TEXT UNIQUE,
    is_archived BOOLEAN DEFAULT FALSE,
    is_pinned   BOOLEAN DEFAULT FALSE,
    folder_id   UUID,
    created_at  BIGINT NOT NULL,
    updated_at  BIGINT NOT NULL
);
```

| Kolom | Tipe | Constraint | Deskripsi |
|---|---|---|---|
| `id` | UUID | PK | Identifier unik chat |
| `user_id` | UUID | FK → users.id, CASCADE | Pemilik chat |
| `title` | TEXT | DEFAULT 'Chat Baru' | Judul percakapan |
| `chat` | JSONB | NOT NULL, DEFAULT '{}' | Tree history lengkap (lihat struktur di bawah) |
| `is_shared` | BOOLEAN | DEFAULT FALSE | Status berbagi publik |
| `share_id` | TEXT | UNIQUE | Identifier untuk share link |
| `is_archived` | BOOLEAN | DEFAULT FALSE | Status arsip |
| `is_pinned` | BOOLEAN | DEFAULT FALSE | Status pinned di daftar |
| `folder_id` | UUID | NULL | Kategori folder |
| `created_at` | BIGINT | NOT NULL | Unix timestamp (nanosecond) |
| `updated_at` | BIGINT | NOT NULL | Unix timestamp (nanosecond) |

**Struktur JSONB `chat`:**
```json
{
  "title": "Diskusi tentang AI",
  "history": {
    "messages": {
      "msg-id-1": {
        "id": "msg-id-1",
        "role": "user",
        "content": "Halo!",
        "timestamp": 1717200000000,
        "files": [],
        "web_search": false
      },
      "msg-id-2": {
        "id": "msg-id-2",
        "role": "assistant",
        "content": "Halo! Ada yang bisa saya bantu?",
        "tool_calls": null,
        "done": true,
        "stopped": false,
        "usage": {
          "prompt_tokens": 10,
          "completion_tokens": 15,
          "total_tokens": 25
        },
        "timestamp": 1717200001000
      }
    },
    "currentId": "msg-id-2"
  },
  "models": ["gpt-4o"],
  "tags": [],
  "files": [
    {"type": "file", "id": "file-uuid-1"}
  ]
}
```

**Indeks:**
```sql
CREATE INDEX idx_chats_user_updated ON chats(user_id, updated_at DESC);
CREATE INDEX idx_chats_user_archived ON chats(user_id, is_archived);
CREATE INDEX idx_chats_pinned ON chats(user_id, is_pinned, updated_at DESC);
CREATE INDEX idx_chats_updated ON chats(updated_at DESC);
```

#### 4.2.3 Tabel `providers`

Menyimpan konfigurasi koneksi ke AI provider.

```sql
CREATE TABLE providers (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    base_url    TEXT NOT NULL,
    api_key     TEXT,
    auth_type   TEXT DEFAULT 'bearer',
    prefix      TEXT,
    is_active   BOOLEAN DEFAULT TRUE,
    extra_config JSONB DEFAULT '{}',
    created_at  BIGINT NOT NULL,
    updated_at  BIGINT NOT NULL
);
```

| Kolom | Tipe | Constraint | Deskripsi |
|---|---|---|---|
| `id` | UUID | PK | Identifier unik provider |
| `name` | TEXT | NOT NULL | Nama provider (display) |
| `base_url` | TEXT | NOT NULL | URL API endpoint |
| `api_key` | TEXT | NULL | API key (dienkripsi di aplikasi) |
| `auth_type` | TEXT | DEFAULT 'bearer' | 'bearer', 'azure_ad', 'system_oauth', 'session', 'none' |
| `prefix` | TEXT | NULL | Prefix untuk model ID |
| `is_active` | BOOLEAN | DEFAULT TRUE | Status aktif/nonaktif |
| `extra_config` | JSONB | DEFAULT '{}' | Header custom, konfigurasi tambahan |
| `created_at` | BIGINT | NOT NULL | Unix timestamp |
| `updated_at` | BIGINT | NOT NULL | Unix timestamp |

**Auth Types:**

| auth_type | Deskripsi | Contoh Use Case |
|---|---|---|
| `bearer` | Standard Bearer token | OpenAI, most compatible APIs |
| `azure_ad` | Azure Active Directory | Azure OpenAI Service |
| `system_oauth` | Internal OAuth token | Enterprise SSO |
| `session` | Cookie-based session | Internal providers |
| `none` | Tanpa autentikasi | Local vLLM without auth |

**Indeks:**
```sql
CREATE INDEX idx_providers_active ON providers(is_active);
```

#### 4.2.4 Tabel `files`

Metadata file yang diupload untuk RAG.

```sql
CREATE TABLE files (
    id               UUID PRIMARY KEY,
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename         TEXT NOT NULL,
    content_type     TEXT NOT NULL,
    file_path        TEXT NOT NULL,
    collection_name  TEXT NOT NULL,
    chunk_count      INTEGER DEFAULT 0,
    size_bytes       BIGINT DEFAULT 0,
    created_at       BIGINT NOT NULL
);
```

| Kolom | Tipe | Constraint | Deskripsi |
|---|---|---|---|
| `id` | UUID | PK | Identifier unik file |
| `user_id` | UUID | FK → users.id, CASCADE | Pemilik file |
| `filename` | TEXT | NOT NULL | Nama asli file |
| `content_type` | TEXT | NOT NULL | MIME type |
| `file_path` | TEXT | NOT NULL | Path ke storage (S3/local) |
| `collection_name` | TEXT | NOT NULL | Nama koleksi pgvector |
| `chunk_count` | INTEGER | DEFAULT 0 | Jumlah chunks yang diindex |
| `size_bytes` | BIGINT | DEFAULT 0 | Ukuran file dalam byte |
| `created_at` | BIGINT | NOT NULL | Unix timestamp |

**Indeks:**
```sql
CREATE INDEX idx_files_user ON files(user_id, created_at DESC);
```

#### 4.2.5 Tabel `app_config` (PersistentConfig)

Menyimpan konfigurasi runtime yang bisa diubah tanpa restart.

```sql
CREATE TABLE app_config (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_path TEXT UNIQUE NOT NULL,
    value       JSONB NOT NULL,
    updated_at  BIGINT NOT NULL
);
```

| Kolom | Tipe | Constraint | Deskripsi |
|---|---|---|---|
| `id` | UUID | PK | Identifier unik |
| `config_path` | TEXT | UNIQUE, NOT NULL | Path konfigurasi (contoh: "rag.chunk_size") |
| `value` | JSONB | NOT NULL | Nilai konfigurasi |
| `updated_at` | BIGINT | NOT NULL | Unix timestamp |

**Contoh konfigurasi:**

| config_path | Tipe Nilai | Default | Deskripsi |
|---|---|---|---|
| `rag.chunk_size` | integer | 1500 | Ukuran chunk untuk RAG |
| `rag.chunk_overlap` | integer | 100 | Overlap antar chunk |
| `rag.top_k` | integer | 5 | Jumlah chunks yang diretrieval |
| `rag.threshold` | float | 0.3 | Threshold relevansi similarity |
| `rag.embedding_model` | string | "text-embedding-3-small" | Model embedding |
| `rag.query_gen` | boolean | true | Generate retrieval query via LLM |
| `rag.reranking` | boolean | false | Reranking via cross-encoder |
| `websearch.enabled` | boolean | false | Aktifkan web search |
| `websearch.engine` | string | "duckduckgo" | Provider search |
| `websearch.count` | integer | 5 | Jumlah hasil search |
| `websearch.extract` | boolean | true | Ekstrak konten halaman web |
| `tasks.model` | string | "" | Model untuk tugas background |
| `tasks.title_prompt` | string | (prompt) | Prompt generate judul |
| `tasks.title_gen` | boolean | true | Aktifkan generate judul |
| `tasks.tag_gen` | boolean | true | Aktifkan generate tag |
| `features.image_gen` | boolean | false | Aktifkan image generation |
| `features.code_interpreter` | boolean | false | Aktifkan code interpreter |
| `features.memory` | boolean | false | Aktifkan memory |

---

### 4.3 pgvector Schema

```sql
-- Aktifkan extension pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Tabel vector store (shared collection)
CREATE TABLE vector_store (
    id              TEXT PRIMARY KEY,
    collection_name TEXT NOT NULL,
    content         TEXT NOT NULL,
    embedding       VECTOR(1536),
    metadata        JSONB DEFAULT '{}',
    created_at      BIGINT NOT NULL
);

-- Index IVFFlat untuk similarity search
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

**Dimensi Embedding yang Didukung:**

| Model | Dimensi | Config |
|---|---|---|
| `text-embedding-3-small` | 1536 | Default |
| `text-embedding-3-large` | 3072 | Config VECTOR(n) |
| `bge-large` (local) | 1024 | Config VECTOR(n) |
| `nomic-embed-text` | 768 | Config VECTOR(n) |

---

## 5. API Endpoints

### 5.1 Ringkasan Endpoint

```
Authentication:
  POST   /auth/login                 # Login dengan email & password
  POST   /auth/logout                # Logout (invalidate token)
  POST   /auth/refresh               # Refresh access token
  GET    /auth/me                    # Get current user profile
  POST   /auth/register              # Register user baru
  PUT    /auth/me/password           # Ganti password

Provider Management:
  GET    /api/providers              # List semua provider
  POST   /api/providers              # Tambah provider baru
  GET    /api/providers/{id}         # Detail provider
  PUT    /api/providers/{id}         # Update provider
  DELETE /api/providers/{id}         # Hapus provider
  POST   /api/providers/{id}/test    # Test koneksi ke provider

Models:
  GET    /api/models                 # Aggregated list dari semua provider
  POST   /api/models/refresh         # Force refresh cache model list
  GET    /api/models/{id}            # Detail model spesifik

Chat Completion (UTAMA):
  POST   /api/chat/completions       # SSE streaming, full pipeline

Chat History:
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

Files & RAG:
  POST   /api/files/upload           # Upload file (multipart/form-data)
  GET    /api/files                  # List file milik user
  GET    /api/files/{id}             # Get file metadata
  DELETE /api/files/{id}             # Hapus file + koleksi vector

Web Search (test/manual):
  POST   /api/retrieval/web/search   # Manual web search

Background Tasks:
  POST   /api/tasks/title            # Manual generate title
  POST   /api/tasks/tags             # Manual generate tags

Admin Only:
  GET    /api/admin/users            # List users
  POST   /api/admin/users            # Buat user
  PUT    /api/admin/users/{id}       # Update user
  DELETE /api/admin/users/{id}       # Hapus user
  GET    /api/admin/config           # Get all PersistentConfig
  PUT    /api/admin/config           # Update PersistentConfig

Health & Monitoring:
  GET    /health                     # Health check
  GET    /metrics                    # Prometheus metrics
```

### 5.2 Detail Request/Response Format

#### 5.2.1 Authentication

**POST /auth/login**

Request:
```json
{
  "email": "user@example.com",
  "password": "secure-password-here"
}
```

Response `200 OK`:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "name": "John Doe",
    "role": "user",
    "is_active": true,
    "settings": {}
  }
}
```

Response `401 Unauthorized`:
```json
{
  "detail": "Email atau password salah"
}
```

**POST /auth/refresh**

Request:
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

Response `200 OK`:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": { ... }
}
```

**GET /auth/me**

Headers: `Authorization: Bearer <token>`

Response `200 OK`:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "name": "John Doe",
  "role": "user",
  "is_active": true,
  "settings": {}
}
```

#### 5.2.2 Chat Completion (Entry Point Utama)

**POST /api/chat/completions**

Headers: `Authorization: Bearer <jwt>`

Request:
```json
{
  "model": "gpt-4o",
  "messages": [
    {"role": "system", "content": "Kamu adalah asisten AI yang membantu."},
    {"role": "user", "content": "Halo, apa kamu bisa membantu saya?"}
  ],
  "stream": true,
  "files": [
    {"type": "file", "id": "file-uuid-1"}
  ],
  "web_search": false,
  "temperature": 0.7,
  "max_tokens": 2048,
  "top_p": 1.0,
  "frequency_penalty": 0.0,
  "presence_penalty": 0.0
}
```

Response `200 OK` — SSE Streaming:
```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no

data: {"type":"status","data":{"description":"Mengambil konteks dari dokumen...","done":false}}

data: {"type":"status","data":{"description":"Mencari di web...","done":false}}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1717200000,"model":"gpt-4o","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1717200000,"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"Halo!"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1717200000,"model":"gpt-4o","choices":[{"index":0,"delta":{"content":" Tentu"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1717200000,"model":"gpt-4o","choices":[{"index":0,"delta":{"content":" bisa"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1717200000,"model":"gpt-4o","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

Error Response `422 Unprocessable Entity`:
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "messages"],
      "msg": "Field required"
    }
  ]
}
```

Error Response `503 Provider Error`:
```json
{
  "error": {
    "code": 503,
    "message": "Provider connection error: Connection refused",
    "type": "provider_error"
  }
}
```

#### 5.2.3 Chat History

**GET /api/chats**

Headers: `Authorization: Bearer <jwt>`

Query Parameters:
| Parameter | Tipe | Default | Deskripsi |
|---|---|---|---|
| `page` | integer | 1 | Halaman |
| `limit` | integer | 60 | Jumlah per halaman |
| `archived` | boolean | false | Tampilkan arsip |

Response `200 OK`:
```json
{
  "data": [
    {
      "id": "chat-uuid-1",
      "title": "Diskusi tentang AI",
      "model_id": "gpt-4o",
      "is_pinned": false,
      "updated_at": 1717200000000,
      "folder_id": null
    },
    {
      "id": "chat-uuid-2",
      "title": "Pembuatan Website",
      "model_id": "claude-3-opus",
      "is_pinned": true,
      "updated_at": 1717199000000,
      "folder_id": null
    }
  ],
  "total": 150,
  "page": 1,
  "has_more": true
}
```

**POST /api/chats**

Request:
```json
{
  "title": "Diskusi Baru",
  "model": "gpt-4o"
}
```

Response `201 Created`:
```json
{
  "id": "chat-uuid-new",
  "title": "Diskusi Baru",
  "model_id": "gpt-4o",
  "is_pinned": false,
  "updated_at": 1717200000000,
  "folder_id": null
}
```

**GET /api/chats/{id}**

Response `200 OK`:
```json
{
  "id": "chat-uuid-1",
  "title": "Diskusi tentang AI",
  "model_id": "gpt-4o",
  "is_pinned": false,
  "is_archived": false,
  "updated_at": 1717200000000,
  "folder_id": null,
  "messages": [
    {
      "id": "msg-1",
      "role": "user",
      "content": "Apa itu AI?",
      "timestamp": 1717199000000,
      "files": [],
      "web_search": false
    },
    {
      "id": "msg-2",
      "role": "assistant",
      "content": "AI adalah...",
      "tool_calls": null,
      "done": true,
      "stopped": false,
      "usage": {
        "prompt_tokens": 10,
        "completion_tokens": 25,
        "total_tokens": 35
      },
      "timestamp": 1717199001000
    }
  ],
  "tags": ["teknologi", "ai"]
}
```

**PUT /api/chats/{id}**

Request:
```json
{
  "title": "Judul Baru",
  "is_pinned": true,
  "tags": ["ai", "machine-learning"]
}
```

Response `200 OK`:
```json
{
  "id": "chat-uuid-1",
  "title": "Judul Baru",
  "is_pinned": true,
  "tags": ["ai", "machine-learning"],
  "updated_at": 1717200100000
}
```

#### 5.2.4 File Upload

**POST /api/files/upload**

Headers:
- `Authorization: Bearer <jwt>`
- `Content-Type: multipart/form-data`

Form Data:
| Field | Tipe | Deskripsi |
|---|---|---|
| `file` | file | File yang diupload |

Response `200 OK`:
```json
{
  "id": "file-uuid-1",
  "filename": "dokumen-ai.pdf",
  "collection_name": "col_550e8400e29b41d4a716446655440000",
  "size": 1048576,
  "chunk_count": 15,
  "created_at": 1717200000000
}
```

Error Response `415 Unsupported Media Type`:
```json
{
  "detail": "Tipe file tidak didukung: application/octet-stream"
}
```

Error Response `413 Payload Too Large`:
```json
{
  "detail": "File terlalu besar (max 50MB)"
}
```

**GET /api/files**

Response `200 OK`:
```json
{
  "data": [
    {
      "id": "file-uuid-1",
      "filename": "dokumen-ai.pdf",
      "content_type": "application/pdf",
      "size": 1048576,
      "chunk_count": 15,
      "collection_name": "col_550e8400e29b41d4a716446655440000",
      "created_at": 1717200000000
    }
  ]
}
```

#### 5.2.5 Provider Management

**POST /api/providers**

Request:
```json
{
  "name": "OpenAI",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-your-api-key-here",
  "auth_type": "bearer",
  "prefix": "oai",
  "is_active": true,
  "extra_headers": {}
}
```

Response `201 Created`:
```json
{
  "id": "provider-uuid-1",
  "name": "OpenAI",
  "base_url": "https://api.openai.com/v1",
  "api_key": "****",
  "auth_type": "bearer",
  "prefix": "oai",
  "is_active": true,
  "extra_config": {},
  "created_at": 1717200000000,
  "updated_at": 1717200000000
}
```

**POST /api/providers/{id}/test**

Response `200 OK`:
```json
{
  "success": true,
  "message": "Koneksi berhasil",
  "response_time_ms": 245
}
```

Response `502 Bad Gateway`:
```json
{
  "success": false,
  "message": "Koneksi gagal: Connection refused",
  "response_time_ms": 5000
}
```

#### 5.2.6 Models

**GET /api/models**

Headers: `Authorization: Bearer <jwt>`

Response `200 OK`:
```json
{
  "data": [
    {
      "id": "oai.gpt-4o",
      "name": "GPT-4 Optimized",
      "description": "Model paling capable dari OpenAI",
      "provider": "OpenAI",
      "capabilities": {
        "vision": true,
        "tools": true,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"]
      },
      "context_length": 128000,
      "params": {
        "temperature": 1.0,
        "max_tokens": 4096,
        "top_p": 1.0
      },
      "tags": ["vision", "tools", "recommended"]
    },
    {
      "id": "local.llama-3.1-70b",
      "name": "Llama 3.1 70B",
      "description": "Model open-source dari Meta",
      "provider": "Local vLLM",
      "capabilities": {
        "vision": false,
        "tools": true,
        "input_modalities": ["text"],
        "output_modalities": ["text"]
      },
      "context_length": 128000,
      "params": {
        "temperature": 0.7,
        "max_tokens": 8192,
        "top_p": 0.9
      },
      "tags": ["open-source", "local"]
    }
  ]
}
```

#### 5.2.7 Web Search

**POST /api/retrieval/web/search**

Request:
```json
{
  "query": "AI terbaru 2024",
  "engine": "duckduckgo",
  "count": 5
}
```

Response `200 OK`:
```json
{
  "results": [
    {
      "title": "Perkembangan AI di Tahun 2024",
      "url": "https://example.com/ai-2024",
      "snippet": "Tinjauan lengkap tentang perkembangan AI..."
    },
    {
      "title": "Modell AI Terbaru",
      "url": "https://example.com/model-ai",
      "snippet": "Daftar model AI terbaru dari berbagai provider..."
    }
  ]
}
```

---

## 6. Module Responsibilities

### 6.1 Routers (`routers/`)

| Module | Fungsi | Dependencies |
|---|---|---|
| [`auth.py`](routers/auth.py) | Login, logout, refresh, me, register, change password | `utils/auth.py`, `models/users.py` |
| [`chat.py`](routers/chat.py) | Entry point chat completion (SSE streaming) | `utils/chat.py`, `utils/streaming.py` |
| [`chats.py`](routers/chats.py) | CRUD chat history, archive, pin, messages | `models/chats.py` |
| [`models.py`](routers/models.py) | List, refresh, detail model aggregation | `utils/models.py` |
| [`providers.py`](routers/providers.py) | CRUD provider, test connection | `models/providers.py` |
| [`files.py`](routers/files.py) | Upload, list, delete files | `utils/middleware.py` (RAG) |
| [`retrieval.py`](routers/retrieval.py) | Web search, RAG search endpoints | `retrieval/web/*.py` |
| [`tasks.py`](routers/tasks.py) | Manual title & tag generation | `utils/task.py` |

### 6.2 Utilities (`utils/`)

| Module | Fungsi | Fungsi Utama |
|---|---|---|
| [`chat.py`](utils/chat.py) | Orchestrator utama chat completion | `generate_chat_completion()`, `_stream_generator()`, `_save_completion_to_db()` |
| [`middleware.py`](utils/middleware.py) | Preprocessing pipeline | `process_chat_payload()`, `execute_tool_calling_loop()`, `chat_completion_files_handler()`, `chat_completion_web_search_handler()` |
| [`payload.py`](utils/payload.py) | Transformasi payload | `apply_system_prompt_to_body()`, `apply_model_params_to_body()`, `strip_unsupported_params()` |
| [`filter.py`](utils/filter.py) | Filter pipeline | `process_filter_functions()` |
| [`tools.py`](utils/tools.py) | Tool discovery & execution | `prepare_tools_for_request()`, `_execute_single_tool()` |
| [`task.py`](utils/task.py) | Background task utilities | `generate_chat_title()`, `generate_chat_tags()`, `_run_post_completion_tasks()` |
| [`models.py`](utils/models.py) | Model aggregation | `get_all_models()`, `_fetch_models_from_provider()` |
| [`auth.py`](utils/auth.py) | JWT utilities | `create_access_token()`, `create_refresh_token()`, `get_verified_user()` |
| [`streaming.py`](utils/streaming.py) | SSE helpers | `create_event_emitter()`, SSE event formatters |

### 6.3 ORM Models (`models/`)

| Module | Table | Fungsi Utama |
|---|---|---|
| [`users.py`](models/users.py) | `users` | CRUD user, password hash, get by email/id |
| [`chats.py`](models/chats.py) | `chats` | Create chat, get list paginated, upsert message, update title |
| [`files.py`](models/files.py) | `files` | Create file metadata, get by user, delete + vector collection |
| [`providers.py`](models/providers.py) | `providers` | CRUD provider, get active, test connection |
| [`config.py`](models/config.py) | `app_config` | Get/set config values |

### 6.4 Retrieval (`retrieval/`)

| Module | Fungsi |
|---|---|
| `vector/pgvector.py` | pgvector adapter (upsert, similarity search, delete collection) |
| `vector/base.py` | Abstract base class untuk vector store |
| `web/searxng.py` | SearXNG search provider |
| `web/brave.py` | Brave Search provider |
| `web/tavily.py` | Tavily Search provider |
| `web/duckduckgo.py` | DuckDuckGo search provider |
| `web/utils.py` | Content extraction dari URL (BeautifulSoup, Playwright) |
| `loaders/pdf.py` | PDF text extraction |
| `loaders/docx.py` | DOCX text extraction |
| `loaders/text.py` | Plain text file processing |
| `loaders/image.py` | OCR via tesseract/paddleocr |
| `utils.py` | Chunking, embedding utilities |

---

## 7. Data Flow Diagrams

### 7.1 Chat Completion Flow (Utama)

```mermaid
sequenceDiagram
    participant Client as Flutter Client
    participant Router as routers/chat.py
    participant Orchestrator as utils/chat.py
    participant Pipeline as utils/middleware.py
    participant Provider as AI Provider
    participant DB as PostgreSQL
    participant Vector as pgvector
    participant Storage as S3/Local

    Client->>Router: POST /api/chat/completions<br/>+ JWT + body
    Router->>Router: Validate JWT
    Router->>Orchestrator: generate_chat_completion()

    Orchestrator->>Orchestrator: [1] Validate user & model access
    Orchestrator->>Orchestrator: [2] Apply model params

    Orchestrator->>Pipeline: process_chat_payload()
    Pipeline->>Pipeline: [3] Apply system prompt & model params
    Pipeline->>Pipeline: [4] Process filter functions (inlet)

    alt Ada files (RAG)
        Pipeline->>Vector: Query embeddings
        Vector-->>Pipeline: Return relevant chunks
        Pipeline->>Pipeline: Inject context to messages
    end

    alt Web search enabled
        Pipeline->>Provider: Search API call
        Provider-->>Pipeline: Search results
        Pipeline->>Storage: Fetch web content (optional)
        Storage-->>Pipeline: Page content
        Pipeline->>Pipeline: Inject search context
    end

    Pipeline->>Pipeline: [5] Inject tool specs
    Pipeline->>Pipeline: [6] Strip unsupported params
    Pipeline-->>Orchestrator: Preprocessed body

    Orchestrator->>Provider: POST /chat/completions (SSE stream)
    Provider-->>Orchestrator: SSE stream chunks

    loop Tool Calling
        Orchestrator->>Orchestrator: Check finish_reason
        alt tool_calls
            Orchestrator->>Orchestrator: Execute tools (parallel)
            Orchestrator->>Provider: Re-send with tool results
            Provider-->>Orchestrator: New stream
        end
    end

    Orchestrator->>DB: Save completion (JSONB update)
    Orchestrator-->>Client: SSE stream chunks

    Orchestrator->>Orchestrator: Background: title & tag generation
```

### 7.2 File Upload & RAG Pipeline Flow

```mermaid
sequenceDiagram
    participant Client as Flutter Client
    participant Router as routers/files.py
    participant Pipeline as RAG Pipeline
    participant Storage as S3/Local
    participant Vector as pgvector
    participant DB as PostgreSQL

    Client->>Router: POST /api/files/upload (multipart)
    Router->>Router: Validate JWT, file type, size
    Router->>Storage: Save file content
    Storage-->>Router: file_path

    Router->>Pipeline: extract_text(file_path, content_type)
    alt PDF
        Pipeline->>Pipeline: pypdf extraction
    else DOCX
        Pipeline->>Pipeline: python-docx extraction
    else Text
        Pipeline->>Pipeline: Direct read
    else Image
        Pipeline->>Pipeline: OCR (tesseract/paddleocr)
    end
    Pipeline-->>Router: extracted text

    Router->>Pipeline: chunk_text(text)
    Pipeline-->>Router: chunks list

    Router->>Pipeline: generate_embeddings_batch(chunk texts)
    Pipeline-->>Router: embeddings list

    Router->>Vector: upsert_collection(collection_name, documents)
    Vector-->>Router: indexed

    Router->>DB: create_file_metadata()
    DB-->>Router: file record
    Router-->>Client: FileResponse { id, filename, collection_name }
```

### 7.3 SSE Streaming & Disconnect Detection

```mermaid
sequenceDiagram
    participant Client as Flutter Client
    participant FastAPI as FastAPI Server
    participant Provider as AI Provider

    Client->>FastAPI: POST /api/chat/completions<br/>+ CancelToken
    FastAPI->>Provider: POST /chat/completions (stream)
    
    loop Streaming
        Provider-->>FastAPI: SSE chunk
        FastAPI->>FastAPI: request.is_disconnected()?
        
        alt Not disconnected
            FastAPI-->>Client: Forward SSE chunk
            FastAPI->>FastAPI: Accumulate content
        else Disconnected (Stop clicked)
            FastAPI->>Provider: Close connection
            Note over FastAPI,Provider: Provider stops generating
            FastAPI->>FastAPI: Save partial content to DB
            FastAPI-->>Client: Final partial content
        end
    end
```

### 7.4 Tool Calling Loop

```mermaid
flowchart TD
    A[Start Tool Loop] --> B{finish_reason == stop?}
    B -->|Yes| C[End - Return Final Response]
    B -->|No, tool_calls| D[Accumulate Tool Calls]
    D --> E{iteration > MAX_TOOL_CALL_ITERATIONS?}
    E -->|Yes| F[Error: Max tool call iterations reached]
    E -->|No| G[Emit Status to Flutter]
    G --> H[Execute Tools in Parallel]
    H --> I[Collect Tool Results]
    I --> J[Append assistant message + tool results to history]
    J --> K[Send to Provider Again]
    K --> B
```

---

## 8. Konfigurasi & Environment Variables

### 8.1 env.py — Pydantic Settings

File [`env.py`](env.py) mendefinisikan semua environment variables menggunakan `pydantic-settings`:

```python
# env.py — Skema konfigurasi
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    # Core
    secret_key: str = Field(..., min_length=32)
    database_url: str
    environment: str = "production"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4
    log_level: str = "info"

    # Auth
    enable_signup: bool = False
    access_token_expire_minutes: int = 10080  # 7 hari
    allowed_cors_origins: list[str] = ["*"]

    # Embedding
    embedding_engine: str = "openai"  # openai | ollama | local
    rag_embedding_model: str = "text-embedding-3-small"

    # Chunking (PersistentConfig - bisa dioverride via Admin UI)
    chunk_size: int = 1500
    chunk_overlap: int = 100
    rag_top_k: int = 5
    rag_relevance_threshold: float = 0.3

    # Web Search
    enable_web_search: bool = False
    web_search_engine: str = "duckduckgo"
    search_result_count: int = 5
    enable_web_content_extraction: bool = True

    # File Storage
    storage_provider: str = "local"  # local | s3
    upload_dir: str = "/app/uploads"
    aws_s3_bucket_name: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "ap-southeast-1"

    # Task Model
    task_model: str = ""
    enable_title_generation: bool = True
    enable_tag_generation: bool = True

    # Redis (opsional)
    redis_url: str = "redis://localhost:6379/0"

    # Monitoring
    enable_metrics: bool = True
    sentry_dsn: str = ""
```

### 8.2 Environment Variables Reference

```bash
# ── Core ────────────────────────────────────────────────────────
SECRET_KEY=<min-32-char-random-string>      # JWT signing key — WAJIB
DATABASE_URL=postgresql+asyncpg://user:pass@host/dbname
ENVIRONMENT=production                       # production | development

# ── Server ──────────────────────────────────────────────────────
HOST=0.0.0.0
PORT=8000
WORKERS=4
LOG_LEVEL=info

# ── Auth ────────────────────────────────────────────────────────
ENABLE_SIGNUP=false
ACCESS_TOKEN_EXPIRE_MINUTES=10080           # 7 hari
ALLOWED_CORS_ORIGINS=*

# ── Embedding ──────────────────────────────────────────────────
EMBEDDING_ENGINE=openai                     # openai | ollama | local
RAG_EMBEDDING_MODEL=text-embedding-3-small

# ── Chunking (bisa di-override via Admin UI) ───────────────────
CHUNK_SIZE=1500
CHUNK_OVERLAP=100
RAG_TOP_K=5
RAG_RELEVANCE_THRESHOLD=0.3

# ── Web Search ─────────────────────────────────────────────────
ENABLE_WEB_SEARCH=false
WEB_SEARCH_ENGINE=duckduckgo
BRAVE_SEARCH_API_KEY=
TAVILY_API_KEY=
SEARXNG_QUERY_URL=

# ── File Storage ───────────────────────────────────────────────
STORAGE_PROVIDER=local                      # local | s3
UPLOAD_DIR=/app/uploads
AWS_S3_BUCKET_NAME=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=ap-southeast-1

# ── Task Model ─────────────────────────────────────────────────
TASK_MODEL=
ENABLE_TITLE_GENERATION=true
ENABLE_TAG_GENERATION=true

# ── Redis (opsional) ───────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0

# ── Monitoring ─────────────────────────────────────────────────
ENABLE_METRICS=true
SENTRY_DSN=
```

---

## 9. Error Handling Strategy

### 9.1 Error Code Constants

File [`constants.py`](constants.py) mendefinisikan semua error codes terstruktur:

```python
# Error Categories
ERROR_CODES = {
    # Auth Errors (A001-A099)
    "INVALID_CREDENTIALS":      {"code": "A001", "status": 401, "message": "Email atau password salah"},
    "INVALID_TOKEN":            {"code": "A002", "status": 401, "message": "Token tidak valid"},
    "TOKEN_EXPIRED":            {"code": "A003", "status": 401, "message": "Token telah kadaluarsa"},
    "ACCOUNT_DISABLED":         {"code": "A004", "status": 403, "message": "Akun dinonaktifkan"},
    "USER_NOT_FOUND":           {"code": "A005", "status": 404, "message": "User tidak ditemukan"},

    # Validation Errors (V001-V099)
    "FILE_TYPE_NOT_SUPPORTED":  {"code": "V001", "status": 415, "message": "Tipe file tidak didukung"},
    "FILE_TOO_LARGE":           {"code": "V002", "status": 413, "message": "File terlalu besar (max 50MB)"},
    "NO_TEXT_EXTRACTED":        {"code": "V003", "status": 422, "message": "File tidak mengandung teks yang dapat diproses"},
    "INVALID_MESSAGE_FORMAT":   {"code": "V004", "status": 422, "message": "Format pesan tidak valid"},

    # Provider Errors (P001-P099)
    "PROVIDER_CONNECTION_FAILED": {"code": "P001", "status": 503, "message": "Provider tidak dapat dihubungi"},
    "PROVIDER_RATE_LIMITED":    {"code": "P002", "status": 429, "message": "Provider rate limit tercapai"},
    "PROVIDER_ERROR":           {"code": "P003", "status": 503, "message": "Error dari provider AI"},

    # RAG Errors (R001-R099)
    "RAG_INDEXING_FAILED":      {"code": "R001", "status": 500, "message": "Gagal mengindex dokumen"},
    "EMBEDDING_GENERATION_FAILED": {"code": "R002", "status": 500, "message": "Gagal generate embedding"},

    # System Errors (S001-S099)
    "INTERNAL_ERROR":           {"code": "S001", "status": 500, "message": "Terjadi kesalahan internal"},
    "SERVICE_UNAVAILABLE":      {"code": "S002", "status": 503, "message": "Layanan sedang tidak tersedia"},
}
```

### 9.2 Error Handling Patterns

**Pattern 1: HTTP Exception di Router**
```python
# routers/files.py
@router.post("/api/files/upload")
async def upload_file(file: UploadFile = File(...)):
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=415,
            detail=ERROR_CODES["FILE_TYPE_NOT_SUPPORTED"]["message"]
        )
```

**Pattern 2: Error dari Streaming Response**
```python
# utils/chat.py — Error dalam stream
def _format_sse_error(status_code: int, message: str) -> str:
    error = {
        "error": {
            "code": status_code,
            "message": message,
            "type": "provider_error",
        }
    }
    return f"data: {json.dumps(error)}\n\n"
```

**Pattern 3: Graceful Failover di Pipeline**
```python
# utils/middleware.py — Filter error tidak menghentikan pipeline
try:
    result = await filter_func["inlet"](body=body, user=user)
except Exception as e:
    log.error(f"Filter '{filter_func.get('name')}' error: {e}")
    # JANGAN hentikan pipeline karena satu filter gagal
    continue
```

### 9.3 Global Exception Handler

```python
# main.py
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(
        "Unhandled exception",
        path=request.url.path,
        error=str(exc),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "S001",
                "message": "Terjadi kesalahan internal",
            }
        }
    )
```

---

## 10. Security Considerations

### 10.1 Auth & Token Security

| Kontrol | Implementasi |
|---|---|
| **JWT Secret Key** | Minimal 32 karakter, random, dari environment variable |
| **Access Token Expire** | 7 hari (10080 menit) |
| **Refresh Token Expire** | 30 hari |
| **Password Hashing** | bcrypt dengan cost factor 12 (passlib) |
| **Timing Attack Prevention** | Delay 0.5 detik pada login gagal |
| **Token Validation** | Type check (`access` vs `refresh`) pada setiap request |

### 10.2 Input Validation

| Input | Validasi |
|---|---|
| **File Upload** | Whitelist MIME type, max 50MB, sanitasi nama file |
| **Messages** | Batas panjang pesan, validasi format (role + content) |
| **Request Body** | Pydantic model untuk semua endpoint |
| **Path Traversal** | Sanitasi semua input yang digunakan untuk file path |

### 10.3 API Security

| Kontrol | Implementasi |
|---|---|
| **CORS** | Konfigurasi eksplisit (bukan `*` di produksi) |
| **HTTPS** | TLS termination di load balancer |
| **Rate Limiting** | 5/min untuk login, 60/min untuk chat |
| **SSE Timeout** | 5 menit max streaming |
| **DB Connection** | SSL di produksi |

### 10.4 Data Protection

| Data | Proteksi |
|---|---|
| **API Key Provider** | Dienkripsi di aplikasi, tidak plain text |
| **Logging** | Tidak mengandung API key atau token |
| **Error Logs** | API key di-mask di log |

### 10.5 Security Checklist

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
```

---

## 11. Monitoring & Logging

### 11.1 Structured Logging (structlog)

```python
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

# Contoh penggunaan:
log.info(
    "chat_completion_started",
    chat_id=chat_id,
    model=model_id,
    user_id=user.id,
    has_files=bool(file_ids),
    web_search=web_search_mode,
)
```

**Format Output JSON:**
```json
{
  "event": "chat_completion_started",
  "chat_id": "chat-uuid-1",
  "model": "gpt-4o",
  "user_id": "user-uuid-1",
  "has_files": true,
  "web_search": false,
  "timestamp": "2025-06-01T12:00:00.000000Z",
  "level": "info"
}
```

### 11.2 Prometheus Metrics

**Built-in Metrics (Instrumentator):**
- `http_requests_total` — Total request per endpoint/method/status
- `http_request_duration_seconds` — Request duration histogram
- `http_request_size_bytes` — Request size histogram
- `http_response_size_bytes` — Response size histogram

**Custom Metrics:**

```python
from prometheus_client import Counter, Histogram

# Chat requests counter
chat_requests_total = Counter(
    "chat_requests_total",
    "Total chat completion requests",
    ["model", "user_role", "has_files"],
)

# Streaming duration histogram
streaming_duration_seconds = Histogram(
    "streaming_duration_seconds",
    "Duration of SSE streaming in seconds",
    ["model"],
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

# RAG chunks retrieved histogram
rag_chunks_retrieved = Histogram(
    "rag_chunks_retrieved",
    "Number of RAG chunks retrieved per request",
    buckets=[0, 1, 2, 5, 10, 20],
)
```

### 11.3 Health Check Endpoint

```python
@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    health = {"status": "healthy", "timestamp": time.time()}

    # Check database
    try:
        await db.execute(text("SELECT 1"))
        health["database"] = "connected"
    except Exception as e:
        health["database"] = f"error: {str(e)}"
        health["status"] = "degraded"

    return health
```

---

## 12. Deployment Architecture

### 12.1 AWS Architecture

```mermaid
graph TB
    subgraph Internet
        CF[CloudFront CDN]
    end

    subgraph VPC["AWS VPC"]
        subgraph PublicSubnet
            ALB[Application Load Balancer]
        end

        subgraph PrivateSubnet
            subgraph ECS["ECS Cluster (Auto Scaling)"]
                API[FastAPI Service<br/>2-10 instances]
            end
        end

        subgraph DataTier
            RDS[(RDS PostgreSQL<br/>Multi-AZ<br/>+ pgvector)]
            ELASTI[(ElastiCache Redis<br/>Single-AZ)]
            S3[(S3 Bucket<br/>File Storage)]
        end
    end

    subgraph External
        OPENAI[OpenAI / vLLM APIs]
        SEARCH[Search APIs]
    end

    CF --> ALB
    ALB --> API
    API --> RDS
    API --> ELASTI
    API --> S3
    API --> OPENAI
    API --> SEARCH
```

### 12.2 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### 12.3 Nginx Configuration (SSE Critical)

```nginx
upstream fastapi {
    server backend:8000;
}

server {
    listen 443 ssl;
    server_name api.example.com;

    # SSE Endpoint — KRITIS untuk streaming
    location /api/chat/completions {
        proxy_pass http://fastapi;
        proxy_http_version 1.1;

        # Disable buffering untuk SSE
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;    # 5 menit
        proxy_send_timeout 300s;

        # SSE headers
        add_header Cache-Control no-cache;
        add_header X-Accel-Buffering no;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Authorization $http_authorization;
    }

    # Semua endpoint lain
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

## Appendix A: Request Preprocessing Pipeline — Urutan Eksekusi

Pipeline ini adalah jantung dari setiap chat request. Urutan eksekusi **tidak boleh diubah**:

| Langkah | Fungsi | File | Deskripsi |
|---|---|---|---|
| 1 | `apply_system_prompt_to_body()` | `utils/payload.py` | Inject system prompt (chat-level > model-default > global) |
| 2 | `apply_model_params_to_body()` | `utils/payload.py` | Apply temperature, max_tokens, top_p, dll |
| 3 | `process_filter_functions()` | `utils/filter.py` | Jalankan filter inlet (admin-configured) |
| 4 | `chat_completion_files_handler()` | `utils/middleware.py` | RAG: retrieve chunks & inject context |
| 5 | `chat_completion_web_search_handler()` | `utils/middleware.py` | Web search: query & inject results |
| 6 | `chat_completion_memory_handler()` | `utils/middleware.py` | Memory injection (jika aktif) |
| 7 | `prepare_tools_for_request()` | `utils/tools.py` | Inject tool specs ke messages |
| 8 | `strip_unsupported_params()` | `utils/payload.py` | Hapus parameter yang tidak didukung model |

## Appendix B: SSE Event Types

| Type | Deskripsi | Sender |
|---|---|---|
| `status` | Status banner ke Flutter (progress) | Pipeline (RAG, Web Search, Tools) |
| `citation` | Citation context untuk Flutter | RAG Pipeline |
| `chat.completion.chunk` | AI response chunk | `_stream_generator()` |
| `error` | Error event | `_format_sse_error()` |
| `[DONE]` | Stream selesai | `_stream_generator()` |

## Appendix C: Tool Specifications (Built-in)

| Tool | Fungsi | Deskripsi |
|---|---|---|
| `search_web` | Web search | Mencari di web menggunakan configured engine |
| `fetch_url` | Web fetch | Mengambil konten penuh dari URL |
| `execute_code` | Code sandbox | Menjalankan Python code (jika aktif) |
| `generate_image` | Image generation | Generate gambar (jika aktif) |
| `get_current_timestamp` | Timestamp | Mendapatkan waktu saat ini |
| `calculate_timestamp` | Timestamp calc | Menghitung timestamp dari string |

---

*Dokumen arsitektur ini dibuat berdasarkan SRS_Backend_FastAPI.md v1.1.0 dan merupakan panduan implementasi untuk seluruh tim pengembangan. Setiap modul yang diimplementasikan harus mengikuti spesifikasi dalam dokumen ini secara ketat.*
