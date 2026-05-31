# Panduan Setup Altex Backend

Panduan lengkap untuk menyiapkan Altex Backend dari awal hingga berjalan, termasuk cara mengakses WebUI Admin.

---

## Daftar Isi

- [1. Prasyarat](#1-prasyarat)
- [2. Quick Start (One-Click Deploy)](#2-quick-start-one-click-deploy)
- [3. Setup Manual Langkah demi Langkah](#3-setup-manual-langkah-demi-langkah)
- [4. Konfigurasi](#4-konfigurasi)
- [5. Mengakses WebUI](#5-mengakses-webui)
- [6. Mengelola Provider](#6-mengelola-provider)
- [7. Dokumentasi API](#7-dokumentasi-api)
- [8. Troubleshooting](#8-troubleshooting)
- [9. Deployment Produksi](#9-deployment-produksi)

---

## 1. Prasyarat

### 1.1 Kebutuhan Sistem

| Komponen | Versi Minimum | Catatan |
|----------|---------------|---------|
| Python | 3.10+ | Disarankan Python 3.11+ |
| PostgreSQL | 13+ | Dengan ekstensi `pgvector` |
| RAM | 4 GB | 8 GB+ disarankan untuk produksi |
| Disk | 10 GB | Untuk penyimpanan file upload |

### 1.2 Port yang Diperlukan

Pastikan port berikut tersedia dan tidak digunakan oleh aplikasi lain:

| Port | Kegunaan |
|------|----------|
| 8000 | HTTP API Server (utama) |
| 8001 | Alternatif / Development |
| 8002 | Alternatif / Staging |
| 8003 | Alternatif / Testing |

**Cek port yang sedang digunakan:**

```bash
# Linux/macOS
netstat -tlnp | grep -E '800[0-3]'
# atau
lsof -i :8000

# Jika port digunakan, hentikan proses atau ubah konfigurasi
```

### 1.3 Tools yang Diperlukan

Pastikan tools berikut sudah terinstall:

```bash
# Cek versi Python
python3 --version  # Harus 3.10 atau lebih tinggi

# Cek pip
pip3 --version

# Cek git
git --version

# Cek PostgreSQL client (opsional)
psql --version
```

**Instalasi tools (jika belum ada):**

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git postgresql-client

# CentOS/RHEL
sudo dnf install -y python3 python3-pip git postgresql

# macOS (dengan Homebrew)
brew install python3 git postgresql
```

### 1.4 Database PostgreSQL

Pastikan PostgreSQL sudah berjalan dengan ekstensi `pgvector`:

```bash
# Masuk ke PostgreSQL
psql -U postgres -h localhost

# Dalam psql, jalankan:
CREATE EXTENSION IF NOT EXISTS vector;

# Verifikasi ekstensi
\dx vector
```

Jika ekstensi `pgvector` belum ada, instal terlebih dahulu:

```bash
# Ubuntu/Debian
sudo apt install -y postgresql-15-pgvector  # Sesuaikan versi PostgreSQL

# Atau compile dari source
git clone https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
```

---

## 2. Quick Start (One-Click Deploy)

### 2.1 Menggunakan deploy.sh

Script `deploy.sh` menyediakan deployment otomatis dengan satu perintah:

```bash
# Standar deployment
./deploy.sh

# Fresh installation (hapus setup lama)
./deploy.sh --fresh

# Update dan restart
./deploy.sh --update

# Jalankan migrasi database saja
./deploy.sh --migrate

# Lihat log
./deploy.sh --logs

# Cek status service
./deploy.sh --status
```

### 2.2 Apa yang Dilakukan deploy.sh Secara Otomatis

Script `deploy.sh` akan melakukan:

1. **Pengecekan Prasyarat**
   - Memverifikasi Python 3.10+
   - Memeriksa ketersediaan port
   - Memvalidasi koneksi database

2. **Setup Virtual Environment**
   - Membuat `.venv` jika belum ada
   - Mengaktifkan virtual environment

3. **Instalasi Dependencies**
   - Menginstall semua package dari `requirements.txt`
   - Termasuk: FastAPI, SQLAlchemy, asyncpg, dll.

4. **Konfigurasi Environment**
   - Menyalin `.env.example` ke `.env` jika belum ada
   - Memvalidasi variabel yang diperlukan

5. **Migrasi Database**
   - Menjalankan Alembic migrations
   - Membuat tabel yang diperlukan

6. **Membuat Admin Default**
   - Email: `admin@altex.local`
   - Password: `Admin@123456`

7. **Memulai Server**
   - Menjalankan uvicorn di port 8000
   - Atau menginstall sebagai systemd service (opsional)

### 2.3 Output yang Diharapkan

```
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║               Altex Backend Deployment Script                ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Checking prerequisites...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✓ Python version: 3.11.x
✓ PostgreSQL connection successful

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Setting up virtual environment...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✓ Virtual environment created
✓ Dependencies installed

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Running database migrations...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✓ Migrations completed

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Starting server...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✓ Server running at http://0.0.0.0:8000
✓ Admin WebUI: http://0.0.0.0:8000/admin
✓ API Docs: http://0.0.0.0:8000/docs
```

---

## 3. Setup Manual Langkah demi Langkah

Jika Anda lebih memilih setup manual atau ingin memahami setiap langkah:

### 3.1 Clone Repository

```bash
# Clone dari repository
git clone <repository-url> altex-backend
cd altex-backend

# Atau jika sudah ada di lokal
cd backend-altex
```

### 3.2 Buat Virtual Environment

```bash
# Buat virtual environment
python3 -m venv .venv

# Aktifkan virtual environment
# Linux/macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate

# Verifikasi aktivasi
which python  # Harus menunjukkan path ke .venv
python --version
```

### 3.3 Install Dependencies

```bash
# Upgrade pip ke versi terbaru
pip install --upgrade pip

# Install semua dependencies
pip install -r requirements.txt

# Verifikasi instalasi
pip list | grep -E 'fastapi|uvicorn|sqlalchemy|asyncpg'
```

**Dependencies utama:**

| Package | Versi | Kegunaan |
|---------|-------|----------|
| fastapi | 0.111.0 | Web framework |
| uvicorn | 0.30.1 | ASGI server |
| sqlalchemy | 2.0.30 | ORM |
| asyncpg | 0.29.0 | PostgreSQL async driver |
| alembic | 1.13.1 | Database migration |
| python-jose | 3.3.0 | JWT handling |
| bcrypt | 4.1.2 | Password hashing |

### 3.4 Konfigurasi File .env

```bash
# Salin template
cp .env.example .env

# Edit file .env
nano .env
# atau
vim .env
```

**Konfigurasi minimum yang harus diisi:**

```env
# ── REQUIRED ────────────────────────────────────────────────
# Secret key untuk JWT (minimal 32 karakter)
secret_key=your-super-secret-key-min-32-chars-here-change-this

# Database URL
database_url=postgresql+asyncpg://postgres:password@localhost:5432/altex_chat

# ── ADMIN CREDENTIALS ─────────────────────────────────────────
admin_email=admin@altex.local
admin_password=Admin@123456

# ── SERVER ────────────────────────────────────────────────────
host=0.0.0.0
port=8000
```

**Generate secret key yang aman:**

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3.5 Jalankan Migrasi Database

```bash
# Pastikan virtual environment aktif
source .venv/bin/activate

# Jalankan migrasi
alembic upgrade head

# Jika ada error, coba:
alembiccurrent  # Cek versi migrasi saat ini
alembic history  # Lihat riwayat migrasi
```

**Jika migrasi baru pertama kali:**

```bash
# Buat database terlebih dahulu jika belum ada
createdb -U postgres altex_chat

# Jalankan migrasi
alembic upgrade head
```

### 3.6 Jalankan Server

```bash
# Development mode (dengan auto-reload)
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Production mode
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4

# Atau gunakan script
python main.py
```

**Verifikasi server berjalan:**

```bash
# Curl ke health endpoint
curl http://localhost:8000/health

# Atau buka browser ke
# http://localhost:8000/docs
```

---

## 4. Konfigurasi

### 4.1 Variabel Environment Lengkap

File `.env` mendukung konfigurasi berikut:

#### Core Configuration (Required)

```env
# Secret key untuk JWT signing (WAJIB minimal 32 karakter)
secret_key=your-super-secret-key-min-32-chars-here-change-this

# Database URL (WAJIB)
# Format: postgresql+asyncpg://user:password@host:port/database
database_url=postgresql+asyncpg://postgres:password@localhost:5432/altex_chat

# Environment: development, staging, production
environment=development
```

#### Server Configuration

```env
# Host binding
host=0.0.0.0

# Port server
port=8000

# Jumlah worker processes (produksi)
workers=4

# Log level: debug, info, warning, error
log_level=info
```

#### Authentication

```env
# Izinkan registrasi user baru
enable_signup=true

# Durasi access token (menit)
access_token_expire_minutes=10080

# Durasi refresh token (hari)
refresh_token_expire_days=30

# CORS origins (JSON array)
allowed_cors_origins=["*"]
```

#### Admin Credentials

```env
# Email admin default
admin_email=admin@altex.local

# Password admin default
admin_password=Admin@123456
```

#### vLLM / OpenAI Provider

```env
# API key (boleh fake untuk vLLM lokal)
openai_api_key=fake-key-because-vllm-doesnt-verify

# Base URL vLLM endpoint
openai_base_url=http://localhost:8000/v1
```

#### RAG Configuration

```env
# Embedding engine: ollama, openai, sentence-transformers
embedding_engine=ollama

# Model embedding
rag_embedding_model=nomic-embed-text

# Dimensi vector
embedding_dimension=768

# Chunk size untuk RAG
chunk_size=1500

# Chunk overlap
chunk_overlap=100

# Top-K retrieval
rag_top_k=5
```

#### Web Search

```env
# Aktifkan web search
enable_web_search=true

# Engine: tavily, duckduckgo, brave, searxng
web_search_engine=tavily

# Jumlah hasil pencarian
search_result_count=5

# API keys (pilih salah satu)
tavily_api_key=tvly-dev-xxxxx
brave_search_api_key=xxxxx
```

#### File Storage

```env
# Storage provider: local, s3
storage_provider=local

# Direktori upload (local)
upload_dir=/app/uploads

# S3 configuration (jika menggunakan S3)
# aws_s3_bucket_name=your-bucket
# aws_access_key_id=your-key
# aws_secret_access_key=your-secret
# aws_region=ap-southeast-1
```

### 4.2 Konfigurasi Database

**Membuat database baru:**

```sql
-- Masuk ke PostgreSQL
psql -U postgres

-- Buat database
CREATE DATABASE altex_chat;

-- Buat user (opsional)
CREATE USER altex_user WITH PASSWORD 'secure_password';

-- Berikan hak akses
GRANT ALL PRIVILEGES ON DATABASE altex_chat TO altex_user;

-- Aktifkan pgvector
\c altex_chat
CREATE EXTENSION IF NOT EXISTS vector;
```

**Konfigurasi connection string:**

```env
# Format dasar
database_url=postgresql+asyncpg://user:password@host:port/database

# Contoh untuk database lokal
database_url=postgresql+asyncpg://postgres:password@localhost:5432/altex_chat

# Contoh untuk AWS RDS
database_url=postgresql+asyncpg://postgres:password@mydb.xxxx.region.rds.amazonaws.com:5432/altex_chat

# Contoh dengan SSL (produksi)
database_url=postgresql+asyncpg://user:pass@host:5432/db?ssl=require
```

### 4.3 Setup vLLM Provider

vLLM adalah inference server yang kompatibel dengan OpenAI API.

**Menjalankan vLLM server:**

```bash
# Dengan model lokal
python -m vllm.entrypoints.openai.api_server \
    --model meta-llama/Llama-3-8b-chat \
    --host 0.0.0.0 \
    --port 8001

# Atau dengan Docker
docker run --gpus all \
    -v ~/.cache/huggingface:/root/.cache/huggingface \
    -p 8001:8000 \
    --rm \
    vllm/vllm-openai:latest \
    --model meta-llama/Llama-3-8b-chat
```

**Konfigurasi di Altex:**

```env
# URL ke vLLM server
openai_base_url=http://localhost:8001/v1

# API key (boleh arbitrary untuk vLLM lokal)
openai_api_key=fake-key
```

### 4.4 Kredensial Admin Default

| Field | Nilai |
|-------|-------|
| Email | `admin@altex.local` |
| Password | `Admin@123456` |

> ⚠️ **PENTING:** Segera ganti password admin setelah login pertama di environment produksi!

---

## 5. Mengakses WebUI

### 5.1 URL Akses

Setelah server berjalan, akses URL berikut:

| Endpoint | URL | Keterangan |
|----------|-----|------------|
| Admin WebUI | `http://localhost:8000/admin` | Panel admin untuk mengelola sistem |
| API Docs (Swagger) | `http://localhost:8000/docs` | Dokumentasi API interaktif |
| API Docs (ReDoc) | `http://localhost:8000/redoc` | Dokumentasi API alternatif |
| Health Check | `http://localhost:8000/health` | Endpoint kesehatan server |

### 5.2 Login ke Admin Panel

1. Buka browser dan akses `http://localhost:8000/admin`

2. Halaman login akan muncul:
   ```
   ┌────────────────────────────────────────┐
   │           ⚡ Altex Admin               │
   │                                        │
   │   ┌──────────────────────────────────┐ │
   │   │ Email address                    │ │
   │   └──────────────────────────────────┘ │
   │   ┌──────────────────────────────────┐ │
   │   │ Password                         │ │
   │   └──────────────────────────────────┘ │
   │                                        │
   │          [   Sign In   ]               │
   │                                        │
   └────────────────────────────────────────┘
   ```

3. Masukkan kredensial:
   - **Email:** `admin@altex.local`
   - **Password:** `Admin@123456`

4. Klik "Sign In"

### 5.3 Navigasi Admin Panel

Setelah login, Anda akan melihat dashboard dengan menu:

| Menu | Fungsi |
|------|--------|
| **Dashboard** | Overview statistik sistem |
| **Providers** | Kelola AI providers (vLLM, OpenAI, dll) |
| **Models** | Kelola model yang tersedia |
| **Chats** | Lihat riwayat chat pengguna |
| **Users** | Kelola user admin |
| **Settings** | Konfigurasi sistem |

---

## 6. Mengelola Provider

### 6.1 Menambah Provider Baru

1. Login ke Admin Panel
2. Klik menu **Providers** di sidebar
3. Klik tombol **"Add Provider"**
4. Isi form:

| Field | Contoh | Keterangan |
|-------|--------|------------|
| Name | `vLLM Local` | Nama provider |
| Type | `openai` | Tipe provider (OpenAI-compatible) |
| Base URL | `http://localhost:8001/v1` | Endpoint vLLM |
| API Key | `fake-key` | API key (boleh arbitrary untuk vLLM) |
| Enabled | ✓ | Aktifkan provider |

5. Klik **Save**

### 6.2 Mengedit Provider

1. Di halaman Providers, klik ikon **Edit** (pensil) pada provider
2. Ubah nilai yang diinginkan
3. Klik **Save**

### 6.3 Setting Base URL untuk vLLM

Base URL adalah alamat endpoint vLLM server:

```env
# Format
openai_base_url=http://<host>:<port>/v1

# Contoh untuk vLLM di mesin yang sama
openai_base_url=http://localhost:8001/v1

# Contoh untuk vLLM di server berbeda
openai_base_url=http://192.168.1.100:8000/v1

# Contoh untuk vLLM dengan custom path
openai_base_url=https://vllm.example.com/api/v1
```

### 6.4 Testing Koneksi Provider

**Menggunakan curl:**

```bash
# Test endpoint vLLM
curl http://localhost:8001/v1/models

# Expected response:
# {
#   "object": "list",
#   "data": [
#     {
#       "id": "meta-llama/Llama-3-8b-chat",
#       "object": "model",
#       ...
#     }
#   ]
# }
```

**Test via Admin Panel:**

1. Buka halaman Providers
2. Klik tombol **"Test Connection"** pada provider
3. Sistem akan mengirim request test ke endpoint
4. Hasil akan ditampilkan di UI

### 6.5 Melihat Model yang Tersedia

```bash
# List models dari vLLM
curl http://localhost:8001/v1/models | jq

# Atau via Python
python -c "
import httpx
resp = httpx.get('http://localhost:8001/v1/models')
print(resp.json())
"
```

---

## 7. Dokumentasi API

### 7.1 Menggunakan /docs Endpoint

FastAPI menyediakan dokumentasi interaktif di `/docs`:

1. Akses `http://localhost:8000/docs`
2. UI Swagger akan ditampilkan:
   ```
   ┌─────────────────────────────────────────────────────────┐
   │  AI Chat Backend                              v2.0.0   │
   │                                                         │
   │  GET /health        Health check                       │
   │  POST /auth/login   Login user                         │
   │  POST /chat         Chat completion (SSE)              │
   │  GET /models        List available models              │
   │  ...                                                   │
   └─────────────────────────────────────────────────────────┘
   ```

3. Klik endpoint untuk melihat detail
4. Klik "Try it out" untuk testing
5. Isi parameter dan body
6. Klik "Execute"

### 7.2 Endpoint Utama

| Method | Endpoint | Keterangan |
|--------|----------|------------|
| `GET` | `/health` | Cek status server |
| `POST` | `/auth/register` | Registrasi user baru |
| `POST` | `/auth/login` | Login user |
| `POST` | `/auth/refresh` | Refresh token |
| `GET` | `/models` | Daftar model tersedia |
| `POST` | `/chat/completions` | Chat completion (streaming) |
| `GET` | `/chats` | Daftar chat user |
| `GET` | `/providers` | Daftar providers |
| `POST` | `/files/upload` | Upload file |
| `POST` | `/retrieval/search` | Web search |

### 7.3 Contoh Request

**Chat Completion:**

```bash
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "model": "meta-llama/Llama-3-8b-chat",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ],
    "stream": true
  }'
```

**List Models:**

```bash
curl http://localhost:8000/models \
  -H "Authorization: Bearer <token>"
```

---

## 8. Troubleshooting

### 8.1 Masalah Umum

#### Database Connection Failed

**Gejala:**
```
sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) 
could not connect to server: Connection refused
```

**Solusi:**

1. Cek status PostgreSQL:
   ```bash
   sudo systemctl status postgresql
   # atau
   docker ps | grep postgres
   ```

2. Verifikasi koneksi:
   ```bash
   psql -U postgres -h localhost -d altex_chat
   ```

3. Cek `.env`:
   ```bash
   # Pastikan connection string benar
   cat .env | grep database_url
   ```

4. Cek firewall:
   ```bash
   sudo ufw allow 5432/tcp
   ```

#### Port Already in Use

**Gejala:**
```
OSError: [Errno 98] Address already in use: ('0.0.0.0', 8000)
```

**Solusi:**

```bash
# Cari proses yang menggunakan port
lsof -i :8000

# Hentikan proses
kill -9 <PID>

# Atau gunakan port berbeda
uvicorn main:app --port 8001
```

#### Module Not Found

**Gejala:**
```
ModuleNotFoundError: No module named 'fastapi'
```

**Solusi:**

```bash
# Pastikan venv aktif
source .venv/bin/activate

# Verifikasi
which python

# Reinstall dependencies
pip install -r requirements.txt
```

#### Migration Failed

**Gejala:**
```
alembic.util.exc.CommandError: Can't locate revision identified by '...'
```

**Solusi:**

```bash
# Cek status migrasi
alembic current

# Reset dan jalankan ulang (HATI-HATI: akan menghapus data)
alembic downgrade base
alembic upgrade head

# Atau buat migrasi baru
alembic revision --autogenerate -m "fix migration"
alembic upgrade head
```

#### pgvector Extension Missing

**Gejala:**
```
sqlalchemy.exc.ProgrammingError: type "vector" does not exist
```

**Solusi:**

```bash
# Install pgvector
sudo apt install postgresql-15-pgvector

# Atau aktifkan extension di database
psql -U postgres -d altex_chat -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

#### Admin Login Failed

**Gejala:**
Kredensial tidak diterima saat login.

**Solusi:**

1. Verifikasi admin ada di database:
   ```sql
   SELECT email, role FROM users WHERE role = 'admin';
   ```

2. Reset password admin:
   ```bash
   # Jalankan script reset
   python -c "
   from admin.auth import hash_password
   print(hash_password('NewPassword@123'))
   "
   
   # Update di database
   UPDATE users SET password_hash = '<hash>' WHERE email = 'admin@altex.local';
   ```

3. Atau buat ulang admin default:
   ```bash
   # Di Python shell
   from database import async_session_factory
   from admin.auth import create_default_admin
   import asyncio
   
   asyncio.run(create_default_admin())
   ```

### 8.2 Cara Melihat Logs

**File logs:**

```bash
# Log utama
tail -f /var/log/altex-backend/app.log

# Atau jika menjalankan langsung
tail -f nohup.out

# Dengan deploy.sh
./deploy.sh --logs
```

**Systemd journal (jika menggunakan service):**

```bash
# Log real-time
journalctl -u altex-backend -f

# Log 100 baris terakhir
journalctl -u altex-backend -n 100

# Sejak waktu tertentu
journalctl -u altex-backend --since "1 hour ago"
```

**Uvicorn logs:**

```bash
# Menjalankan dengan log level debug
uvicorn main:app --log-level debug
```

### 8.3 Debug Mode

Untuk debugging, aktifkan mode debug:

```env
# Di .env
environment=development
log_level=debug
```

```python
# Atau di main.py
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## 9. Deployment Produksi

### 9.1 Menggunakan Systemd Service

File `install-service.sh` akan menginstall sebagai systemd service:

```bash
# Install service
sudo ./install-service.sh

# Atau manual:
```

**Buat file service:**

```bash
sudo nano /etc/systemd/system/altex-backend.service
```

**Isi file:**

```ini
[Unit]
Description=Altex Backend API Server
After=network.target postgresql.service

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/opt/altex-backend
Environment="PATH=/opt/altex-backend/.venv/bin"
ExecStart=/opt/altex-backend/.venv/bin/uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4 \
    --log-level info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Aktifkan service:**

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service
sudo systemctl enable altex-backend

# Start service
sudo systemctl start altex-backend

# Cek status
sudo systemctl status altex-backend
```

### 9.2 Security Considerations

#### Ganti Kredensial Default

```bash
# Ganti secret key
python -c "import secrets; print(secrets.token_urlsafe(32))"
# Copy output ke .env sebagai secret_key

# Update .env
secret_key=<output-dari-perintah-di-atas>
```

#### HTTPS dengan Nginx Reverse Proxy

**Konfigurasi Nginx:**

```nginx
server {
    listen 80;
    server_name api.example.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_certificate /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Untuk SSE streaming
        proxy_buffering off;
        proxy_cache off;
    }
}
```

#### Database Security

```sql
-- Buat user khusus untuk aplikasi
CREATE USER altex_app WITH PASSWORD 'secure_random_password';

-- Berikan hak akses minimal
GRANT CONNECT ON DATABASE altex_chat TO altex_app;
GRANT USAGE ON SCHEMA public TO altex_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO altex_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO altex_app;

-- Larang akses ke tabel lain
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
```

#### Environment Production

```env
environment=production
log_level=warning
enable_signup=false  # Disable public registration

# CORS - batasi origins
allowed_cors_origins=["https://yourdomain.com"]
```

### 9.3 Monitoring

**Health check endpoint:**

```bash
# Tambahkan ke cron untuk monitoring
*/5 * * * * curl -f http://localhost:8000/health || systemctl restart altex-backend
```

**Prometheus metrics:**

```bash
# Endpoint metrics (jika diaktifkan)
curl http://localhost:8000/metrics
```

---

## Checklist Deployment

Gunakan checklist ini untuk memastikan deployment berhasil:

- [ ] Python 3.10+ terinstall
- [ ] PostgreSQL berjalan dengan pgvector
- [ ] Virtual environment aktif
- [ ] Dependencies terinstall
- [ ] File `.env` dikonfigurasi
- [ ] Database migrasi berhasil
- [ ] Admin default dapat login
- [ ] API dapat diakses di `/docs`
- [ ] Provider vLLM terkonfigurasi
- [ ] Test chat completion berhasil
- [ ] Logs dapat dilihat
- [ ] Systemd service aktif (produksi)

---

## Dukungan

Jika mengalami masalah:

1. Cek [Troubleshooting](#8-troubleshooting) di atas
2. Lihat log aplikasi: `./deploy.sh --logs`
3. Verifikasi konfigurasi: `cat .env`
4. Cek status service: `./deploy.sh --status`

---

**Dokumen ini terakhir diupdate:** 2024
**Versi:** 1.0.0
