# ====================================================================
# REPORT_AGENT.PY - Agent Tạo Báo Cáo (Gemini 2.5 Flash)
# ====================================================================
#
# THAY ĐỔI:
#   Cũ: Template-based report (cứng, format cố định)
#   Mới: Gemini 2.5 Flash generate báo cáo natural language
#         → Chi tiết hơn, audit-ready, đọc dễ hiểu hơn
#
# Gemini 2.5 Flash free tier: 15 req/min, 1,500 req/day
# Cloud-hosted: chỉ cần API key, không cài gì local
# ====================================================================

from __future__ import annotations
from models import (
    InvestigationReport, ExecutorResult, FinalDecision, TaskType
)
from llm_providers import gemini_provider_report as gemini_provider


REPORT_PROMPT_TEMPLATE = """Bạn là REPORT AGENT trong hệ thống phát hiện gian lận ngân hàng.

NHIỆM VỤ: Tạo báo cáo điều tra NGẮN GỌN, súc tích.

VỤ VIỆC: {transaction_id} | {request_id} | {total_steps} bước | confidence {confidence:.2f}

HYPOTHESIS: {hypothesis}

EVIDENCE ({evidence_count} sources):
{evidence_text}

RISK ({risk_count}): {risk_factors_text}
MITIGATING ({mitigating_count}): {mitigating_factors_text}

YÊU CẦU — VIẾT NGẮN, KHÔNG DÀI DÒNG:
1. Summary: 1-2 câu tóm tắt vụ việc
2. Evidence: bullet-point ngắn, chỉ nêu phát hiện quan trọng
3. Risk vs Mitigating: đánh giá 1-2 câu
4. Đề xuất: ALLOW / BLOCK / ESCALATE + lý do 1 câu

Tổng báo cáo KHÔNG quá 15 dòng. Viết tiếng Việt."""


class ReportAgent:
    """
    Report Generating Agent - Tổng hợp bằng chứng thành báo cáo.
    
    Sử dụng Gemini 2.5 Flash để generate:
    - Natural language report (audit-ready)
    - Decision recommendation với reasoning
    - Confidence assessment
    
    Fallback: template-based nếu không có Gemini API key.
    """
    
    def generate_report(
        self,
        request_id: str,
        transaction_id: str,
        investigation_summary: dict,
        evidence: list[ExecutorResult],
    ) -> InvestigationReport:
        """
        Tạo báo cáo điều tra bằng Gemini 2.5 Flash.
        """
        print(f"\n{'='*60}")
        print(f"📝 REPORT AGENT (Gemini): Tạo báo cáo...")
        print(f"{'='*60}")
        
        # ─── Thu thập factors ───
        risk_factors = []
        mitigating_factors = []
        
        for result in evidence:
            for indicator in result.risk_indicators:
                if indicator not in risk_factors:
                    risk_factors.append(indicator)
            
            analysis = result.analysis.lower()
            if "✅" in result.analysis or "normal" in analysis or "verified" in analysis:
                for line in result.analysis.split("\n"):
                    if "✅" in line:
                        mitigating_factors.append(line.strip())
        
        # ─── Tính confidence ───
        evidence_quality = sum(1 for e in evidence if e.success) / max(len(evidence), 1)
        risk_weight = min(len(risk_factors) * 0.1, 0.5)
        planner_confidence = investigation_summary.get("confidence", 0.5)
        confidence = min(max(evidence_quality * 0.3 + risk_weight + planner_confidence * 0.4, 0.1), 1.0)
        
        # ─── Recommended decision ───
        if len(risk_factors) >= 5 and confidence > 0.7:
            recommended = FinalDecision.BLOCK
        elif len(risk_factors) <= 1 and len(mitigating_factors) >= 2:
            recommended = FinalDecision.ALLOW
        elif len(risk_factors) >= 3:
            recommended = FinalDecision.BLOCK
        else:
            recommended = FinalDecision.ESCALATE
        
        # ─── Generate detailed analysis với Gemini ───
        evidence_text = ""
        for r in evidence:
            status = "✅" if r.success else "❌"
            evidence_text += f"\n{status} [{r.task_type.value}]:\n"
            evidence_text += f"  Analysis: {r.analysis[:300]}\n"
            if r.risk_indicators:
                evidence_text += f"  Risk indicators: {r.risk_indicators}\n"
        
        prompt = REPORT_PROMPT_TEMPLATE.format(
            transaction_id=transaction_id,
            request_id=request_id,
            total_steps=investigation_summary.get("total_steps", "N/A"),
            confidence=confidence,
            hypothesis=investigation_summary.get("hypothesis", "N/A"),
            evidence_count=len(evidence),
            evidence_text=evidence_text,
            risk_count=len(risk_factors),
            risk_factors_text="\n".join(f"  {i+1}. {rf}" for i, rf in enumerate(risk_factors)),
            mitigating_count=len(mitigating_factors),
            mitigating_factors_text="\n".join(f"  {i+1}. {mf}" for i, mf in enumerate(mitigating_factors)) or "  (không có)",
        )
        
        detailed_analysis = gemini_provider.generate(prompt, temperature=0.2)
        
        # ─── Summary ngắn ───
        summary = (
            f"Điều tra {transaction_id}: "
            f"{len(risk_factors)} risk factors, "
            f"{len(mitigating_factors)} mitigating. "
            f"Confidence: {confidence:.0%}. "
            f"Đề xuất: {recommended.value.upper()}."
        )
        
        report = InvestigationReport(
            request_id=request_id,
            transaction_id=transaction_id,
            summary=summary,
            evidence=evidence,
            risk_factors=risk_factors,
            mitigating_factors=mitigating_factors,
            confidence_score=confidence,
            recommended_decision=recommended,
            detailed_analysis=detailed_analysis,
        )
        
        print(f"   Summary: {summary}")
        print(f"   Recommended: {recommended.value}")
        print(f"{'='*60}\n")
        
        return report
