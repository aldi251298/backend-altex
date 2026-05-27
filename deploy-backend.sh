#!/bin/bash
# ============================================================================
# AI Chat Backend Deployment Script (FREE - vLLM only, no paid APIs)
# EC2: 3.113.109.206 (ubuntu)
# RDS: altex-chat.crek440ck7co.ap-northeast-1.rds.amazonaws.com
# ============================================================================

set -e

echo "=========================================="
echo "  AI Chat Backend Deployment (FREE)"
echo "=========================================="

# ---- Configuration ----
PROJECT_DIR="/home/ubuntu/PROJECT/backend"
RDS_ENDPOINT="altex-chat.crek440ck7co.ap-northeast-1.rds.amazonaws.com"
RDS_PORT="5432"
RDS_USER="admin"
RDS_PASSWORD="uLFIfDIzxzTuxLbNBdNn"
RDS_DATABASE="altex-chat"
SECRET_KEY="your-super-secret-key-min-32-chars-here-change-this"
VLLM_PRIVATE_IP="172.31.X.X"  # <-- UBAH: Private IP EC2 vLLM Anda

# ---- Step 1: Install System Dependencies ----
echo ""
echo "[1/8] Installing system dependencies..."
sudo apt update
sudo apt install -y python3.11-venv python3-pip postgresql-client nginx git

# ---- Step 2: Setup Python Virtual Environment ----
echo ""
echo "[2/8] Setting up Python virtual environment..."
cd /home/ubuntu/PROJECT
if [ -d "venv" ]; then
    echo "Virtual environment already exists, skipping..."
else
    python3.11 -m venv venv
    echo "Virtual environment created."
fi

source /home/ubuntu/PROJECT/venv/bin/activate
pip install --upgrade pip
cd $PROJECT_DIR
pip install -r requirements.txt
echo "Python dependencies installed."

# ---- Step 3: Setup Database & Extensions ----
echo ""
echo "[3/8] Setting up database..."
echo "Connecting to RDS ($RDS_ENDPOINT:$RDS_PORT)..."

# Test connection
if ! psql "host=$RDS_ENDPOINT port=$RDS_PORT dbname=postgres user=$RDS_USER password=$RDS_PASSWORD sslmode=require" -c '\q' 2>/dev/null; then
    echo "ERROR: Cannot connect to RDS. Check security group rules!"
    echo ""
    echo "Run this from EC2 security group to allow inbound port 5432:"
    echo "aws ec2 authorize-security-group-ingress --group-id <RDS_SG_ID> --protocol tcp --port 5432 --source-group <EC2_SG_ID>"
    exit 1
fi
echo "RDS connection successful."

# Create database if not exists
psql "host=$RDS_ENDPOINT port=$RDS_PORT dbname=postgres user=$RDS_USER password=$RDS_PASSWORD sslmode=require" \
    -c "CREATE DATABASE $RDS_DATABASE;" 2>/dev/null || echo "Database '$RDS_DATABASE' already exists."

# Enable pgvector extension
echo "Enabling pgvector extension..."
psql "host=$RDS_ENDPOINT port=$RDS_PORT dbname=$RDS_DATABASE user=$RDS_USER password=$RDS_PASSWORD sslmode=require" \
    -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Create vector_store table
echo "Creating vector_store table..."
psql "host=$RDS_ENDPOINT port=$RDS_PORT dbname=$RDS_DATABASE user=$RDS_USER password=$RDS_PASSWORD sslmode=require" << 'EOSQL'
CREATE TABLE IF NOT EXISTS vector_store (
    id TEXT PRIMARY KEY,
    collection_name TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),
    metadata TEXT DEFAULT '{}',
    created_at BIGINT,
    updated_at BIGINT
);

CREATE INDEX IF NOT EXISTS idx_vs_collection ON vector_store (collection_name);
CREATE INDEX IF NOT EXISTS idx_vs_embedding ON vector_store 
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_vs_metadata ON vector_store USING GIN ((metadata::jsonb));
EOSQL

echo "Database setup complete."

# ---- Step 4: Create .env file ----
echo ""
echo "[4/8] Creating .env file (FREE configuration)..."
cat > $PROJECT_DIR/.env << EOF
# Core
secret_key=$SECRET_KEY
database_url=postgresql+asyncpg://${RDS_USER}:${RDS_PASSWORD}@${RDS_ENDPOINT}:${RDS_PORT}/${RDS_DATABASE}
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

# Embedding - menggunakan Ollama GRATIS (harus jalankan di EC2 vLLM atau yang sama)
embedding_engine=ollama
rag_embedding_model=nomic-embed-text
embedding_dimension=768

# RAG
chunk_size=1500
chunk_overlap=100
rag_top_k=5
rag_relevance_threshold=0.3
enable_rag_query_generation=false
enable_rag_reranking=false

# Web Search - DuckDuckGo GRATIS
enable_web_search=false
enable_web_search_auto=false
web_search_engine=duckduckgo
search_result_count=5
enable_web_content_extraction=true

# File Storage
storage_provider=local
upload_dir=/app/uploads

# Task Model
task_model=
enable_title_generation=true
enable_tag_generation=true

# Features
enable_image_generation=false
enable_code_interpreter=false
enable_memory=false

# Monitoring
enable_metrics=true
sentry_dsn=

# vLLM - Base URL untuk chat completions
openai_api_key=fake-key-because-vllm-doesnt-verify
openai_base_url=http://${VLLM_PRIVATE_IP}:8000/v1

# Ollama - Base URL untuk embeddings (jika vLLM dan Ollama di EC2 sama)
ollama_base_url=http://localhost:11434
EOF

echo ".env created."
echo ""
echo "IMPORTANT: Edit .env jika vLLM private IP berbeda!"
echo "  Edit baris: openai_base_url=http://<VLLM_PRIVATE_IP>:8000/v1"

# ---- Step 5: Run Migrations ----
echo ""
echo "[5/8] Running Alembic migrations..."
cd $PROJECT_DIR
alembic upgrade head
echo "Migrations complete."

# ---- Step 6: Create upload directory ----
echo ""
echo "[6/8] Creating upload directory..."
sudo mkdir -p /app/uploads
sudo chown ubuntu:ubuntu /app/uploads
echo "Upload directory created."

# ---- Step 7: Setup systemd service ----
echo ""
echo "[7/8] Setting up systemd service..."
sudo tee /etc/systemd/system/ai-chat.service > /dev/null << EOF
[Unit]
Description=AI Chat Backend Service
After=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=$PROJECT_DIR
Environment="PATH=/home/ubuntu/PROJECT/venv/bin"
ExecStart=/home/ubuntu/PROJECT/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ai-chat

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ai-chat
sudo systemctl restart ai-chat

sleep 3
echo "Systemd service configured."

# ---- Step 8: Setup Nginx (optional, for reverse proxy) ----
echo ""
echo "[8/8] Setting up Nginx..."
sudo tee /etc/nginx/sites-available/ai-chat > /dev/null << EOF
server {
    listen 80;
    
    # Allow large file uploads
    client_max_body_size 50M;
    
    # SSE configuration (CRITICAL for streaming)
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 300s;
    
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    
    # Health check
    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
    }
    
    # Static files (if any)
    location /static/ {
        alias /home/ubuntu/PROJECT/backend/static/;
        expires 30d;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/ai-chat /etc/nginx/sites-enabled/
sudo nginx -t 2>/dev/null && sudo systemctl restart nginx || echo "Nginx config test failed. Skipping nginx setup."

# ---- Summary ----
echo ""
echo "=========================================="
echo "  DEPLOYMENT COMPLETE! (FREE)"
echo "=========================================="
echo ""
echo "  Backend URL:  http://3.113.109.206:8000"
echo "  Health Check: http://3.113.109.206:8000/health"
echo "  API Base:     http://3.113.109.206:8000/api"
echo ""
echo "  Configuration:"
echo "    Chat:    vLLM @ http://${VLLM_PRIVATE_IP}:8000/v1"
echo "    Embed:   Ollama @ http://localhost:11434"
echo ""
echo "  Services:"
sudo systemctl status ai-chat --no-pager | head -10
echo ""
echo "  Logs:"
echo "  journalctl -u ai-chat -f -n 50"
echo ""
echo "  ===== IMPORTANT NOTES ====="
echo "  1. Ensure vLLM is running on EC2 (port 8000)"
echo "  2. Ensure Ollama is running for embeddings (port 11434)"
echo "  3. Pull embedding model: ollama pull nomic-embed-text"
echo "  4. If vLLM IP changed, edit .env and restart:"
echo "     sudo systemctl restart ai-chat"
echo "=========================================="
