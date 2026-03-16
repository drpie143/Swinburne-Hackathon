# ====================================================================
# PLANNER_AGENT.PY - Agent Lập Kế Hoạch Điều Tra (Gemini 2.5 Flash)
# ====================================================================
#
# Planner dùng Gemini 2.5 Flash để tạo kế hoạch điều tra ĐỘNG
# dựa trên context từ Phase 1.
#
# LLM-driven dynamic planning:
#   - Nhận Phase1Result ENRICHED (risk details, velocity, flags)
#   - Gemini LLM phân tích context → tạo HYPOTHESIS cụ thể
#   - Decompose thành tasks PHÙ HỢP với từng case
#   - Ví dụ:
#     * Velocity cao + amount nhỏ → hypothesis "structuring"
#       → plan: velocity check + amount pattern + KB search structuring
#     * VPN + new account + large amount → hypothesis "ATO hoặc money laundering"
#       → plan: device analysis + graph query + behavioral + KB search ATO
#     * Receiver blacklisted → hypothesis "money mule"
#       → plan: graph query (deep) + KB search mule + velocity
#
# FLOW:
#   Phase1Result (enriched)
#       ↓
#   [Gemini LLM: phân tích context, tạo hypothesis]
#       ↓
#   [Gemini LLM: decompose thành PlannerTask[]]
#       ↓
#   [Gửi cho Executor]
#       ↓
#   [Nhận results → Gemini LLM: evaluate → thêm tasks nếu cần]
#       ↓
#   [Đủ confidence → gửi cho Report Agent]
# ====================================================================

from __future__ import annotations
import json
import uuid
from typing import Optional

from models import (
    Transaction, Phase1Result, InvestigationRequest,
    PlannerTask, ExecutorResult, TaskType
)
from config import settings
from llm_providers import gemini_provider_planner as gemini_provider


# =====================================================================
# SYSTEM PROMPT - Định nghĩa vai trò của Planner Agent
# =====================================================================

PLANNER_SYSTEM_PROMPT = """Bạn là PLANNER AGENT trong hệ thống phát hiện gian lận ngân hàng.

NHIỆM VỤ: Nhận thông tin giao dịch nghi ngờ + kết quả screening Phase 1 → tạo KẾ HOẠCH ĐIỀU TRA.

CÁC LOẠI TASK CÓ THỂ TẠO (TỔNG HỢP — mỗi task bao phủ NHIỀU khía cạnh):
1. account_profiling - TỔNG HỢP: Phân tích hành vi + lịch sử + mẫu số tiền của sender VÀ receiver từ MongoDB Atlas
   → Bao gồm: account age, KYC status, transaction history, baseline spending, structuring patterns (<$1000/$10000), round amounts, outliers, velocity
   → Executor sẽ query TOÀN BỘ MongoDB data cần thiết trong 1 task

2. network_analysis - TỔNG HỢP: Phân tích mạng lưới quan hệ + thiết bị/IP từ Neo4j graph DB
   → Bao gồm: shared devices/IPs, mule networks, circular flows, device fingerprint, VPN/Tor detection, geo-anomaly, blacklisted entities
   → Executor sẽ query TOÀN BỘ Neo4j data cần thiết trong 1 task

3. knowledge_retrieval - Tìm fraud patterns tương tự trong ChromaDB (RAG): structuring, mule, ATO, APP fraud
   → So sánh case hiện tại với các patterns đã biết

QUAN TRỌNG — LẬP KẾ HOẠCH THÔNG MINH:
- PHÂN TÍCH dữ liệu Phase 1 → quyết định CẦN TASK NÀO, KHÔNG cần task nào
- Số lượng tasks KHÔNG CỐ ĐỊNH — có thể 2, 3, hoặc 4,... tùy context:
  • Giao dịch đơn giản (amount thấp, sender whitelisted) → 2 tasks có thể đủ
  • Giao dịch phức tạp (multiple red flags, mule network) → 3-4 tasks
- KHÔNG máy móc tạo cùng 1 kế hoạch cho mọi giao dịch — mỗi case là khác nhau
- Mỗi task phải MÔ TẢ CHI TIẾT để Executor biết cần query những gì
- KHÔNG tách nhỏ thêm (ví dụ: KHÔNG tạo riêng behavioral + amount_pattern, gộp vào account_profiling)

QUY TẮC:
- Phân tích KỸ context từ Phase 1 để hiểu TẠI SAO giao dịch bị flag
- Tạo HYPOTHESIS (giả thuyết gian lận) cụ thể (chỉ tạo những task thực sự cần thiết, không phải lúc nào cũng làm tất cả, và tùy vào dữ liệu nhận được mà thứ tự hoặc mỗi task có thể không theo thứ tự hoặc không giống nhau, cần gì tạo nấy)
- Gán priority: 10 (cao nhất) → 1 (thấp nhất)

RESPONSE FORMAT (JSON):
{
    "hypothesis": "Mô tả giả thuyết gian lận dựa trên Phase 1 context",
    "reasoning": "Giải thích tại sao chọn các tasks này",
    "tasks": [
        {
            "task_type": "account_profiling|network_analysis|knowledge_retrieval",
            "description": "Mô tả CHI TIẾT tất cả data cần query trong task này",
            "priority": 1-10
        }
    ]
}

CHỈ TRẢ JSON HỢP LỆ. KHÔNG thêm text, KHÔNG markdown, KHÔNG giải thích ngoài JSON."""

EVALUATE_SYSTEM_PROMPT = """Bạn là PLANNER AGENT đang ĐÁNH GIÁ bằng chứng thu thập được.

NHIỆM VỤ: Xem xét evidence mới từ Executor → quyết định:
1. ĐỦ bằng chứng → kết thúc điều tra (done=true)
2. CẦN THÊM → tạo follow-up tasks (done=false)

QUY TẮC:
- Nếu đã có ≥3 risk indicators mạnh → đủ để kết luận
- Nếu evidence mâu thuẫn → cần thêm data
- Nếu phát hiện pattern mới cần explore → tạo follow-up
- KHÔNG tạo quá 2 follow-up tasks mỗi lần
- Tính confidence (0.0 - 1.0) dựa trên quality & quantity of evidence

RESPONSE FORMAT (JSON):
{
    "done": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "Giải thích quyết định",
    "follow_up_tasks": [
        {
            "task_type": "...",
            "description": "...",
            "priority": 1-10
        }
    ]
}

CHỈ TRẢ JSON HỢP LỆ. KHÔNG thêm text, KHÔNG markdown, KHÔNG giải thích ngoài JSON."""


class PlannerAgent:
    """
    Planner Agent - Orchestrator điều tra (Gemini LLM-driven).
    
    Thay đổi chính so với bản cũ:
    - Dùng Gemini 2.5 Flash để reasoning (thay vì rule-based)
    - Nhận Phase1Result enriched → tạo plan ĐỘNG
    - Follow-up tasks cũng do LLM quyết định
    """
    
    def __init__(self):
        self.accumulated_evidence: list[ExecutorResult] = []
        self.current_confidence: float = 0.0
        self.step_count: int = 0
        self.max_steps: int = settings.max_investigation_steps
        self.confidence_threshold: float = settings.confidence_threshold
        self.investigation_context: dict = {}
        self.hypothesis: str = ""
    
    def create_investigation_plan(
        self,
        request: InvestigationRequest
    ) -> list[PlannerTask]:
        """
        TẠO KẾ HOẠCH ĐIỀU TRA ĐỘNG bằng Gemini LLM.
        
        Thay vì rule-based cứng nhắc, giờ:
        1. Tổng hợp TOÀN BỘ context từ Phase1Result enriched
        2. Gửi cho Gemini LLM với system prompt
        3. LLM phân tích context → tạo hypothesis → decompose tasks
        4. Parse JSON response → list[PlannerTask]
        
        Kết quả: Mỗi giao dịch khác nhau → kế hoạch khác nhau!
        """
        txn = request.transaction
        phase1 = request.phase1_result
        
        # Lưu context
        self.investigation_context = {
            "transaction_id": txn.transaction_id,
            "sender_id": txn.sender_id,
            "receiver_id": txn.receiver_id,
            "amount": txn.amount,
            "initial_risk_score": phase1.risk_score,
        }
        
        # ─── Tạo user message với TOÀN BỘ context enriched ───
        user_message = self._build_context_message(txn, phase1)
        
        print(f"\n{'='*60}")
        print(f"📋 PLANNER (Gemini LLM): Đang phân tích context...")
        print(f"{'='*60}")
        
        # ─── Gọi Gemini LLM ───
        llm_response = gemini_provider.chat_json(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_message=user_message,
        )
        
        # ─── Parse response thành PlannerTask[] ───
        tasks = self._parse_plan_response(llm_response)
        
        self.hypothesis = llm_response.get("hypothesis", "Không xác định")
        
        print(f"   🧠 Hypothesis: {self.hypothesis}")
        print(f"   💡 Reasoning: {llm_response.get('reasoning', 'N/A')[:150]}")
        print(f"   📋 Tasks: {len(tasks)}")
        for i, task in enumerate(tasks, 1):
            print(f"      {i}. [{task.task_type.value}] (priority={task.priority})")
            print(f"         {task.description[:120]}")
        print(f"{'='*60}\n")
        
        return tasks
    
    def _build_context_message(self, txn: Transaction, phase1: Phase1Result) -> str:
        """
        Xây dựng message chi tiết cho Gemini LLM.
        
        Message chứa TOÀN BỘ enriched context từ Phase 1:
        - Thông tin giao dịch
        - Chi tiết rules đã trigger (severity, value, threshold)
        - Account flags (whitelist/blacklist/risk/velocity)
        - Context summary
        
        → LLM đọc message này → hiểu chính xác tình huống
        → Tạo plan phù hợp
        """
        lines = [
            "=== GIAO DỊCH NGHI NGỜ ===",
            f"Transaction ID: {txn.transaction_id}",
            f"Sender: {txn.sender_id} ({txn.sender_name})",
            f"Receiver: {txn.receiver_id} ({txn.receiver_name})",
            f"Amount: ${txn.amount:,.2f} {txn.currency}",
            f"Type: {txn.transaction_type}",
            f"Channel: {txn.channel}",
            f"Device: {txn.device_id or 'N/A'}",
            f"IP: {txn.ip_address or 'N/A'}",
            f"Location: {txn.location or 'N/A'}",
            "",
            "=== KẾT QUẢ PHASE 1 (Real-Time Screening) ===",
            f"Risk Level: {phase1.risk_level.value.upper()}",
            f"Risk Score: {phase1.risk_score:.3f}",
        ]
        
        # ─── Chi tiết rules trigger ───
        if phase1.triggered_rules:
            lines.append(f"\nRules Triggered ({len(phase1.triggered_rules)}):")
            for rule in phase1.triggered_rules:
                lines.append(f"  - [{rule.severity.upper()}] {rule.rule}: {rule.detail}")
                if rule.value is not None:
                    lines.append(f"    Value: {rule.value}, Threshold: {rule.threshold}")
        
        # ─── Account flags từ Redis ───
        if phase1.sender_flags:
            sf = phase1.sender_flags
            lines.extend([
                f"\nSender Flags ({sf.account_id}):",
                f"  Whitelisted: {sf.is_whitelisted}",
                f"  Blacklisted: {sf.is_blacklisted}",
                f"  Risk Score: {sf.risk_score:.2f}",
                f"  Velocity 1h: {sf.velocity_1h} GD",
                f"  Velocity 24h: {sf.velocity_24h} GD",
            ])
        
        if phase1.receiver_flags:
            rf = phase1.receiver_flags
            lines.extend([
                f"\nReceiver Flags ({rf.account_id}):",
                f"  Whitelisted: {rf.is_whitelisted}",
                f"  Blacklisted: {rf.is_blacklisted}",
                f"  Risk Score: {rf.risk_score:.2f}",
                f"  Velocity 1h: {rf.velocity_1h} GD",
                f"  Velocity 24h: {rf.velocity_24h} GD",
            ])
        
        # ─── Context summary ───
        if phase1.context_summary:
            lines.extend([
                f"\nContext Summary:",
                phase1.context_summary,
            ])
        
        lines.append("\n=== YÊU CẦU ===")
        lines.append("Hãy phân tích context trên, đưa ra hypothesis, và tạo kế hoạch điều tra phù hợp.")
        
        return "\n".join(lines)
    
    def _parse_plan_response(self, response: dict) -> list[PlannerTask]:
        """
        Parse JSON response từ LLM thành list[PlannerTask].
        
        Xử lý graceful: nếu LLM trả format sai → fallback tasks.
        """
        tasks = []
        
        # Map string → TaskType enum (consolidated + legacy)
        type_map = {
            # Consolidated types (mới)
            "account_profiling": TaskType.ACCOUNT_PROFILING,
            "network_analysis": TaskType.NETWORK_ANALYSIS,
            # Legacy types (backward compat)
            "graph_query": TaskType.GRAPH_QUERY,
            "behavioral_analysis": TaskType.BEHAVIORAL_ANALYSIS,
            "knowledge_retrieval": TaskType.KNOWLEDGE_RETRIEVAL,
            "device_analysis": TaskType.DEVICE_ANALYSIS,
            "amount_pattern": TaskType.AMOUNT_PATTERN,
        }
        
        raw_tasks = response.get("tasks", [])
        
        if not raw_tasks:
            # Fallback: tạo basic plan nếu LLM không trả tasks
            return self._fallback_plan()
        
        for raw in raw_tasks:
            task_type_str = raw.get("task_type", "").lower().strip()
            task_type = type_map.get(task_type_str)
            
            if not task_type:
                print(f"   ⚠️  Unknown task_type '{task_type_str}' — skipped")
                continue
            
            task_id = f"task_{uuid.uuid4().hex[:8]}"
            
            # Parse depends_on (list[str] task_ids)
            depends_on = []
            for dep_idx in raw.get("depends_on", []):
                if isinstance(dep_idx, int) and dep_idx < len(tasks):
                    depends_on.append(tasks[dep_idx].task_id)
            
            tasks.append(PlannerTask(
                task_id=task_id,
                task_type=task_type,
                description=raw.get("description", f"Execute {task_type_str}"),
                query=raw.get("query", ""),
                priority=raw.get("priority", 5),
                depends_on=depends_on,
            ))
        
        # Sắp xếp theo priority
        tasks.sort(key=lambda t: t.priority, reverse=True)
        return tasks
    
    def _fallback_plan(self) -> list[PlannerTask]:
        """Fallback plan khi LLM không available hoặc response lỗi."""
        ctx = self.investigation_context
        return [
            PlannerTask(
                task_id=f"task_{uuid.uuid4().hex[:8]}",
                task_type=TaskType.ACCOUNT_PROFILING,
                description=f"Phân tích hành vi + lịch sử giao dịch + mẫu số tiền của sender {ctx.get('sender_id', '')} và receiver {ctx.get('receiver_id', '')}",
                priority=10,
            ),
            PlannerTask(
                task_id=f"task_{uuid.uuid4().hex[:8]}",
                task_type=TaskType.NETWORK_ANALYSIS,
                description=f"Truy vấn graph cho sender {ctx.get('sender_id', '')} và receiver {ctx.get('receiver_id', '')}: mạng lưới quan hệ, thiết bị, IP, circular flows",
                priority=9,
            ),
            PlannerTask(
                task_id=f"task_{uuid.uuid4().hex[:8]}",
                task_type=TaskType.KNOWLEDGE_RETRIEVAL,
                description="Tìm fraud patterns tương tự trong knowledge base",
                priority=6,
            ),
        ]
    
    def evaluate_evidence(
        self,
        new_results: list[ExecutorResult],
        vision_analysis: dict | None = None,
    ) -> tuple[bool, Optional[list[PlannerTask]]]:
        """
        ĐÁNH GIÁ bằng chứng bằng Gemini LLM.
        
        LLM nhận:
        - Evidence mới từ Executor
        - Evidence tích lũy trước đó
        - Hypothesis ban đầu
        - Vision Agent analysis (cross-reference, patterns)
        → Quyết định: đủ rồi hay cần thêm?
        """
        self.step_count += 1
        self.accumulated_evidence.extend(new_results)
        
        print(f"\n{'─'*50}")
        print(f"🔍 PLANNER (Gemini LLM): Đánh giá evidence (Step {self.step_count}/{self.max_steps})")
        print(f"{'─'*50}")
        
        # Bounded execution: check max steps trước
        if self.step_count >= self.max_steps:
            self.current_confidence = self._calculate_confidence()
            print(f"   ⏹️  Max steps reached. Confidence: {self.current_confidence:.2f}")
            return True, None
        
        # ─── Tạo evidence summary cho LLM ───
        evidence_text = self._summarize_evidence()
        
        # ─── Thêm Vision analysis nếu có ───
        vision_text = ""
        if vision_analysis:
            vision_text = (
                f"\n=== VISION AGENT ANALYSIS ===\n"
                f"Summary: {vision_analysis.get('summary', 'N/A')}\n"
                f"Risk Level: {vision_analysis.get('overall_risk_level', 'N/A')}\n"
                f"Patterns: {vision_analysis.get('patterns_detected', [])}\n"
                f"Cross-references: {vision_analysis.get('cross_references', [])}\n"
                f"Recommendation: {vision_analysis.get('recommended_action', 'N/A')}\n"
            )
        
        user_message = (
            f"=== HYPOTHESIS ===\n{self.hypothesis}\n\n"
            f"=== EVIDENCE THU THẬP ({len(self.accumulated_evidence)} sources) ===\n"
            f"{evidence_text}\n"
            f"{vision_text}\n"
            f"=== STEP ===\n"
            f"Step {self.step_count}/{self.max_steps}\n\n"
            f"Hãy đánh giá: đủ evidence chưa? Cần thêm gì?"
        )
        
        llm_response = gemini_provider.chat_json(
            system_prompt=EVALUATE_SYSTEM_PROMPT,
            user_message=user_message,
        )
        
        is_done = llm_response.get("done", True)
        self.current_confidence = llm_response.get("confidence", self._calculate_confidence())
        reasoning = llm_response.get("reasoning", "")
        
        print(f"   Confidence: {self.current_confidence:.2f}")
        print(f"   Done: {is_done}")
        print(f"   Reasoning: {reasoning[:100]}")
        
        # Check confidence threshold
        if self.current_confidence >= self.confidence_threshold:
            print(f"   ✅ Confidence đủ cao → kết thúc")
            return True, None
        
        if is_done:
            return True, None
        
        # Parse follow-up tasks
        follow_ups = self._parse_plan_response(
            {"tasks": llm_response.get("follow_up_tasks", [])}
        )
        
        if follow_ups:
            print(f"   🔄 {len(follow_ups)} follow-up tasks")
            return False, follow_ups
        
        return True, None
    
    def _summarize_evidence(self) -> str:
        """Tóm tắt tất cả evidence cho LLM evaluation."""
        lines = []
        for result in self.accumulated_evidence:
            status = "✅" if result.success else "❌"
            lines.append(f"\n{status} [{result.task_type.value}]:")
            lines.append(f"   Analysis: {result.analysis[:200]}")
            if result.risk_indicators:
                lines.append(f"   Risk Indicators ({len(result.risk_indicators)}):")
                for ri in result.risk_indicators[:5]:
                    lines.append(f"     - {ri}")
        return "\n".join(lines)
    
    def _calculate_confidence(self) -> float:
        """Tính confidence score dựa trên evidence."""
        risk_count = sum(
            len(r.risk_indicators) for r in self.accumulated_evidence
        )
        evidence_count = len(self.accumulated_evidence)
        
        risk_conf = min(risk_count * 0.12, 0.7)
        coverage_conf = min(evidence_count * 0.08, 0.3)
        
        return min(max(risk_conf + coverage_conf, 0.1), 1.0)
    
    def get_investigation_summary(self) -> dict:
        """Tạo tóm tắt điều tra cho Report Agent."""
        all_risk = []
        all_mitigating = []
        
        for r in self.accumulated_evidence:
            all_risk.extend(r.risk_indicators)
            if any(w in r.analysis.lower() for w in ["normal", "consistent", "verified", "✅"]):
                all_mitigating.append(r.analysis[:100])
        
        return {
            "context": self.investigation_context,
            "hypothesis": self.hypothesis,
            "total_steps": self.step_count,
            "confidence": self.current_confidence,
            "evidence_count": len(self.accumulated_evidence),
            "risk_indicators": list(set(all_risk)),
            "mitigating_factors": all_mitigating,
            "evidence": [
                {
                    "task_id": r.task_id,
                    "task_type": r.task_type.value,
                    "success": r.success,
                    "analysis": r.analysis,
                    "risk_indicators": r.risk_indicators,
                }
                for r in self.accumulated_evidence
            ],
        }
    
    def reset(self):
        """Reset cho investigation mới."""
        self.accumulated_evidence = []
        self.current_confidence = 0.0
        self.step_count = 0
        self.investigation_context = {}
        self.hypothesis = ""
