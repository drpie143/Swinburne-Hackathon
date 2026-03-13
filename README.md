# 🏦 Fraud Detection System — Agentic AI

A **multi-agent AI pipeline** for real-time bank fraud detection, built entirely on **free-tier cloud services**.

Five specialized AI agents collaborate through LangGraph to screen, investigate, and adjudicate every transaction across a 3-phase architecture: **Rule-Based Screening → AI Investigation → Enforcement**.

---

## 🏗️ Architecture

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

### Pipeline Details

| Phase | Description | Technology |
|-------|-------------|------------|
| **Phase 1** | Real-time screening: whitelist/blacklist checks, risk scoring, velocity tracking, amount thresholds, VPN/Tor detection | Redis Cloud |
| **Phase 2** | AI investigation (YELLOW only): Planner generates hypothesis → Executor queries DBs → Vision cross-references evidence → Report generates audit report → Detective makes final decision | Gemini 2.5 Flash, Neo4j, MongoDB, ChromaDB |
| **Phase 3** | Enforcement: BLOCK → blacklist + increase risk score + index pattern. ALLOW → whitelist + decrease risk score. ESCALATE → hold + route to human review | Redis Cloud, ChromaDB |

---

## 🤖 5 AI Agents

| Agent | Role |
|-------|------|
| **Planner** | Analyzes Phase 1 context, generates hypotheses (structuring, money laundering, ATO), decomposes into specific investigation tasks |
| **Executor** | True AI agent — Gemini autonomously generates Cypher/MongoDB/ChromaDB queries, executes via 12 pre-defined DB tools, analyzes raw results |
| **Vision** | Cross-references all evidence from Executor, detects patterns invisible to individual tasks (e.g., star topology + structuring = mule network) |
| **Report** | Generates detailed, audit-ready investigation reports in natural language |
| **Detective** | Final adjudicator — independently evaluates the report, makes BLOCK/ALLOW/ESCALATE decision, triggers Phase 3 enforcement |

---

## ⚡ Tech Stack (Zero-Cost)

| Component | Technology | Replaces |
|-----------|-----------|----------|
| LLM (all agents) | Google Gemini 2.5 Flash (free: 15 req/min) | AWS Bedrock |
| Graph DB | Neo4j AuraDB (free: 200K nodes) | Amazon Neptune |
| Vector Store / RAG | ChromaDB Cloud (trychroma.com) | Amazon OpenSearch |
| Document DB | MongoDB Atlas (M0 free: 512MB) | Amazon DynamoDB |
| Cache / Rules | Redis Cloud (free tier) | Amazon ElastiCache |
| Orchestration | LangGraph (StateGraph) | Custom orchestration |
| Backend | FastAPI + Uvicorn | — |
| Data Models | Pydantic v2 | — |

---

## 📁 Project Structure

```
├── main.py                  # Entrypoint: CLI demo + FastAPI server
├── config.py                # Environment variable management
├── models.py                # Pydantic models (Transaction, Phase1Result, ...)
├── orchestrator.py          # LangGraph pipeline (Phase 1 → 2 → 3)
├── llm_providers.py         # Gemini 2.5 Flash wrapper (shared by all agents)
├── planner_agent.py         # Planner Agent
├── executor_agent.py        # Executor Agent (AI-driven, 12 DB tools)
├── vision_agent.py          # Vision Agent (cross-reference analysis)
├── report_agent.py          # Report Agent (NL report generation)
├── detective_agent.py       # Detective Agent (final adjudication)
├── graph_db.py              # Neo4j AuraDB client
├── mongo_db.py              # MongoDB Atlas client
├── vector_store.py          # ChromaDB Cloud client
├── simulators.py            # In-memory simulators + RedisService
├── setup_demo.py            # Seed synthetic demo data to all databases
├── requirements.txt         # Python dependencies
├── .env.example             # Environment variable template
└── .gitignore
```

---

## 🚀 Getting Started

### 1. Clone & Create Virtual Environment

```bash
git clone https://github.com/drpie143/Swinburne-Hackathon.git
cd Swinburne-Hackathon
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your API keys:

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | ✅ | Google AI Studio → [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `NEO4J_URI` | ✅ | Neo4j AuraDB URI (format: `neo4j+ssc://xxx.databases.neo4j.io`) |
| `NEO4J_USER` | ✅ | Neo4j username |
| `NEO4J_PASSWORD` | ✅ | Neo4j password |
| `CHROMA_API_KEY` | ✅ | ChromaDB Cloud API key |
| `CHROMA_TENANT` | ✅ | ChromaDB tenant ID |
| `CHROMA_DATABASE` | ✅ | ChromaDB database name |
| `MONGODB_URI` | ✅ | MongoDB Atlas connection string |
| `REDIS_HOST` | ⚪ | Redis Cloud host (omit to use simulator) |
| `REDIS_PASSWORD` | ⚪ | Redis Cloud password |

> **Demo Mode**: If credentials are missing, the system automatically falls back to in-memory simulators — the demo runs fully offline without any cloud services.

### 4. Seed Demo Data

```bash
python setup_demo.py
```

### 5. Run

```bash
# CLI Demo — runs all 3 scenarios
python main.py

# API Server — FastAPI on http://localhost:8000
python main.py --serve
```

---

## 🎯 Demo Scenarios

| # | Name | Transaction | Expected Result |
|---|------|-------------|-----------------|
| 1 | **Normal Transaction** | ACC_001 (whitelisted, 5yr account) → ACC_002, $250 | 🟢 GREEN → ALLOW |
| 2 | **Structuring Pattern** | ACC_007 (45-day account, high velocity, 15 txns <$1000/1hr) → ACC_002, $950 | 🟡 YELLOW → Investigation → BLOCK |
| 3 | **Money Laundering** | ACC_050 (15-day account, KYC pending, VPN/Tor) → ACC_666 (blacklisted), $25,000 | 🔴 RED → BLOCK |

---

## 🔌 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | API information |
| `GET` | `/health` | Health check |
| `POST` | `/transaction` | Process a single transaction |
| `GET` | `/scenarios` | List available demo scenarios |
| `POST` | `/demo/{n}` | Run demo scenario 1–3 |

---

## 🔄 Fallback & Demo Mode

All database clients include in-memory simulators as fallback:

| Cloud Service | Simulator Fallback |
|---------------|-------------------|
| Redis Cloud | `RedisSimulator` — whitelist, blacklist, risk scores, velocity |
| Neo4j AuraDB | `NeptuneSimulator` — graph nodes, edges, shared entities |
| MongoDB Atlas | `DynamoDBSimulator` — customer profiles, transaction history |
| ChromaDB Cloud | `OpenSearchSimulator` — fraud patterns, past cases |

When `DEMO_MODE=true` or credentials are missing, the system automatically uses simulators — fully offline, no external services required.

---

## 👥 Team

USIT TEAM Swinburne Hackathon 2025
