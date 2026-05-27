# AI Chat Backend — Deployment Guide

> **Architecture:** EC2 Singapore (development) → GitHub → EC2 Backend Tokyo (production)
> **Stack:** FastAPI + PostgreSQL (RDS Aurora) + pgvector + vLLM + Ollama
> **Cost:** 100% free except AWS infrastructure (~$30-50/bulan)

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Pre-Deployment Checklist](#2-pre-deployment-checklist)
3. [Step 1: Setup GitHub Repository](#3-step-1-setup-github-repository)
4. [Step 2: Push Project ke GitHub](#4-step-2-push-project-ke-github)
5. [Step 3: Setup Security Group RDS](#5-step-3-setup-security-group-rds)
6. [Step 4: Login ke EC2 Backend](#6-step-4-login-ke-ec2-backend)
7. [Step 5: Clone & Setup di EC2 Backend](#7-step-5-clone--setup-di-ec2-backend)
8. [Step 6: Setup Database RDS](#8-step-6-setup-database-rds)
9. [Step 7: Run Migrations](#9-step-7-run-migrations)
10. [Step 8: Setup systemd Service](#10-step-8-setup-systemd-service)
11. [Step 9: Setup Nginx (Optional)](#11-step-9-setup-nginx-optional)
12. [Step 10: Test API](#12-step-10-test-api)
13. [Troubleshooting](#13-troubleshooting)
14. [Flutter Integration](#14-flutter-integration)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                      EC2 Singapore (dev)                           │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  PROJECT/backend (code, venv, testing)                       │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                     │
│                              │ git push                            │
└──────────────────────────────┼─────────────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   GitHub Private    │
                    │   Repository        │
                    └──────────┬──────────┘
                               │
                               │ git clone
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Tokyo Region (production)                     │
│                                                                     │
│  ┌─────────────────────┐     ┌─────────────────────┐              │
│  │  EC2 Backend        │     │  EC2 vLLM           │              │
│  │  3.113.109.206      │     │  172.31.9.197       │              │
│  │                     │     │                     │              │
│  │  FastAPI (port 8000)│◄────┤ vLLM (port 8000)   │              │
│  │  Nginx (port 80)    │     │  Ollama (port 11434)│              │
│  └──────────┬──────────┘     └─────────────────────┘              │
│             │ private IP (VPC)                                      │
│             │                                                     │
│  ┌──────────▼──────────┐                                          │
│  │  RDS Aurora PG      │                                          │
│  │  ap-northeast-1     │                                          │
│  │  altex-chat         │                                          │
│  │  pgvector enabled   │                                          │
│  └─────────────────────┘                                          │
└─────────────────────────────────────────────────────────────────────┘
```

**Key Points:**
- Backend EC2 dan vLLM EC2 di VPC yang sama → connect via **private IP**
- RDS Aurora di region yang sama → connect via public endpoint
- Flutter clients connect ke Backend via **Elastic IP** (`3.113.109.206`)

---

## 2. Pre-Deployment Checklist

Pastikan semua ini sudah siap:

- [ ] **EC2 Backend** running (`i-0ca8b884b2a2eb28f`) — region ap-northeast-1 (Tokyo)
- [ ] **Elastic IP** `3.113.109.206` assigned ke EC2 Backend
- [ ] **EC2 vLLM** running (`172.31.9.197`) — vLLM & Ollama sudah install
- [ ] **RDS Aurora PostgreSQL** running — endpoint: `altex-chat.crek440ck7co.ap-northeast-1.rds.amazonaws.com`
- [ ] **RDS password**已知: `uLFIfDIzxzTuxLbNBdNn`
- [ ] **GitHub account** dengan private repo

---

## 3. Step 1: Setup GitHub Repository

### 3.1 Buat Repository Baru

1. Buka **[github.com/new](https://github.com/new)**
2. Isi form:
   - **Repository name**: `ai-chat-backend` (atau nama apa saja)
   - **Description**: `AI Chat Backend with RAG`
   - **Private** ✅ (penting agar API key tidak terlihat)
   - **Tidak perlu** initialize dengan README / .gitignore / LICENSE
3. Click **Create repository**

### 3.2 Copy Repository URL

Setelah repository dibuat, copy HTTPS URL-nya:

```
https://github.com/<username>/<repo-name>.git
```

Contoh:
```
https://github.com/myuser/ai-chat-backend.git
```

**Simpan URL ini** — akan dipakai di Step 2.

---

## 4. Step 2: Push Project ke GitHub

### 4.1 Inisialisasi Git

**Di terminal EC2 Singapore (yang sedang kita akses sekarang):**

```bash
# Pastikan di folder backend
cd /home/ubuntu/PROJECT/backend

# Inisialisasi git (jika belum)
git init

# Tambahkan semua file
git add -A

# Commit pertama
git commit -m "Initial commit - AI Chat Backend with RAG"
```

### 4.2 Tambah Remote & Push

```bash
# Tambah remote GitHub (GANTI URL dengan repo Anda)
git remote add origin https://github.com/<username>/<repo-name>.git

# Rename branch ke main
git branch -M main

# Push ke GitHub
git push -u origin main
```

### 4.3 Authentication

Saat push, Anda akan diminta login. Pilih salah satu:

**Opsi A: GitHub CLI (paling mudah)**
```bash
# Install GitHub CLI jika belum
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update
sudo apt install -y github-cli

# Login
gh auth login --git-protocol https
```

**Opsi B: Personal Access Token**
1. Buka **GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens**
2. Buat token baru:
   - **Permissions**: `Contents: Read and Write`
   - **Repository**: This repository only
3. Generate → copy token
4. Saat diminta password di terminal, paste token:
   ```
   Username: <your-username>
   Password: ghp_xxxxxxxx
   ```

---

## 5. Step 3: Setup Security Group RDS

Agar EC2 Backend bisa connect ke RDS, perlu allow inbound port 5432.

### 5.1 Dapatkan Security Group IDs

**Di browser AWS Console:**

1. **EC2 Dashboard** → **Instances**
2. Click instance `i-0ca8b884b2a2eb28f` (Backend)
3. Scroll ke **Security** tab → copy **Security group ID** (bentuk: `sg-xxxxx`) → **EC2_SG**

4. **RDS Dashboard** → **Databases**
5. Click `altex-chat` cluster
6. Scroll ke **Security** → copy **Security group ID** → **RDS_SG**

### 5.2 Allow Inbound dari EC2 ke RDS

**Via AWS CLI (jika terinstall di EC2 Singapore):**

```bash
aws ec2 authorize-security-group-ingress \
  --group-id <RDS_SG_ID> \
  --protocol tcp \
  --port 5432 \
  --source-group <EC2_SG_ID>
```

**Via AWS Console (jika tidak ada AWS CLI):**

1. Buka **RDS Dashboard** → **Databases** → Click `altex-chat`
2. Click **Security group link** (di Security section)
3. Di **Security Groups** → Click the SG ID
4. Tab **Inbound rules** → **Edit inbound rules**
5. Click **Add rule**:
   - **Type**: PostgreSQL Aurora
   - **Protocol**: TCP
   - **Port range**: 5432
   - **Source**: Custom → paste **EC2_SG_ID** (`sg-xxxxx`)
6. Click **Save rules**

---

## 6. Step 4: Login ke EC2 Backend

Karena EC2 Backend belum punya SSH key Anda, gunakan **AWS Console Instance Connect**.

### 6.1 Login via Console

1. Buka **AWS Console** → **EC2 Dashboard**
2. **Instances** → Select `i-0ca8b884b2a2eb28f`
3. Click **Connect** (tombol hijau di atas)
4. Pilih tab **EC2 Instance Connect**
5. Click **Connect**
6. Terminal browser akan terbuka — Anda sudah login sebagai `ubuntu`!

### 6.2 Install EC2 Instance Connect Agent (untuk akses permanen)

**Di terminal Instance Connect:**

```bash
sudo apt update
sudo apt install -y ec2-instance-connect
sudo systemctl enable ec2-instance-connect
sudo systemctl start ec2-instance-connect
```

### 6.3 Setup SSH Key Permanen (opsional tapi recommended)

Agar bisa SSH langsung tanpa Console di masa depan:

**Di terminal EC2 Singapore:**
```bash
cat ~/.ssh/id_ed25519.pub
```
→ Copy output-nya (bentuk: `ssh-ed25519 AAAA... ubuntu@...`)

**Di AWS Console → EC2 Instance Connect:**
1. Paste public key di field "SSH public key"
2. Click **Send SSH public key**
3. Click **Connect** lagi — sekarang dengan key Anda

**Di terminal EC2 Backend:**
```bash
chmod 600 ~/.ssh/authorized_keys
```

Sekarang bisa SSH langsung dari EC2 Singapore:
```bash
ssh ubuntu@3.113.109.206
```

---

## 7. Step 5: Clone & Setup di EC2 Backend

### 7.1 Clone Repository

**Di EC2 Backend (via Instance Connect atau SSH):**

```bash
# Install AWS CLI untuk Session Manager (opsional)
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Clone repo (GANTI URL)
cd /home/ubuntu
git clone https://github.com/<username>/<repo-name>.git
cd PROJECT/backend
```

### 7.2 Install Dependencies

```bash
# Install system dependencies
sudo apt update
sudo apt install -y python3.11-venv python3-pip postgresql-client nginx

# Setup Python virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install Python packages
pip install --upgrade pip
pip install -r requirements.txt
```

### 7.3 Setup .env File

```bash
# Edit .env — GANTI <VLLM_PRIVATE_IP> dengan IP EC2 vLLM Anda
nano .env
```

Isi dengan:
```bash
# Core
secret_key=your-super-secret-key-min-32-chars-here-change-this
database_url=postgresql+asyncpg://admin:uLFIfDIzxzTuxLbNBdNn@altex-chat.crek440ck7co.ap-northeast-1.rds.amazonaws.com:5432/altex-chat
environment=production

# Server
host=0.0.0.0
port=8000
workers=4
log_level=warning

# Auth
enable_signup=true
access_token_expire_minutes=10080
refresh_token_expire_days=30
bcrypt_cost_factor=12
allowed_cors_origins=["*"]

# Embedding - Ollama (GRATIS)
embedding_engine=ollama
rag_embedding_model=nomic-embed-text
embedding_dimension=768

# OpenAI/vLLM Base URL
openai_api_key=fake-key-because-vllm-doesnt-verify
openai_base_url=http://<VLLM_PRIVATE_IP>:8000/v1

# RAG
chunk_size=1500
chunk_overlap=100
rag_top_k=5
rag_relevance_threshold=0.3
enable_rag_query_generation=false
enable_rag_reranking=false

# Web Search - DuckDuckGo (GRATIS)
enable_web_search=false
enable_web_search_auto=false
web_search_engine=duckduckgo
search_result_count=5
enable_web_content_extraction=true

# File Storage
storage_provider=local
upload_dir=/app/uploads

# Features
enable_image_generation=false
enable_code_interpreter=false
enable_memory=false

# Monitoring
enable_metrics=true
sentry_dsn=
```

**Cari nilai `<VLLM_PRIVATE_IP>`:**

```bash
# Di EC2 vLLM (172.31.9.197):
hostname -I
# Output: 172.31.9.197  (gunakan IP pertama)
```

Ganti di `.env`:
```
openai_base_url=http://172.31.9.197:8000/v1
```

### 7.4 Create Upload Directory

```bash
sudo mkdir -p /app/uploads
sudo chown ubuntu:ubuntu /app/uploads
```

---

## 8. Step 6: Setup Database RDS

### 8.1 Test Connection

```bash
psql "host=altex-chat.crek440ck7co.ap-northeast-1.rds.amazonaws.com \
      port=5432 dbname=postgres user=admin password=uLFIfDIzxzTuxLbNBdNn sslmode=require"
```

Jika berhasil, Anda akan masuk ke `psql` prompt (`altex-chat=#`).

### 8.2 Create Database

```sql
-- Di dalam psql prompt:
CREATE DATABASE altex-chat;
\q
```

### 8.3 Enable pgvector Extension

```bash
psql "host=altex-chat.crek440ck7co.ap-northeast-1.rds.amazonaws.com \
      port=5432 dbname=altex-chat user=admin password=uLFIfDIzxzTuxLbNBdNn sslmode=require" \
      -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 8.4 Create Tables & Indexes

```bash
psql "host=altex-chat.crek440ck7co.ap-northeast-1.rds.amazonaws.com \
      port=5432 dbname=altex-chat user=admin password=uLFIfDIzxzTuxLbNBdNn sslmode=require" << 'EOF'
-- Vector store table (untuk RAG)
CREATE TABLE IF NOT EXISTS vector_store (
    id TEXT PRIMARY KEY,
    collection_name TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),
    metadata TEXT DEFAULT '{}',
    created_at BIGINT,
    updated_at BIGINT
);

-- Index untuk fast similarity search
CREATE INDEX IF NOT EXISTS idx_vs_collection ON vector_store (collection_name);
CREATE INDEX IF NOT EXISTS idx_vs_embedding ON vector_store
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_vs_metadata ON vector_store USING GIN ((metadata::jsonb));
EOF
```

### 8.5 Verify Database

```bash
psql "host=altex-chat.crek440ck7co.ap-northeast-1.rds.amazonaws.com \
      port=5432 dbname=altex-chat user=admin password=uLFIfDIzxzTuxLbNBdNn sslmode=require" \
      -c "\dt" -c "\di"
```

Should show: `vector_store` table and indexes.

---

## 9. Step 7: Run Migrations

```bash
cd /home/ubuntu/PROJECT/backend
source venv/bin/activate

# Run Alembic migrations
alembic upgrade head

# Verify tables created
psql "host=altex-chat.crek440ck7co.ap-northeast-1.rds.amazonaws.com \
      port=5432 dbname=altex-chat user=admin password=uLFIfDIzxzTuxLbNBdNn sslmode=require" \
      -c "\dt"
```

Expected tables: `users`, `chats`, `files`, `providers`, `app_config`

---

## 10. Step 8: Setup systemd Service

### 10.1 Create Service File

```bash
sudo tee /etc/systemd/system/ai-chat.service > /dev/null << 'EOF'
[Unit]
Description=AI Chat Backend Service
After=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/PROJECT/backend
Environment="PATH=/home/ubuntu/PROJECT/backend/venv/bin"
ExecStart=/home/ubuntu/PROJECT/backend/venv/bin/uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ai-chat

[Install]
WantedBy=multi-user.target
EOF
```

### 10.2 Enable & Start Service

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-chat
sudo systemctl start ai-chat

# Check status
sudo systemctl status ai-chat --no-pager
```

### 10.3 View Logs

```bash
# Real-time logs
sudo journalctl -u ai-chat -f -n 50

# Recent logs
sudo journalctl -u ai-chat -n 100 --no-pager
```

### 10.4 Common Service Commands

```bash
sudo systemctl start ai-chat      # Start
sudo systemctl stop ai-chat       # Stop
sudo systemctl restart ai-chat    # Restart
sudo systemctl status ai-chat     # Status
sudo systemctl enable ai-chat     # Auto-start on boot
```

---

## 11. Step 9: Setup Nginx (Optional)

Nginx sebagai reverse proxy untuk SSE streaming.

### 9.1 Create Nginx Config

```bash
sudo tee /etc/nginx/sites-available/ai-chat > /dev/null << 'EOF'
server {
    listen 80;

    # Allow large file uploads (for RAG)
    client_max_body_size 50M;

    # SSE configuration (CRITICAL for streaming)
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 300s;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Health check endpoint
    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }
}
EOF

# Enable site
sudo ln -sf /etc/nginx/sites-available/ai-chat /etc/nginx/sites-enabled/

# Test config
sudo nginx -t

# Restart nginx
sudo systemctl restart nginx
sudo systemctl enable nginx
```

---

## 12. Step 10: Test API

### 12.1 Health Check

```bash
# Via localhost
curl http://localhost:8000/health

# Via Elastic IP
curl http://3.113.109.206:8000/health
```

Expected response:
```json
{"status": "healthy", "database": "connected"}
```

### 12.2 Test Register

```bash
curl -X POST http://3.113.109.206:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@test.com",
    "password": "admin123456",
    "name": "Admin User"
  }'
```

Expected response:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "user": {"id": "...", "email": "admin@test.com", "name": "Admin User", ...}
}
```

### 12.3 Test Login

```bash
curl -X POST http://3.113.109.206:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@test.com",
    "password": "admin123456"
  }'
```

### 12.4 Test Chat Completion

```bash
TOKEN="<copy_from_login_response>"

curl -X POST http://3.113.109.206:8000/api/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "model": "vllm.llama-3.1-8b-instruct",
    "messages": [
      {"role": "user", "content": "Halo, apa kabar?"}
    ],
    "stream": true
  }'
```

Expected: SSE stream with assistant response.

---

## 13. Troubleshooting

### Problem: Cannot connect to RDS

**Error:** `Connection refused` or `timeout`

**Solutions:**
1. Check RDS is running: AWS Console → RDS → Databases → status `available`
2. Check Security Group: RDS must allow inbound port 5432 from EC2 Backend SG
3. Test connection locally:
   ```bash
   psql "host=altex-chat.crek440ck7co.ap-northeast-1.rds.amazonaws.com \
         port=5432 dbname=altex-chat user=admin password=uLFIfDIzxzTuxLbNBdNn sslmode=require"
   ```

### Problem: pgvector extension not found

**Error:** `could not open extension control file`

**Solution:**
1. Verify pgvector is supported: AWS Console → RDS → your cluster → Modifications → pgvector should be in parameter groups
2. Or upgrade Aurora engine version to 15.3+ with pgvector engine version

### Problem: Service not starting

**Check logs:**
```bash
sudo journalctl -u ai-chat -n 100 --no-pager
```

Common issues:
- **Database URL wrong**: Check `.env` database_url
- **Port already in use**: `sudo lsof -i :8000`
- **Missing dependencies**: `pip install -r requirements.txt`

### Problem: vLLM connection failed

**Error:** `Provider connection error` or timeout

**Solutions:**
1. Check vLLM is running:
   ```bash
   # Di EC2 vLLM
   curl http://localhost:8000/v1/models
   ```
2. Check Backend can reach vLLM via private IP:
   ```bash
   # Di EC2 Backend
   curl http://172.31.9.197:8000/v1/models
   ```
3. Check `.env` has correct `openai_base_url`

### Problem: Ollama embedding not working

**Error:** `embedding generation failed`

**Solutions:**
1. Check Ollama is running:
   ```bash
   # Di EC2 Backend
   curl http://localhost:11434/api/tags
   ```
2. Pull embedding model:
   ```bash
   # Di EC2 Backend
   ollama pull nomic-embed-text
   ```

---

## 14. Flutter Integration

### 14.1 API Base URL

```dart
// lib/config.dart
class AppConfig {
  // Untuk production (Elastic IP)
  static const String baseUrl = 'http://3.113.109.206:8000';
  
  // Untuk development (local)
  // static const String baseUrl = 'http://localhost:8000';
  
  // API paths
  static const String loginPath = '$baseUrl/api/auth/login';
  static const String registerPath = '$baseUrl/api/auth/register';
  static const String chatCompletionsPath = '$baseUrl/api/chat/completions';
  static const String chatsPath = '$baseUrl/api/chats';
}
```

### 14.2 Android Network Config (HTTP)

Jika pakai HTTP (tanpa SSL), perlu enable cleartext traffic:

**`android/app/src/main/res/xml/network_security_config.xml`:**
```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="false">3.113.109.206</domain>
    </domain-config>
</network-security-config>
```

**`android/app/src/main/AndroidManifest.xml`:**
```xml
<application
    android:networkSecurityConfig="@xml/network_security_config"
    ...>
```

### 14.3 Chat API Call Example

```dart
import 'package:http/http.dart' as http;
import 'dart:convert';

class ChatService {
  final String token;
  
  ChatService(this.token);
  
  Future<Stream<http.StreamedResponse>> streamChat(
    String message,
  ) async {
    final response = await http.post(
      Uri.parse('http://3.113.109.206:8000/api/chat/completions'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $token',
      },
      body: jsonEncode({
        'model': 'vllm.llama-3.1-8b-instruct',
        'messages': [
          {'role': 'user', 'content': message},
        ],
        'stream': true,
      }),
    );
    
    return response.stream;
  }
}
```

---

## Quick Reference

| Item | Value |
|------|-------|
| **Backend Elastic IP** | `3.113.109.206` |
| **Backend Instance ID** | `i-0ca8b884b2a2eb28f` |
| **vLLM Private IP** | `172.31.9.197` (ganti dengan IP asli) |
| **RDS Endpoint** | `altex-chat.crek440ck7co.ap-northeast-1.rds.amazonaws.com` |
| **RDS Port** | `5432` |
| **RDS User** | `admin` |
| **RDS Password** | `uLFIfDIzxzTuxLbNBdNn` |
| **RDS Database** | `altex-chat` |
| **vLLM URL** | `http://<VLLM_PRIVATE_IP>:8000/v1` |
| **Ollama URL** | `http://localhost:11434` |
| **Flutter API URL** | `http://3.113.109.206:8000` |

---

## Next Steps After Deployment

1. **Setup vLLM** di EC2 Tokyo jika belum:
   ```bash
   # Di EC2 vLLM
   pip install vllm
   vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8000
   ```

2. **Setup Ollama** untuk embeddings:
   ```bash
   # Di EC2 Backend
   curl -fsSL https://ollama.ai/install.sh | sh
   ollama pull nomic-embed-text
   ```

3. **Setup SSL** untuk HTTPS (recommended):
   - Beli domain murah (~Rp 50k/tahun)
   - Install Let's Encrypt SSL
   - Atau beli DigiCert IP SSL (~$100/tahun)

4. **Monitor** dengan CloudWatch:
   - AWS Console → CloudWatch → Logs → `/var/log/syslog`

5. **Backup** database secara berkala:
   ```bash
   pg_dump "host=... dbname=altex-chat user=admin sslmode=require" \
     > backup_$(date +%Y%m%d).sql
   ```
