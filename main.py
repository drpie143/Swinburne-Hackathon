# ====================================================================
# MAIN.PY - FastAPI Backend + CLI Demo
# ====================================================================
#
# THAY ĐỔI:
#   Cũ: CLI-only demo chạy 3 scenarios rồi thoát
#   Mới: FastAPI server + CLI mode
#
# MODES:
#   1. CLI Demo: python main.py
#      → Chạy 3 demo scenarios (GREEN, YELLOW, YELLOW-with-VPN)
#      → In kết quả ra terminal
#
#   2. API Server: python main.py --serve
#      → Khởi động FastAPI trên http://localhost:8000
#      → Endpoints: POST /transaction, GET /health, GET /scenarios
#
# DEMO SCENARIOS:
#   Scenario 1: ACC_001 → ACC_002 ($250)
#     → GREEN: sender whitelisted, low amount, low risk
#     → Expected: ALLOW (skip investigation)
#
#   Scenario 2: ACC_007 → ACC_002 ($950)
#     → YELLOW: velocity cao + amount gần threshold + risk score cao
#     → Expected: Investigation → likely BLOCK (structuring pattern)
#
#   Scenario 3: ACC_050 → ACC_666 ($25,000)
#     → YELLOW/RED: VPN + large amount + receiver blacklisted
#     → Expected: Investigation → BLOCK (money laundering)
# ====================================================================

import sys
import json
import asyncio
from datetime import datetime

from models import Transaction
from orchestrator import FraudDetectionOrchestrator


# =====================================================================
# DEMO SCENARIOS
# =====================================================================

DEMO_SCENARIOS = [
    {
        "name": "Scenario 1: Normal Transaction (Expected: GREEN → ALLOW)",
        "description": (
            "ACC_001 (Nguyễn Văn An, whitelisted, 5 năm) "
            "gửi $250 cho ACC_002. Giao dịch bình thường."
        ),
        "transaction": Transaction(
            transaction_id="TXN_DEMO_001",
            timestamp=datetime.now().isoformat(),
            sender_id="ACC_001",
            sender_name="Nguyễn Văn An",
            sender_account_type="savings",
            receiver_id="ACC_002",
            receiver_name="Trần Minh Tuấn",
            amount=250.00,
            currency="USD",
            transaction_type="transfer",
            device_id="DEV_001",
            ip_address="14.161.42.100",
            channel="mobile",
            location="Ho Chi Minh City",
            description="Chuyển tiền ăn trưa",
        ),
    },
    {
        "name": "Scenario 2: Structuring Pattern (Expected: YELLOW → BLOCK)",
        "description": (
            "ACC_007 (Trần Thị B, tài khoản mới 45 ngày, velocity CAO) "
            "gửi $950 cho ACC_002. Nghi ngờ structuring: "
            "15 GD nhỏ (<$1000) trong 1 giờ qua, risk score cao."
        ),
        "transaction": Transaction(
            transaction_id="TXN_DEMO_002",
            timestamp=datetime.now().isoformat(),
            sender_id="ACC_007",
            sender_name="Trần Thị B",
            sender_account_type="checking",
            receiver_id="ACC_002",
            receiver_name="Trần Minh Tuấn",
            amount=950.00,
            currency="USD",
            transaction_type="transfer",
            device_id="DEV_002",
            ip_address="113.190.88.50",
            channel="mobile",
            location="Da Nang",
            description="Payment",
        ),
    },
    {
        "name": "Scenario 3: Money Laundering (Expected: YELLOW → BLOCK)",
        "description": (
            "ACC_050 (Unknown Entity, tài khoản mới 15 ngày, KYC pending) "
            "gửi $25,000 cho ACC_666 (BLACKLISTED). Dùng VPN/Tor."
        ),
        "transaction": Transaction(
            transaction_id="TXN_DEMO_003",
            timestamp=datetime.now().isoformat(),
            sender_id="ACC_050",
            sender_name="Unknown Entity",
            sender_account_type="business",
            receiver_id="ACC_666",
            receiver_name="Blocked Account",
            amount=25000.00,
            currency="USD",
            transaction_type="transfer",
            device_id="DEV_UNKNOWN_001",
            ip_address="185.220.101.42 (Tor Exit Node)",
            channel="web",
            location="Unknown (VPN)",
            merchant_id="MERCH_SHELL",
            description="Business payment",
        ),
    },
]


# =====================================================================
# CLI DEMO MODE
# =====================================================================

def run_cli_demo():
    """
    Chạy 3 demo scenarios liên tiếp.
    
    Output ra terminal với format đẹp, dễ đọc.
    Phù hợp cho hackathon presentation.
    """
    print("\n" + "=" * 70)
    print("  🏦 FRAUD DETECTION SYSTEM - Zero-Cost Agentic AI Demo")
    print("  " + "─" * 66)
    print("  Tech Stack:")
    print("    • LLM: Gemini 2.5 Flash (tất cả agents)")
    print("    • Graph DB: Neo4j AuraDB (cloud)")
    print("    • Vector Store: ChromaDB Cloud (trychroma.com)")
    print("    • Pipeline: LangGraph")
    print("    • Backend: FastAPI")
    print("=" * 70)
    
    orchestrator = FraudDetectionOrchestrator()
    orchestrator.initialize()
    
    results = []
    
    for i, scenario in enumerate(DEMO_SCENARIOS, 1):
        print(f"\n{'█'*70}")
        print(f"█ DEMO {i}/3: {scenario['name']}")
        print(f"█ {scenario['description'][:100]}")
        print(f"{'█'*70}")
        
        result = orchestrator.process_transaction(scenario["transaction"])
        results.append({
            "scenario": scenario["name"],
            "decision": result.get("final_decision", "unknown"),
            "message": result.get("final_message", ""),
        })
        
        print(f"\n{'─'*70}")
        input("   ⏎ Press Enter to continue to next scenario...") if i < len(DEMO_SCENARIOS) else None
    
    # ─── Summary ───
    print(f"\n{'='*70}")
    print("  📊 DEMO SUMMARY")
    print(f"{'='*70}")
    
    for r in results:
        symbols = {"allow": "✅", "block": "🚫", "escalate": "⚠️"}
        s = symbols.get(r["decision"], "?")
        print(f"  {s} {r['scenario'][:50]}")
        print(f"     → {r['decision'].upper()}: {r['message'][:80]}")
    
    print(f"\n{'='*70}")
    print("  Demo hoàn tất! 🎉")
    print(f"{'='*70}\n")
    
    orchestrator.shutdown()


# =====================================================================
# FASTAPI SERVER MODE
# =====================================================================

def create_fastapi_app():
    """
    Tạo FastAPI application.

    Endpoints:
    - GET  /        → API info
    - GET  /health  → Health check
    - POST /transaction → Process a transaction
    - GET  /scenarios   → List demo scenarios
    - POST /demo/{n}    → Run demo scenario N (1-3)
    - WS   /ws/pipeline → WebSocket real-time pipeline events
    - WS   /ws/pipeline/{txn_id} → WebSocket cho specific transaction
    """
    from fastapi import FastAPI, BackgroundTasks, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from concurrent.futures import ThreadPoolExecutor
    from event_emitter import event_emitter

    app = FastAPI(
        title="Fraud Detection System",
        description="Zero-Cost Agentic AI Fraud Detection Pipeline",
        version="2.0.0",
    )

    # CORS (cho frontend nếu có)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Shared orchestrator
    orchestrator = FraudDetectionOrchestrator()

    # Thread pool for running sync orchestrator in async context
    executor = ThreadPoolExecutor(max_workers=4)

    @app.on_event("startup")
    async def startup():
        orchestrator.initialize()

    @app.on_event("shutdown")
    async def shutdown():
        orchestrator.shutdown()
        executor.shutdown(wait=False)

    @app.get("/")
    async def root():
        return {
            "system": "Fraud Detection System",
            "version": "2.0.0",
            "stack": {
                "llm": "Gemini 2.5 Flash (all agents)",
                "graph_db": "Neo4j AuraDB",
                "vector_store": "ChromaDB",
                "pipeline": "LangGraph",
                "backend": "FastAPI",
            },
            "endpoints": {
                "health": "GET /health",
                "process": "POST /transaction",
                "process_realtime": "POST /transaction/stream",
                "scenarios": "GET /scenarios",
                "demo": "POST /demo/{scenario_number}",
                "websocket": "WS /ws/pipeline",
            },
        }

    @app.get("/health")
    async def health():
        return {
            "status": "healthy",
            "neo4j": "connected" if __import__("graph_db").neo4j_client.is_connected else "simulator",
            "chromadb": "active",
            "gemini": "configured" if __import__("config").settings.gemini_api_key else "fallback",
        }

    @app.post("/transaction")
    async def process_transaction(transaction: Transaction):
        """
        Xử lý 1 giao dịch qua pipeline.

        Body: Transaction object (JSON)
        Returns: Full pipeline result
        """
        # Run in thread pool to not block event loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            executor,
            orchestrator.process_transaction,
            transaction
        )

        return {
            "transaction_id": transaction.transaction_id,
            "decision": result.get("final_decision", "escalate"),
            "message": result.get("final_message", ""),
            "phase1": result.get("phase1_result"),
            "investigation": {
                "steps": result.get("investigation_step", 0),
                "evidence_count": len(result.get("all_results", [])),
                "confidence": result.get("planner_confidence", 0),
            },
            "report": result.get("report"),
            "detail": result.get("decision"),
        }

    @app.websocket("/ws/pipeline")
    async def websocket_pipeline(websocket: WebSocket):
        """
        WebSocket endpoint cho real-time pipeline events.

        Client connect → nhận tất cả events từ mọi transactions.
        """
        await websocket.accept()
        print(f"🔌 WebSocket client connected")

        queue = event_emitter.subscribe()

        try:
            while True:
                # Wait for events from orchestrator
                event = await queue.get()
                await websocket.send_text(event.to_json())
        except WebSocketDisconnect:
            print(f"🔌 WebSocket client disconnected")
        except Exception as e:
            print(f"❌ WebSocket error: {e}")
        finally:
            event_emitter.unsubscribe(queue)

    @app.websocket("/ws/pipeline/{transaction_id}")
    async def websocket_pipeline_txn(websocket: WebSocket, transaction_id: str):
        """
        WebSocket endpoint cho specific transaction.

        Client gửi transaction_id khi connect → chỉ nhận events của transaction đó.
        """
        await websocket.accept()
        print(f"🔌 WebSocket client connected for transaction: {transaction_id}")

        queue = event_emitter.subscribe(transaction_id)

        try:
            while True:
                event = await queue.get()
                await websocket.send_text(event.to_json())
        except WebSocketDisconnect:
            print(f"🔌 WebSocket client disconnected: {transaction_id}")
        except Exception as e:
            print(f"❌ WebSocket error: {e}")
        finally:
            event_emitter.unsubscribe(queue, transaction_id)

    @app.get("/scenarios")
    async def list_scenarios():
        """Liệt kê các demo scenarios."""
        return [
            {
                "id": i + 1,
                "name": s["name"],
                "description": s["description"],
                "transaction": s["transaction"].model_dump(),
            }
            for i, s in enumerate(DEMO_SCENARIOS)
        ]

    @app.post("/demo/{scenario_number}")
    async def run_demo_scenario(scenario_number: int):
        """
        Chạy 1 demo scenario (1-3).
        """
        if scenario_number < 1 or scenario_number > len(DEMO_SCENARIOS):
            raise HTTPException(
                status_code=400,
                detail=f"Scenario number must be 1-{len(DEMO_SCENARIOS)}",
            )

        scenario = DEMO_SCENARIOS[scenario_number - 1]

        # Run in thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            executor,
            orchestrator.process_transaction,
            scenario["transaction"]
        )

        return {
            "scenario": scenario["name"],
            "description": scenario["description"],
            "transaction_id": scenario["transaction"].transaction_id,
            "decision": result.get("final_decision", "escalate"),
            "message": result.get("final_message", ""),
            "phase1": result.get("phase1_result"),
            "report": result.get("report"),
            "detail": result.get("decision"),
        }

    return app


# =====================================================================
# ENTRY POINT
# =====================================================================

def main():
    """
    Entry point:
    - python main.py          → CLI demo (3 scenarios)
    - python main.py --serve  → FastAPI server
    """
    if "--serve" in sys.argv:
        # ─── FastAPI Server Mode ───
        import uvicorn
        from config import settings
        
        print("\n🚀 Starting FastAPI server...")
        print(f"   URL: http://{settings.api_host}:{settings.api_port}")
        print(f"   Docs: http://localhost:{settings.api_port}/docs")
        
        app = create_fastapi_app()
        uvicorn.run(
            app,
            host=settings.api_host,
            port=settings.api_port,
            log_level="info",
        )
    else:
        # ─── CLI Demo Mode ───
        run_cli_demo()


if __name__ == "__main__":
    main()
