# ====================================================================
# ORCHESTRATOR.PY - LangGraph Pipeline Orchestration
# ====================================================================
#
# THAY ĐỔI:
#   Cũ: Class-based orchestrator với if/else routing thủ công
#   Mới: LangGraph StateGraph với conditional edges
#
# GRAPH FLOW:
#   START
#     ↓
#   [phase1_screening] → Enriched Phase1Result (RuleDetail, AccountFlags)
#     ↓
#   {route_after_phase1}
#     ├── GREEN → END (allow)
#     ├── RED   → END (block)
#     └── YELLOW → [planner]
#                     ↓
#                  [executor] → query Neo4j + ChromaDB + MongoDB Atlas
#                     ↓
#                  [vision]  → Gemini đọc/phân tích kết quả executor
#                     ↓
#                  [planner_evaluate] → Planner đánh giá vision analysis
#                     ↓
#                  {route_after_evaluate}
#                     ├── done → [report_generator] → [detective] → END
#                     └── not_done → [executor] (loop)
#
# LangGraph:
#   - Mỗi node là 1 function nhận state → trả state mới
#   - Conditional edges: routing dựa trên state values
#   - Built-in state management: không cần global variables
# ====================================================================

from __future__ import annotations

import uuid
import threading
from datetime import datetime
from typing import TypedDict, Optional, Annotated

from langgraph.graph import StateGraph, END

from models import (
    Transaction, Phase1Result, RuleDetail, AccountFlags,
    InvestigationRequest, PlannerTask, ExecutorResult,
    InvestigationReport, DecisionResult,
    RiskLevel, FinalDecision, TaskType,
)
from simulators import redis_service
from mongo_db import mongodb_client
from graph_db import neo4j_client
from vector_store import vector_store
from planner_agent import PlannerAgent
from executor_agent import ExecutorAgent
from report_agent import ReportAgent
from detective_agent import DetectiveAgent
from vision_agent import vision_agent
from config import settings


# =====================================================================
# LANGGRAPH STATE - TypedDict for state management
# =====================================================================

class GraphState(TypedDict, total=False):
    """
    State object cho LangGraph pipeline.
    
    Mỗi node đọc fields cần thiết và cập nhật fields output.
    LangGraph tự merge state updates.
    """
    # Input
    transaction: Optional[dict]  # Transaction as dict
    
    # Phase 1
    phase1_result: Optional[dict]  # Phase1Result as dict
    phase1_risk_level: str  # "green" / "yellow" / "red"
    
    # Phase 2 - Planning
    investigation_request: Optional[dict]
    current_tasks: list  # list[PlannerTask dicts]
    all_results: list  # list[ExecutorResult dicts]
    investigation_step: int
    investigation_done: bool
    planner_confidence: float
    
    # Phase 2 - Vision Analysis
    vision_analysis: Optional[dict]  # VisionAgent output
    
    # Phase 2 - Report
    report: Optional[dict]
    
    # Phase 3
    decision: Optional[dict]
    
    # Final output
    final_decision: str  # "allow" / "block" / "escalate"
    final_message: str
    
    # Meta
    error: Optional[str]


# =====================================================================
# NODE: PHASE 1 SCREENING (Enriched)
# =====================================================================

def phase1_screening(state: GraphState) -> GraphState:
    """
    Phase 1: Real-time Screening với Redis Simulator.
    
    ENRICHED: Tạo Phase1Result chi tiết gồm:
    - triggered_rules → list[RuleDetail] (severity, value, threshold)
    - sender_flags, receiver_flags → AccountFlags
    - context_summary → text cho Planner
    
    Routing logic:
    - Sender whitelisted + amount < $1000 + score < 0.2 → GREEN
    - Sender blacklisted OR score > 0.9 → RED
    - Còn lại → YELLOW (cần điều tra)
    """
    txn_dict = state["transaction"]
    txn = Transaction(**txn_dict)
    
    print(f"\n{'#'*70}")
    print(f"# PHASE 1: Real-Time Screening")
    print(f"# Transaction: {txn.transaction_id}")
    print(f"# {txn.sender_id} → {txn.receiver_id}: ${txn.amount:,.2f}")
    print(f"{'#'*70}")
    
    triggered_rules: list[RuleDetail] = []
    risk_score = 0.0
    
    # ─── Increment velocity counter (ref: fraud-detection/phase1.py Check 4) ───
    redis_service.increment_velocity(txn.sender_id)
    
    # ─── Rule 1: Blacklist check ───
    if redis_service.is_blacklisted(txn.sender_id):
        triggered_rules.append(RuleDetail(
            rule="SENDER_BLACKLISTED",
            severity="critical",
            detail=f"Sender {txn.sender_id} is on blacklist",
        ))
        risk_score += 0.5
    
    if redis_service.is_blacklisted(txn.receiver_id):
        triggered_rules.append(RuleDetail(
            rule="RECEIVER_BLACKLISTED",
            severity="critical",
            detail=f"Receiver {txn.receiver_id} is on blacklist",
        ))
        risk_score += 0.3
    
    # ─── Rule 2: Risk score hiện tại ───
    sender_risk = redis_service.get_risk_score(txn.sender_id)
    if sender_risk > 0.6:
        triggered_rules.append(RuleDetail(
            rule="HIGH_RISK_SCORE",
            severity="high",
            value=sender_risk,
            threshold=0.6,
            detail=f"Sender risk score {sender_risk:.2f} > threshold 0.6",
        ))
        risk_score += sender_risk * 0.3
    
    # ─── Rule 3: High velocity ───
    velocity_1h = redis_service.get_velocity(txn.sender_id, hours=1)
    if velocity_1h > 5:
        triggered_rules.append(RuleDetail(
            rule="HIGH_VELOCITY",
            severity="high",
            value=float(velocity_1h),
            threshold=5.0,
            detail=f"{velocity_1h} GD trong 1 giờ qua (threshold: 5)",
        ))
        risk_score += 0.15
    
    # ─── Rule 4: Large amount ───
    if txn.amount > 10000:
        triggered_rules.append(RuleDetail(
            rule="LARGE_AMOUNT",
            severity="high",
            value=txn.amount,
            threshold=10000.0,
            detail=f"Số tiền ${txn.amount:,.2f} > threshold $10,000",
        ))
        risk_score += 0.15
    elif txn.amount > 5000:
        triggered_rules.append(RuleDetail(
            rule="ELEVATED_AMOUNT",
            severity="medium",
            value=txn.amount,
            threshold=5000.0,
            detail=f"Số tiền ${txn.amount:,.2f} > threshold $5,000",
        ))
        risk_score += 0.08
    
    # ─── Rule 5: Structuring pattern ───
    if 900 <= txn.amount < 1000 or 9000 <= txn.amount < 10000:
        triggered_rules.append(RuleDetail(
            rule="STRUCTURING_SUSPICION",
            severity="high",
            value=txn.amount,
            threshold=1000.0 if txn.amount < 1000 else 10000.0,
            detail=f"Số tiền ${txn.amount:,.2f} ngay dưới reporting threshold",
        ))
        risk_score += 0.2
    
    # ─── Rule 6: VPN / Tor ───
    if txn.ip_address and any(
        kw in txn.ip_address.lower()
        for kw in ["vpn", "tor", "proxy", "185.220"]
    ):
        triggered_rules.append(RuleDetail(
            rule="VPN_TOR_DETECTED",
            severity="high",
            detail=f"IP {txn.ip_address} flagged as VPN/Tor/Proxy",
        ))
        risk_score += 0.15
    
    # ─── Rule 7: New/Unknown device ───
    if txn.device_id and txn.device_id.startswith("DEV_UNKNOWN"):
        triggered_rules.append(RuleDetail(
            rule="UNKNOWN_DEVICE",
            severity="medium",
            detail=f"Device {txn.device_id} không có trong profile",
        ))
        risk_score += 0.1
    
    # ─── Clamp risk score ───
    risk_score = min(risk_score, 1.0)
    
    # ─── Account flags ───
    sender_flags = AccountFlags(
        account_id=txn.sender_id,
        is_whitelisted=redis_service.is_whitelisted(txn.sender_id),
        is_blacklisted=redis_service.is_blacklisted(txn.sender_id),
        risk_score=redis_service.get_risk_score(txn.sender_id),
        velocity_1h=redis_service.get_velocity(txn.sender_id, hours=1),
        velocity_24h=redis_service.get_velocity(txn.sender_id, hours=24),
    )
    
    receiver_flags = AccountFlags(
        account_id=txn.receiver_id,
        is_whitelisted=redis_service.is_whitelisted(txn.receiver_id),
        is_blacklisted=redis_service.is_blacklisted(txn.receiver_id),
        risk_score=redis_service.get_risk_score(txn.receiver_id),
        velocity_1h=redis_service.get_velocity(txn.receiver_id, hours=1),
        velocity_24h=redis_service.get_velocity(txn.receiver_id, hours=24),
    )
    
    # ─── Routing decision ───
    if (
        sender_flags.is_whitelisted
        and not any(r.severity == "critical" for r in triggered_rules)
        and txn.amount < 1000
        and risk_score < 0.2
    ):
        risk_level = RiskLevel.GREEN
    elif (
        sender_flags.is_blacklisted
        or receiver_flags.is_blacklisted
        or any(r.severity == "critical" for r in triggered_rules)
        or risk_score > 0.9
    ):
        risk_level = RiskLevel.RED
    else:
        risk_level = RiskLevel.YELLOW
    
    # ─── Context summary cho Planner ───
    context_parts = [f"Giao dịch ${txn.amount:,.2f} từ {txn.sender_id} đến {txn.receiver_id}."]
    if triggered_rules:
        context_parts.append(f"Triggered {len(triggered_rules)} rules: " +
                             ", ".join(r.rule for r in triggered_rules) + ".")
    if sender_flags.is_blacklisted:
        context_parts.append(f"Sender {txn.sender_id} is BLACKLISTED.")
    if receiver_flags.is_blacklisted:
        context_parts.append(f"Receiver {txn.receiver_id} is BLACKLISTED.")
    if sender_flags.velocity_1h > 5:
        context_parts.append(f"Sender velocity bất thường: {sender_flags.velocity_1h} GD/1h.")
    context_summary = " ".join(context_parts)
    
    phase1 = Phase1Result(
        transaction_id=txn.transaction_id,
        risk_level=risk_level,
        risk_score=risk_score,
        triggered_rules=triggered_rules,
        sender_flags=sender_flags,
        receiver_flags=receiver_flags,
        context_summary=context_summary,
        requires_investigation=(risk_level == RiskLevel.YELLOW),
        message=f"Phase 1: {risk_level.value.upper()} (score={risk_score:.3f}, rules={len(triggered_rules)})",
    )
    
    # ─── Log ───
    color = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
    print(f"\n   Result: {color.get(risk_level.value, '?')} {risk_level.value.upper()}")
    print(f"   Risk Score: {risk_score:.3f}")
    print(f"   Rules: {len(triggered_rules)}")
    for r in triggered_rules:
        print(f"     [{r.severity.upper()}] {r.rule}: {r.detail}")
    print(f"   Sender: wl={sender_flags.is_whitelisted}, bl={sender_flags.is_blacklisted}, "
          f"risk={sender_flags.risk_score:.2f}, vel_1h={sender_flags.velocity_1h}")
    print(f"   Receiver: wl={receiver_flags.is_whitelisted}, bl={receiver_flags.is_blacklisted}, "
          f"risk={receiver_flags.risk_score:.2f}")
    
    return {
        "phase1_result": phase1.model_dump(),
        "phase1_risk_level": risk_level.value,
    }


# =====================================================================
# ROUTING: After Phase 1
# =====================================================================

def route_after_phase1(state: GraphState) -> str:
    """
    Conditional routing sau Phase 1.
    
    GREEN → "end_allow" (pass through, allow)
    RED   → "end_block" (block immediately)
    YELLOW → "planner" (cần điều tra)
    """
    risk_level = state.get("phase1_risk_level", "yellow")
    
    if risk_level == "green":
        print(f"\n   🟢 ROUTING: GREEN → ALLOW (skip investigation)")
        return "end_allow"
    elif risk_level == "red":
        print(f"\n   🔴 ROUTING: RED → BLOCK (auto-reject)")
        return "end_block"
    else:
        print(f"\n   🟡 ROUTING: YELLOW → Investigation pipeline")
        return "planner"


# =====================================================================
# NODE: END_ALLOW (Green path - skip investigation)
# =====================================================================

def end_allow(state: GraphState) -> GraphState:
    """Kết thúc GREEN: cho phép giao dịch."""
    txn = state.get("transaction", {})
    phase1 = state.get("phase1_result", {})
    
    print(f"\n   ✅ ALLOWED: {txn.get('transaction_id', '?')}")
    print(f"   Risk score: {phase1.get('risk_score', 0):.3f}")
    
    return {
        "final_decision": "allow",
        "final_message": (
            f"Transaction {txn.get('transaction_id', '?')} ALLOWED. "
            f"Sender whitelisted, low risk ({phase1.get('risk_score', 0):.3f})."
        ),
        "decision": {
            "decision": "allow",
            "confidence": 0.95,
            "reasoning": "Phase 1 GREEN: sender whitelisted, low risk, small amount",
        },
    }


# =====================================================================
# NODE: END_BLOCK (Red path - auto-block)
# =====================================================================

def end_block(state: GraphState) -> GraphState:
    """Kết thúc RED: chặn giao dịch ngay."""
    txn = state.get("transaction", {})
    phase1 = state.get("phase1_result", {})
    sender_id = txn.get("sender_id", "")
    
    print(f"\n   🚫 BLOCKED: {txn.get('transaction_id', '?')}")
    print(f"   Risk score: {phase1.get('risk_score', 0):.3f}")
    
    # Phase 3 enforcement (auto-block)
    if sender_id:
        redis_service.update_blacklist(sender_id, add=True)
        redis_service.update_risk_score(sender_id, 0.95)
        print(f"   → Blacklisted: {sender_id}")
    
    return {
        "final_decision": "block",
        "final_message": (
            f"Transaction {txn.get('transaction_id', '?')} BLOCKED. "
            f"Phase 1 RED: risk={phase1.get('risk_score', 0):.3f}."
        ),
        "decision": {
            "decision": "block",
            "confidence": 0.99,
            "reasoning": "Phase 1 RED: blacklisted sender or extreme risk score",
        },
    }


# =====================================================================
# NODE: PLANNER (LLM-driven investigation planning)
# =====================================================================

# Shared agent instances (reset per investigation)
# Protected by _processing_lock to prevent race conditions
_planner = PlannerAgent()
_executor = ExecutorAgent()
_report_agent = ReportAgent()
_detective = DetectiveAgent()
_processing_lock = threading.Lock()


def planner_node(state: GraphState) -> GraphState:
    """
    Planner Agent: tạo investigation plan bằng Gemini LLM.
    
    Nhận Phase1Result enriched → LLM phân tích → tạo tasks.
    """
    _planner.reset()
    
    txn = Transaction(**state["transaction"])
    phase1 = Phase1Result(**state["phase1_result"])
    
    request = InvestigationRequest(
        request_id=f"REQ_{uuid.uuid4().hex[:8]}",
        transaction=txn,
        phase1_result=phase1,
        priority=8 if phase1.risk_score > 0.5 else 5,
    )
    
    tasks = _planner.create_investigation_plan(request)
    
    return {
        "investigation_request": request.model_dump(),
        "current_tasks": [t.model_dump() for t in tasks],
        "all_results": [],
        "investigation_step": 0,
        "investigation_done": False,
        "planner_confidence": 0.0,
    }


# =====================================================================
# NODE: EXECUTOR (Execute tasks, collect evidence)
# =====================================================================

def executor_node(state: GraphState) -> GraphState:
    """
    Executor Agent: thực thi batch tasks, thu thập evidence.
    """
    task_dicts = state.get("current_tasks", [])
    tasks = [PlannerTask(**t) for t in task_dicts]
    
    results = _executor.execute_batch(tasks)
    
    existing_results = state.get("all_results", [])
    all_results = existing_results + [r.model_dump() for r in results]
    
    return {
        "all_results": all_results,
        "investigation_step": state.get("investigation_step", 0) + 1,
    }


# =====================================================================
# NODE: VISION (Gemini phân tích kết quả Executor)
# =====================================================================

def vision_node(state: GraphState) -> GraphState:
    """
    Vision Agent: Gemini đọc TẤT CẢ kết quả từ Executor.
    
    Cross-reference các evidence sources → phát hiện patterns ẩn.
    Trả VisionAnalysis về cho Planner đánh giá.
    """
    result_dicts = state.get("all_results", [])
    evidence = [ExecutorResult(**r) for r in result_dicts]
    
    # Lấy context cho Vision
    txn = state.get("transaction", {})
    phase1 = state.get("phase1_result", {})
    
    # FIX: Lấy hypothesis từ Planner (trước đây lấy nhầm "priority")
    hypothesis = _planner.hypothesis if _planner.hypothesis else ""
    
    investigation_context = {
        "transaction_id": txn.get("transaction_id", ""),
        "sender_id": txn.get("sender_id", ""),
        "receiver_id": txn.get("receiver_id", ""),
        "amount": txn.get("amount", 0),
        "initial_risk_score": phase1.get("risk_score", 0),
    }
    
    # Gọi Vision Agent (Gemini 2.5 Flash)
    analysis = vision_agent.analyze_results(
        evidence=evidence,
        hypothesis=hypothesis,
        investigation_context=investigation_context,
    )
    
    return {"vision_analysis": analysis}


# =====================================================================
# NODE: PLANNER EVALUATE (Planner đánh giá Vision analysis)
# =====================================================================

def planner_evaluate_node(state: GraphState) -> GraphState:
    """
    Planner nhận Vision analysis → quyết định:
    - Đủ evidence → done, chuyển sang Report
    - Chưa đủ → tạo follow-up tasks → quay lại Executor
    """
    result_dicts = state.get("all_results", [])
    evidence = [ExecutorResult(**r) for r in result_dicts]
    vision_analysis = state.get("vision_analysis", {})
    
    # FIX: Planner evaluate VỚI vision_analysis (trước đây bị bỏ qua)
    is_done, follow_up_tasks = _planner.evaluate_evidence(
        evidence, vision_analysis=vision_analysis
    )
    
    # Xem xét Vision recommendation
    vision_action = vision_analysis.get("recommended_action", "investigate_more")
    vision_risk = vision_analysis.get("overall_risk_level", "unknown")
    
    # Nếu Vision nói sufficient + planner cũng done → chắc chắn done
    # Nếu Vision nói investigate_more nhưng đã max steps → force done
    step = state.get("investigation_step", 1)
    max_steps = settings.max_investigation_steps
    
    if is_done or vision_action == "sufficient_for_report":
        print(f"   📋 PLANNER: Đủ evidence (vision: {vision_action}, risk: {vision_risk})")
        return {
            "investigation_done": True,
            "planner_confidence": _planner.current_confidence,
            "current_tasks": [],
        }
    elif step >= max_steps:
        print(f"   ⏰ PLANNER: Max steps ({max_steps}) reached, forcing report")
        return {
            "investigation_done": True,
            "planner_confidence": _planner.current_confidence,
            "current_tasks": [],
        }
    elif follow_up_tasks:
        print(f"   🔄 PLANNER: Cần thêm {len(follow_up_tasks)} tasks (step {step}/{max_steps})")
        return {
            "investigation_done": False,
            "planner_confidence": _planner.current_confidence,
            "current_tasks": [t.model_dump() for t in follow_up_tasks],
        }
    else:
        # No follow-up but not explicitly done → force done
        print(f"   📋 PLANNER: No follow-up tasks, proceeding to report")
        return {
            "investigation_done": True,
            "planner_confidence": _planner.current_confidence,
            "current_tasks": [],
        }


def route_after_evaluate(state: GraphState) -> str:
    """
    Routing sau evaluate:
    - done → report_generator
    - not done → executor (loop)
    """
    if state.get("investigation_done", True):
        return "report_generator"
    else:
        return "executor"


# =====================================================================
# NODE: REPORT GENERATOR (Gemini 2.5 Flash)
# =====================================================================

def report_generator_node(state: GraphState) -> GraphState:
    """
    Report Agent: generate investigation report bằng Gemini.
    """
    request_dict = state.get("investigation_request", {})
    result_dicts = state.get("all_results", [])
    evidence = [ExecutorResult(**r) for r in result_dicts]
    
    request_id = request_dict.get("request_id", "unknown")
    txn_id = state.get("transaction", {}).get("transaction_id", "unknown")
    
    investigation_summary = _planner.get_investigation_summary()
    
    report = _report_agent.generate_report(
        request_id=request_id,
        transaction_id=txn_id,
        investigation_summary=investigation_summary,
        evidence=evidence,
    )
    
    return {"report": report.model_dump()}


# =====================================================================
# NODE: DETECTIVE (Final adjudication)
# =====================================================================

def detective_node(state: GraphState) -> GraphState:
    """
    Detective Agent: final adjudication bằng Gemini LLM.
    """
    report_dict = state.get("report", {})
    
    # Reconstruct ExecutorResult objects for evidence
    evidence_dicts = report_dict.get("evidence", [])
    evidence = []
    for ed in evidence_dicts:
        # Convert task_type string back to enum
        if isinstance(ed.get("task_type"), str):
            ed["task_type"] = TaskType(ed["task_type"])
        evidence.append(ExecutorResult(**ed))
    
    # Reconstruct recommended_decision
    rec_decision = report_dict.get("recommended_decision", "escalate")
    if isinstance(rec_decision, str):
        report_dict["recommended_decision"] = FinalDecision(rec_decision)
    
    report_dict["evidence"] = evidence
    report = InvestigationReport(**report_dict)
    
    # Pass sender_id từ transaction state làm fallback
    txn_sender_id = state.get("transaction", {}).get("sender_id", "")
    
    result = _detective.adjudicate(report, sender_id_fallback=txn_sender_id)
    
    return {
        "decision": result.model_dump(),
        "final_decision": result.decision.value,
        "final_message": (
            f"Transaction {result.transaction_id}: "
            f"{result.decision.value.upper()} "
            f"(confidence={result.confidence:.2f}). "
            f"{result.reasoning[:100]}"
        ),
    }


# =====================================================================
# BUILD LANGGRAPH PIPELINE
# =====================================================================

def build_pipeline() -> StateGraph:
    """
    Xây dựng LangGraph pipeline.
    
    Graph structure:
    
    START → phase1_screening
            ├── GREEN → end_allow → END
            ├── RED → end_block → END
            └── YELLOW → planner → executor → vision → planner_evaluate
                                                        ├── done → report → detective → END
                                                        └── not_done → executor (loop)
    """
    graph = StateGraph(GraphState)
    
    # ─── Add nodes ───
    graph.add_node("phase1_screening", phase1_screening)
    graph.add_node("end_allow", end_allow)
    graph.add_node("end_block", end_block)
    graph.add_node("planner", planner_node)
    graph.add_node("executor", executor_node)
    graph.add_node("vision", vision_node)
    graph.add_node("planner_evaluate", planner_evaluate_node)
    graph.add_node("report_generator", report_generator_node)
    graph.add_node("detective", detective_node)
    
    # ─── Set entry point ───
    graph.set_entry_point("phase1_screening")
    
    # ─── Conditional routing after Phase 1 ───
    graph.add_conditional_edges(
        "phase1_screening",
        route_after_phase1,
        {
            "end_allow": "end_allow",
            "end_block": "end_block",
            "planner": "planner",
        },
    )
    
    # ─── Green/Red paths → END ───
    graph.add_edge("end_allow", END)
    graph.add_edge("end_block", END)
    
    # ─── Investigation pipeline (NEW FLOW) ───
    # Planner → Executor → Vision → Planner Evaluate
    graph.add_edge("planner", "executor")
    graph.add_edge("executor", "vision")
    graph.add_edge("vision", "planner_evaluate")
    
    # ─── Conditional: planner_evaluate → report or loop ───
    graph.add_conditional_edges(
        "planner_evaluate",
        route_after_evaluate,
        {
            "report_generator": "report_generator",
            "executor": "executor",
        },
    )
    
    # ─── Report → Detective → END ───
    graph.add_edge("report_generator", "detective")
    graph.add_edge("detective", END)
    
    return graph


# =====================================================================
# ORCHESTRATOR CLASS (Wrapper for convenience)
# =====================================================================

class FraudDetectionOrchestrator:
    """
    High-level wrapper cho LangGraph pipeline.
    
    Dùng trong main.py:
        orchestrator = FraudDetectionOrchestrator()
        orchestrator.initialize()
        result = orchestrator.process_transaction(txn)
    """
    
    def __init__(self):
        self.graph = None
        self.app = None
        self._initialized = False
    
    def initialize(self):
        """
        Khởi tạo pipeline + seed demo data.
        
        Gọi 1 lần khi startup:
        - Seed Neo4j (nếu connected)
        - Seed ChromaDB knowledge base
        - Build LangGraph pipeline
        """
        if self._initialized:
            return
        
        print("\n" + "=" * 70)
        print(" FRAUD DETECTION SYSTEM - Initializing")
        print("=" * 70)
        
        # ─── Seed databases ───
        print("\n📊 Seeding databases...")
        redis_service.seed_data()
        neo4j_client.seed_demo_data()
        vector_store.seed_knowledge_base()
        mongodb_client.seed_demo_data()
        
        # ─── Build pipeline ───
        print("\n🔗 Building LangGraph pipeline...")
        self.graph = build_pipeline()
        self.app = self.graph.compile()
        
        self._initialized = True
        
        print("\n✅ System ready!")
        print(f"   Redis: {'Cloud (' + settings.redis_host + ')' if redis_service.is_connected else 'Simulator (in-memory)'}")
        print(f"   Neo4j: {'AuraDB (cloud)' if neo4j_client.is_connected else 'Simulator (in-memory)'}")
        print(f"   MongoDB: {'Atlas (cloud)' if mongodb_client.is_connected else 'Simulator (in-memory)'}")
        print(f"   LLM (ALL agents): Gemini {'(connected)' if settings.gemini_api_key else '(fallback)'}")
        print("=" * 70 + "\n")
    
    def process_transaction(self, transaction: Transaction) -> dict:
        """
        Xử lý 1 giao dịch qua pipeline LangGraph.
        
        Returns:
            dict với final_decision, final_message, và full state
        """
        if not self._initialized:
            self.initialize()
        
        print(f"\n{'*'*70}")
        print(f" PROCESSING: {transaction.transaction_id}")
        print(f" {transaction.sender_id} → {transaction.receiver_id}: ${transaction.amount:,.2f}")
        print(f"{'*'*70}")
        
        # ─── Run LangGraph pipeline (thread-safe) ───
        initial_state: GraphState = {
            "transaction": transaction.model_dump(),
            "phase1_result": None,
            "phase1_risk_level": "",
            "investigation_request": None,
            "current_tasks": [],
            "all_results": [],
            "investigation_step": 0,
            "investigation_done": False,
            "planner_confidence": 0.0,
            "vision_analysis": None,
            "report": None,
            "decision": None,
            "final_decision": "",
            "final_message": "",
            "error": None,
        }
        
        # FIX: Lock prevents concurrent access to shared agent instances
        with _processing_lock:
            _planner.reset()
            try:
                final_state = self.app.invoke(initial_state)
            except Exception as e:
                print(f"\n❌ Pipeline error: {e}")
                import traceback
                traceback.print_exc()
                final_state = {
                    **initial_state,
                    "final_decision": "escalate",
                    "final_message": f"Pipeline error: {str(e)}. Escalating to human review.",
                    "error": str(e),
                }
        
        # ─── Summary ───
        decision = final_state.get("final_decision", "escalate")
        message = final_state.get("final_message", "Unknown")
        
        symbols = {"allow": "✅", "block": "🚫", "escalate": "⚠️"}
        
        print(f"\n{'*'*70}")
        print(f" RESULT: {symbols.get(decision, '?')} {decision.upper()}")
        print(f" {message[:150]}")
        print(f"{'*'*70}")
        
        # ─── In báo cáo chi tiết (nếu có) ───
        report = final_state.get("report")
        if report and isinstance(report, dict):
            detailed = report.get("detailed_analysis", "")
            if detailed:
                print(f"\n{'─'*70}")
                print("📄 BÁO CÁO ĐIỀU TRA CHI TIẾT")
                print(f"{'─'*70}")
                print(detailed)
                print(f"{'─'*70}")
        
        print()
        
        # ─── Store audit trail to Redis (ref: fraud-detection/phase1.py._finalize) ───
        redis_service.store_transaction_result(transaction.transaction_id, {
            "decision": decision,
            "confidence": str(final_state.get("decision", {}).get("confidence", 0)),
            "sender": transaction.sender_id,
            "receiver": transaction.receiver_id,
            "amount": str(transaction.amount),
            "timestamp": datetime.now().isoformat(),
        })
        
        return final_state
    
    def shutdown(self):
        """Cleanup khi tắt app — đóng tất cả DB connections."""
        neo4j_client.close()
        mongodb_client.close()
        print("🔌 System shutdown complete.")
