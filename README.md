# 🏦 Fraud Detection System — Zero-Cost Agentic AI

Hệ thống phát hiện gian lận ngân hàng sử dụng **multi-agent AI pipeline**.

5 AI agents phối hợp qua LangGraph để sàng lọc, điều tra và ra quyết định cho mỗi giao dịch theo 3 phase: **Rule-Based Screening → AI Investigation → Enforcement**.

---

## 🏗️ Kiến trúc

```
                         Transaction
                              │
                    ┌─────────▼──────────┐
                    │  PHASE 1: Screening │  ← Redis Cloud
                    │  (Rule-Based)       │
                    └────────┬────────────┘
                             │
                ┌────────────┼────────────┐
                │            │            │
             🟢 GREEN    🟡 YELLOW    🔴 RED
             ALLOW       │            BLOCK
                         ▼
              ┌──────────────────────┐
              │  PHASE 2: AI Agents  │  ← LangGraph Loop
              │                      │
              │  Planner  → Executor │  ← Gemini 2.5 Flash
              │  Vision   → Report   │  ← Neo4j + MongoDB + ChromaDB
              │  Detective           │
              └──────────┬───────────┘
                         │
              ┌──────────▼───────────┐
              │  PHASE 3: Enforce    │
              │  BLOCK / ALLOW /     │
              │  ESCALATE            │
              └──────────────────────┘
```

### Pipeline chi tiết

| Phase | Mô tả | Công nghệ |
|-------|--------|-----------|
| **Phase 1** | Sàng lọc real-time: whitelist/blacklist, risk score, velocity, amount threshold, VPN/Tor detection | Redis Cloud |
| **Phase 2** | Điều tra AI (chỉ cho YELLOW): Planner tạo hypothesis → Executor truy vấn DB → Vision phân tích chéo → Report tạo báo cáo → Detective ra quyết định | Gemini 2.5 Flash, Neo4j, MongoDB, ChromaDB |
| **Phase 3** | Thực thi: BLOCK → blacklist + tăng risk score + lưu pattern. ALLOW → whitelist + giảm risk score. ESCALATE → hold + chuyển human review | Redis Cloud, ChromaDB |

---

## 🤖 5 AI Agents

| Agent | Vai trò |
|-------|---------|
| **Planner** | Phân tích context Phase 1, tạo giả thuyết (structuring, money laundering, ATO), phân rã thành investigation tasks |
| **Executor** | AI Agent thật sự — Gemini sinh Cypher/MongoDB/ChromaDB query tự động, chạy qua 12 DB tools, phân tích kết quả |
| **Vision** | Phân tích chéo tất cả evidence từ Executor, phát hiện pattern mà từng task riêng lẻ không thấy được |
| **Report** | Tạo báo cáo điều tra chi tiết bằng ngôn ngữ tự nhiên (audit-ready) |
| **Detective** | Thẩm phán cuối cùng — đánh giá ĐỘC LẬP, ra quyết định BLOCK/ALLOW/ESCALATE, thực thi Phase 3 |

---

## ⚡ Tech Stack

| Thành phần | Công nghệ | Thay thế |
|------------|-----------|----------|
| LLM (tất cả agents) | Google Gemini 2.5 Flash (free: 15 req/min) | AWS Bedrock |
| Graph DB | Neo4j AuraDB (free: 200K nodes) | Amazon Neptune |
| Vector Store / RAG | ChromaDB Cloud (trychroma.com) | Amazon OpenSearch |
| Document DB | MongoDB Atlas (M0 free: 512MB) | Amazon DynamoDB |
| Cache / Rules | Redis Cloud (free tier) | Amazon ElastiCache |
| Orchestration | LangGraph (StateGraph) | Custom orchestration |
| Backend | FastAPI + Uvicorn | — |
| Data Models | Pydantic v2 | — |

---

## 📁 Cấu trúc Project

```
├── main.py                 # Entrypoint: CLI demo + FastAPI server
├── config.py               # Quản lý environment variables
├── models.py               # Pydantic models (Transaction, Phase1Result, ...)
├── orchestrator.py          # LangGraph pipeline (Phase 1 → 2 → 3)
├── llm_providers.py         # Gemini 2.5 Flash wrapper
├── planner_agent.py         # Planner Agent
├── executor_agent.py        # Executor Agent (AI-driven, 12 DB tools)
├── vision_agent.py          # Vision Agent (cross-reference analysis)
├── report_agent.py          # Report Agent (NL report generation)
├── detective_agent.py       # Detective Agent (final adjudication)
├── graph_db.py              # Neo4j AuraDB client
├── mongo_db.py              # MongoDB Atlas client
├── vector_store.py          # ChromaDB Cloud client
├── simulators.py            # In-memory simulators + RedisService
├── setup_demo.py            # Seed demo data vào 4 databases
├── requirements.txt         # Dependencies
├── .env.example             # Template environment variables
└── .gitignore
```

---

## 🚀 Cài đặt & Chạy

### 1. Clone & tạo virtual environment

```bash
git clone https://github.com/drpie143/Swinburne-Hackathon.git
cd Swinburne-Hackathon
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate
```

### 2. Cài dependencies

```bash
pip install -r requirements.txt
```

### 3. Cấu hình environment variables

```bash
cp .env.example .env
```

Mở `.env` và điền API keys:

| Biến | Bắt buộc | Mô tả |
|------|----------|-------|
| `GEMINI_API_KEY` | ✅ | Google AI Studio → [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `NEO4J_URI` | ✅ | Neo4j AuraDB URI (format: `neo4j+ssc://xxx.databases.neo4j.io`) |
| `NEO4J_USER` | ✅ | Neo4j username |
| `NEO4J_PASSWORD` | ✅ | Neo4j password |
| `CHROMA_API_KEY` | ✅ | ChromaDB Cloud API key |
| `CHROMA_TENANT` | ✅ | ChromaDB tenant ID |
| `CHROMA_DATABASE` | ✅ | ChromaDB database name |
| `MONGODB_URI` | ✅ | MongoDB Atlas connection string |
| `REDIS_HOST` | ⚪ | Redis Cloud host (bỏ qua → dùng simulator) |
| `REDIS_PASSWORD` | ⚪ | Redis Cloud password |

> **Demo Mode**: Nếu thiếu credentials, hệ thống tự fallback về in-memory simulators — vẫn chạy demo được mà không cần bất kỳ cloud service nào.

### 4. Seed demo data

```bash
python setup_demo.py
```

### 5. Chạy

```bash
# CLI Demo — chạy 3 scenarios
python main.py

# API Server — FastAPI trên http://localhost:8000
python main.py --serve
```

---

## 🎯 Demo Scenarios

| # | Tên | Giao dịch | Kết quả mong đợi |
|---|-----|-----------|-------------------|
| 1 | **Normal Transaction** | ACC_001 (whitelisted, 5 năm) → ACC_002, $250 | 🟢 GREEN → ALLOW |
| 2 | **Structuring Pattern** | ACC_007 (45 ngày, velocity cao, 15 GD <$1000/1h) → ACC_002, $950 | 🟡 YELLOW → Investigation → BLOCK |
| 3 | **Money Laundering** | ACC_050 (15 ngày, KYC pending, VPN/Tor) → ACC_666 (blacklisted), $25,000 | 🔴 RED → BLOCK |

---

## 🔌 API Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `GET` | `/` | Thông tin API |
| `GET` | `/health` | Health check |
| `POST` | `/transaction` | Xử lý 1 giao dịch |
| `GET` | `/scenarios` | Danh sách demo scenarios |
| `POST` | `/demo/{n}` | Chạy demo scenario 1-3 |

---

## 🔄 Fallback & Demo Mode

Tất cả DB clients đều có in-memory simulator làm fallback:

| Cloud Service | Simulator Fallback |
|---------------|-------------------|
| Redis Cloud | `RedisSimulator` (whitelist, blacklist, risk scores, velocity) |
| Neo4j AuraDB | `NeptuneSimulator` (graph nodes, edges, shared entities) |
| MongoDB Atlas | `DynamoDBSimulator` (customer profiles, transaction history) |
| ChromaDB Cloud | `OpenSearchSimulator` (fraud patterns, past cases) |

Khi `DEMO_MODE=true` hoặc thiếu credentials → hệ thống tự động dùng simulator, demo chạy hoàn toàn offline.

---

## 👥 Team

USIT TEAM Swinburne Hackathon 2025
