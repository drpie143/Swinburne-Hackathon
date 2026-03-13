# ====================================================================
# DETECTIVE_AGENT.PY - Agent Ra Quyết Định (Gemini 2.5 Flash)
# ====================================================================
#
# Gemini 2.5 Flash đánh giá INDEPENDENT
# → Reasoning chi tiết, quyết định linh hoạt hơn
#
# PHASE 3 ENFORCEMENT vẫn giữ nguyên:
#   BLOCK → blacklist + risk score + index pattern
#   ALLOW → whitelist + giảm risk score
#   ESCALATE → hold + notify human reviewer
# ====================================================================

from __future__ import annotations
import json
from models import InvestigationReport, DecisionResult, FinalDecision
from simulators import redis_service
from vector_store import vector_store
from llm_providers import gemini_provider_detective as gemini_provider


DETECTIVE_SYSTEM_PROMPT = """Bạn là DETECTIVE AGENT - thẩm phán cuối cùng trong hệ thống phát hiện gian lận ngân hàng.

NHIỆM VỤ: Nhận báo cáo điều tra → ra quyết định cuối cùng.

QUYẾT ĐỊNH CÓ THỂ:
1. BLOCK - Gian lận xác nhận. Chặn giao dịch, blacklist account, cập nhật risk score.
2. ALLOW - Giao dịch hợp lệ. Cho phép, whitelist account, giảm risk score.
3. ESCALATE - Không đủ bằng chứng. Chuyển cho human reviewer, tạm giữ giao dịch.

QUY TẮC:
- ĐỘC LẬP đánh giá (không chỉ theo recommendation)
- Ưu tiên AN TOÀN: nghi ngờ thì block/escalate, KHÔNG dễ dãi allow
- Nếu có critical risk (blacklist, circular flow, mule) → BLOCK
- Nếu chỉ medium risk + mitigating → ESCALATE
- Nếu không có risk + nhiều mitigating → ALLOW
- Confidence phải > 0.7 để auto-decide (BLOCK/ALLOW). Dưới 0.7 → ESCALATE

RESPONSE FORMAT (JSON):
{
    "decision": "allow" | "block" | "escalate",
    "confidence": 0.0-1.0,
    "reasoning": "Giải thích chi tiết",
    "risk_assessment": {
        "critical": ["list critical risks"],
        "high": ["list high risks"],
        "medium": ["list medium risks"]
    },
    "actions": ["list enforcement actions"]
}"""


class DetectiveAgent:
    """
    Detective Agent - Final Adjudication (Gemini 2.5 Flash).
    
    Đánh giá INDEPENDENT bằng LLM:
    - Re-evaluate risk factors
    - Check critical indicators
    - Make final call: ALLOW/BLOCK/ESCALATE
    - Trigger Phase 3 enforcement
    """
    
    def adjudicate(self, report: InvestigationReport, sender_id_fallback: str = "") -> DecisionResult:
        """
        Ra quyết định cuối cùng bằng Gemini LLM.
        
        Args:
            report: Báo cáo điều tra từ Report Agent
            sender_id_fallback: sender_id từ transaction (fallback khi evidence thiếu)
        """
        print(f"\n{'='*60}")
        print(f"🕵️ DETECTIVE (Gemini LLM): Phân tích và ra quyết định...")
        print(f"{'='*60}")
        
        # ─── Tạo prompt cho LLM ───
        user_message = self._build_adjudication_message(report)
        
        # ─── Gọi Gemini LLM ───
        llm_response = gemini_provider.chat_json(
            system_prompt=DETECTIVE_SYSTEM_PROMPT,
            user_message=user_message,
        )
        
        # ─── Parse response ───
        decision_str = llm_response.get("decision", "escalate").lower()
        decision_map = {
            "allow": FinalDecision.ALLOW,
            "block": FinalDecision.BLOCK,
            "escalate": FinalDecision.ESCALATE,
        }
        decision = decision_map.get(decision_str, FinalDecision.ESCALATE)
        confidence = llm_response.get("confidence", report.confidence_score)
        reasoning = llm_response.get("reasoning", "LLM-based adjudication")
        
        # Log risk assessment
        risk_assessment = llm_response.get("risk_assessment", {})
        print(f"\n   Risk Assessment:")
        print(f"     🔴 Critical: {risk_assessment.get('critical', [])}")
        print(f"     🟠 High: {risk_assessment.get('high', [])}")
        print(f"     🟡 Medium: {risk_assessment.get('medium', [])}")
        
        # ─── Phase 3 Enforcement ───
        actions = llm_response.get("actions", [])
        sender_id = self._extract_sender_id(report) or sender_id_fallback
        
        self._enforce_decision(decision, sender_id, report, actions)
        
        result = DecisionResult(
            request_id=report.request_id,
            transaction_id=report.transaction_id,
            decision=decision,
            confidence=confidence,
            reasoning=reasoning,
            actions=actions,
            investigation_report=report,
        )
        
        print(f"\n   📌 DECISION: {decision.value.upper()}")
        print(f"   📌 Confidence: {confidence:.2f}")
        print(f"   📌 Reasoning: {reasoning[:150]}")
        print(f"{'='*60}\n")
        
        return result
    
    def _build_adjudication_message(self, report: InvestigationReport) -> str:
        """Tạo prompt chi tiết cho Detective LLM."""
        lines = [
            f"=== BÁO CÁO ĐIỀU TRA ===",
            f"Transaction: {report.transaction_id}",
            f"Summary: {report.summary}",
            f"Report confidence: {report.confidence_score:.2f}",
            f"Recommendation: {report.recommended_decision.value}",
            "",
            f"=== RISK FACTORS ({len(report.risk_factors)}) ===",
        ]
        for i, rf in enumerate(report.risk_factors, 1):
            lines.append(f"  {i}. {rf}")
        
        lines.append(f"\n=== MITIGATING FACTORS ({len(report.mitigating_factors)}) ===")
        for i, mf in enumerate(report.mitigating_factors, 1):
            lines.append(f"  {i}. {mf}")
        
        lines.append(f"\n=== EVIDENCE ({len(report.evidence)} sources) ===")
        for ev in report.evidence:
            status = "✅" if ev.success else "❌"
            lines.append(f"  {status} [{ev.task_type.value}]: {ev.analysis[:150]}")
            if ev.risk_indicators:
                lines.append(f"     Indicators: {ev.risk_indicators[:3]}")
        
        if report.detailed_analysis:
            lines.append(f"\n=== PHÂN TÍCH CHI TIẾT (Report Agent) ===")
            lines.append(report.detailed_analysis[:1000])
        
        lines.append("\n=== YÊU CẦU ===")
        lines.append("Đánh giá INDEPENDENT và ra quyết định: ALLOW / BLOCK / ESCALATE")
        
        return "\n".join(lines)
    
    def _extract_sender_id(self, report: InvestigationReport) -> str:
        """Lấy sender_id từ evidence (nhiều fallback strategies)."""
        # Strategy 1: Tìm từ profile.customer_id trong evidence
        for ev in report.evidence:
            if ev.raw_data.get("profile", {}).get("customer_id"):
                return ev.raw_data["profile"]["customer_id"]
        
        # Strategy 2: Tìm từ sender_id / sender trong evidence raw_data
        for ev in report.evidence:
            sender = ev.raw_data.get("sender_id") or ev.raw_data.get("sender")
            if sender:
                return sender
        
        # Strategy 3: Tìm từ transaction info trong evidence raw_data
        for ev in report.evidence:
            txn_info = ev.raw_data.get("transaction", {})
            if isinstance(txn_info, dict):
                sender = txn_info.get("sender_id") or txn_info.get("sender")
                if sender:
                    return sender
        
        print("   ⚠️  WARNING: Không tìm được sender_id từ evidence")
        return ""
    
    def _enforce_decision(
        self,
        decision: FinalDecision,
        sender_id: str,
        report: InvestigationReport,
        actions: list[str],
    ):
        """
        Phase 3: Thực thi enforcement actions.
        
        BLOCK → blacklist + risk score 0.95 + index pattern vào ChromaDB
        ALLOW → whitelist + giảm risk score + index pattern vào ChromaDB
        ESCALATE → tăng risk score + index pattern vào ChromaDB
        """
        if decision == FinalDecision.BLOCK:
            if sender_id:
                redis_service.update_blacklist(sender_id, add=True)
                redis_service.update_risk_score(sender_id, 0.95)
                print(f"\n   🔒 Phase 3: BLOCK enforcement")
                print(f"      → Blacklisted: {sender_id}")
                print(f"      → Risk score: 0.95")
            
            # Index vào ChromaDB (Adaptive Intelligence)
            new_pattern = {
                "type": "past_investigation",
                "title": f"Case: {report.transaction_id} blocked",
                "description": report.summary,
                "risk_factors": report.risk_factors[:5],
                "decision": "BLOCK",
            }
            pattern_id = vector_store.index_new_pattern(new_pattern)
            actions.append(f"indexed_pattern:{pattern_id}")
            print(f"      → ChromaDB updated: {pattern_id}")
        
        elif decision == FinalDecision.ALLOW:
            if sender_id:
                redis_service.update_whitelist(sender_id, add=True)
                current_score = redis_service.get_risk_score(sender_id)
                new_score = max(current_score - 0.1, 0.01)
                redis_service.update_risk_score(sender_id, new_score)
                print(f"\n   ✅ Phase 3: ALLOW enforcement")
                print(f"      → Whitelisted: {sender_id}")
                print(f"      → Risk score: {current_score:.2f} → {new_score:.2f}")
            
            # Index vào ChromaDB (lưu pattern "cleared" cho future reference)
            allow_pattern = {
                "type": "past_investigation",
                "title": f"Case: {report.transaction_id} allowed",
                "description": report.summary,
                "mitigating_factors": report.mitigating_factors[:5],
                "decision": "ALLOW",
            }
            pattern_id = vector_store.index_new_pattern(allow_pattern)
            actions.append(f"indexed_pattern:{pattern_id}")
            print(f"      → ChromaDB updated: {pattern_id}")
        
        elif decision == FinalDecision.ESCALATE:
            print(f"\n   ⚠️  Phase 3: ESCALATE to human review")
            print(f"      → Transaction held pending review")
            
            # Tăng risk score cho sender (nghi ngờ nhưng chưa chắc chắn)
            if sender_id:
                current_score = redis_service.get_risk_score(sender_id)
                new_score = min(current_score + 0.15, 0.89)  # Không vượt 0.9 (auto-block)
                redis_service.update_risk_score(sender_id, new_score)
                print(f"      → Risk score: {current_score:.2f} → {new_score:.2f}")
            
            # Index vào ChromaDB (lưu pattern "pending review")
            escalate_pattern = {
                "type": "past_investigation",
                "title": f"Case: {report.transaction_id} escalated",
                "description": report.summary,
                "risk_factors": report.risk_factors[:5],
                "decision": "ESCALATE",
            }
            pattern_id = vector_store.index_new_pattern(escalate_pattern)
            actions.append(f"indexed_pattern:{pattern_id}")
            print(f"      → ChromaDB updated: {pattern_id}")
