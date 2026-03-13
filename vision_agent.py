# ====================================================================
# VISION_AGENT.PY - Agent Phân Tích Kết Quả (Gemini 2.5 Flash)
# ====================================================================
#
# Vision Agent đọc và phân tích KẾT QUẢ từ Executor Agent.
#
# FLOW:
#   Executor truy vấn 3 DB (Neo4j, ChromaDB, MongoDB Atlas)
#       ↓
#   Kết quả (raw data + analysis sơ bộ)
#       ↓
#   Vision Agent (Gemini 2.5 Flash) đọc TẤT CẢ kết quả
#       ↓
#   Phân tích tổng hợp: pattern detection, cross-reference,
#   risk assessment liên kết giữa các nguồn evidence
#       ↓
#   Trả VisionAnalysis về cho Planner
#
# TẠI SAO CẦN VISION AGENT?
#   - Executor chỉ trả raw data + analysis sơ bộ từng task riêng lẻ
#   - Vision Agent CROSS-REFERENCE tất cả kết quả → phát hiện
#     pattern MÀ TỪNG TASK RIÊNG LẺ KHÔNG THẤY
#   - Ví dụ: Graph thấy star topology + Amount thấy structuring
#     → Vision kết luận: "Money mule network + structuring scheme"
#
# Dùng Gemini 2.5 Flash (free tier: 15 req/min)
# ====================================================================

from __future__ import annotations
import json
from typing import Optional

from models import ExecutorResult
from llm_providers import gemini_provider_vision as gemini_provider


VISION_SYSTEM_PROMPT = """Bạn là VISION AGENT trong hệ thống phát hiện gian lận ngân hàng.

NHIỆM VỤ: Đọc và phân tích TẤT CẢ kết quả từ Executor Agent (dữ liệu từ Neo4j, ChromaDB, MongoDB Atlas).

BẠN PHẢI:
1. ĐỌC KỸ từng evidence source (graph query, behavioral, knowledge, device, amount)
2. CROSS-REFERENCE: Tìm mối liên kết giữa các evidence
   - Graph topology + amount patterns → structuring qua mule network?
   - Device sharing → bot/automated fraud?
   - Large amount + blacklisted receiver → money laundering?
3. TỔNG HỢP risk indicators từ tất cả sources
4. PHÁT HIỆN patterns mà từng source RIÊNG LẺ không thấy
5. ĐÁNH GIÁ confidence level

RESPONSE FORMAT (JSON):
{
    "summary": "Tóm tắt tổng hợp 2-3 câu",
    "cross_references": [
        "Mối liên kết 1 giữa evidence A và B",
        "Mối liên kết 2..."
    ],
    "patterns_detected": [
        {
            "pattern": "Tên pattern (structuring, mule_network, ATO, etc.)",
            "confidence": 0.0-1.0,
            "evidence": "Bằng chứng cụ thể"
        }
    ],
    "consolidated_risk_indicators": ["risk 1", "risk 2", ...],
    "consolidated_mitigating_factors": ["mitigating 1", ...],
    "overall_risk_level": "low|medium|high|critical",
    "recommended_action": "investigate_more|sufficient_for_report",
    "reasoning": "Giải thích chi tiết"
}"""


class VisionAgent:
    """
    Vision Agent - Phân tích tổng hợp kết quả Executor.

    Sử dụng Gemini 2.5 Flash để:
    - Đọc TẤT CẢ evidence từ Executor
    - Cross-reference giữa các nguồn (Neo4j, ChromaDB, MongoDB)
    - Phát hiện patterns ẩn
    - Tổng hợp risk assessment

    Gemini 2.5 Flash free tier: 15 req/min
    """

    def analyze_results(
        self,
        evidence: list[ExecutorResult],
        hypothesis: str = "",
        investigation_context: dict | None = None,
    ) -> dict:
        """
        Phân tích tổng hợp tất cả evidence từ Executor.

        Args:
            evidence: Danh sách ExecutorResult từ Executor
            hypothesis: Giả thuyết ban đầu từ Planner
            investigation_context: Context bổ sung (txn info, etc.)

        Returns:
            dict: VisionAnalysis JSON (summary, patterns, risks, etc.)
        """
        print(f"\n{'='*60}")
        print(f"👁️  VISION AGENT (Gemini): Phân tích {len(evidence)} evidence sources...")
        print(f"{'='*60}")

        # ─── Tạo prompt từ evidence ───
        prompt = self._build_analysis_prompt(evidence, hypothesis, investigation_context)

        # ─── Gọi Gemini ───
        raw_response = gemini_provider.generate(prompt, temperature=0.2)

        # ─── Parse JSON response ───
        analysis = self._parse_response(raw_response, evidence)

        # ─── Log kết quả ───
        print(f"   📊 Summary: {analysis.get('summary', 'N/A')[:120]}")
        print(f"   🔗 Cross-references: {len(analysis.get('cross_references', []))}")
        patterns = analysis.get("patterns_detected", [])
        print(f"   🔍 Patterns: {len(patterns)}")
        for p in patterns[:3]:
            print(f"      • {p.get('pattern', '?')} (conf: {p.get('confidence', 0):.0%})")
        risk_level = analysis.get("overall_risk_level", "unknown")
        action = analysis.get("recommended_action", "unknown")
        print(f"   ⚠️  Risk Level: {risk_level}")
        print(f"   📌 Action: {action}")
        print(f"{'='*60}\n")

        return analysis

    def _build_analysis_prompt(
        self,
        evidence: list[ExecutorResult],
        hypothesis: str,
        context: dict | None,
    ) -> str:
        """Tạo prompt chi tiết cho Gemini từ evidence."""
        lines = [VISION_SYSTEM_PROMPT, ""]

        # ─── Context ───
        if context:
            lines.append("=== INVESTIGATION CONTEXT ===")
            lines.append(f"Transaction: {context.get('transaction_id', 'N/A')}")
            lines.append(f"Sender: {context.get('sender_id', 'N/A')}")
            lines.append(f"Receiver: {context.get('receiver_id', 'N/A')}")
            lines.append(f"Amount: ${context.get('amount', 0):,.2f}")
            lines.append(f"Risk Score: {context.get('initial_risk_score', 0):.3f}")
            lines.append("")

        if hypothesis:
            lines.append(f"=== HYPOTHESIS CỦA PLANNER ===")
            lines.append(hypothesis)
            lines.append("")

        # ─── Evidence từ Executor ───
        lines.append(f"=== EVIDENCE TỪ EXECUTOR ({len(evidence)} sources) ===")

        for i, result in enumerate(evidence, 1):
            status = "✅" if result.success else "❌"
            lines.append(f"\n--- Source {i}: {status} [{result.task_type.value}] ---")
            lines.append(f"Analysis: {result.analysis}")
            if result.risk_indicators:
                lines.append(f"Risk Indicators ({len(result.risk_indicators)}):")
                for ri in result.risk_indicators:
                    lines.append(f"  • {ri}")
            if result.raw_data:
                # Giới hạn raw_data để không vượt token limit
                raw_str = json.dumps(result.raw_data, default=str, ensure_ascii=False)
                if len(raw_str) > 2000:
                    raw_str = raw_str[:2000] + "... (truncated)"
                lines.append(f"Raw Data: {raw_str}")
            if result.error_message:
                lines.append(f"Error: {result.error_message}")

        lines.append("\n=== YÊU CẦU ===")
        lines.append(
            "Đọc TẤT CẢ evidence trên. Cross-reference giữa các sources. "
            "Phát hiện patterns ẩn. Trả JSON theo format đã chỉ định."
        )

        return "\n".join(lines)

    def _parse_response(self, raw: str, evidence: list[ExecutorResult]) -> dict:
        """Parse Gemini response thành dict. Fallback nếu parse lỗi."""
        # Thử parse JSON trực tiếp
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass

        # Thử extract JSON từ markdown code block
        for delimiter in ["```json", "```"]:
            if delimiter in raw:
                try:
                    json_str = raw.split(delimiter)[1].split("```")[0].strip()
                    return json.loads(json_str)
                except (json.JSONDecodeError, IndexError):
                    pass

        # ─── Fallback: tổng hợp thủ công từ evidence ───
        return self._fallback_analysis(raw, evidence)

    def _fallback_analysis(self, raw_text: str, evidence: list[ExecutorResult]) -> dict:
        """
        Fallback khi Gemini không trả JSON hợp lệ hoặc không có API key.
        Tổng hợp thủ công từ evidence.
        """
        all_risk_indicators = []
        all_mitigating = []

        for result in evidence:
            all_risk_indicators.extend(result.risk_indicators)
            if "✅" in result.analysis or "normal" in result.analysis.lower():
                for line in result.analysis.split("\n"):
                    if "✅" in line:
                        all_mitigating.append(line.strip())

        # Detect patterns dựa trên risk indicators
        patterns = []
        indicator_text = " ".join(all_risk_indicators).lower()

        if "structuring" in indicator_text:
            patterns.append({
                "pattern": "structuring",
                "confidence": 0.7,
                "evidence": "Structuring indicators found in transaction amounts",
            })
        if "mule" in indicator_text or "shared" in indicator_text:
            patterns.append({
                "pattern": "mule_network",
                "confidence": 0.7,
                "evidence": "Mule network / shared entity indicators found",
            })
        if "blacklist" in indicator_text:
            patterns.append({
                "pattern": "blacklisted_connection",
                "confidence": 0.8,
                "evidence": "Connection to blacklisted accounts detected",
            })
        if "vpn" in indicator_text or "tor" in indicator_text or "anonymizing" in indicator_text:
            patterns.append({
                "pattern": "anonymization",
                "confidence": 0.6,
                "evidence": "VPN/Tor/anonymizing network usage detected",
            })

        # Risk level
        if len(all_risk_indicators) >= 5:
            risk_level = "critical"
        elif len(all_risk_indicators) >= 3:
            risk_level = "high"
        elif len(all_risk_indicators) >= 1:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "summary": raw_text[:300] if raw_text else (
                f"Phân tích {len(evidence)} evidence sources: "
                f"{len(all_risk_indicators)} risk indicators, "
                f"{len(all_mitigating)} mitigating factors."
            ),
            "cross_references": [],
            "patterns_detected": patterns,
            "consolidated_risk_indicators": list(set(all_risk_indicators)),
            "consolidated_mitigating_factors": all_mitigating,
            "overall_risk_level": risk_level,
            "recommended_action": (
                "sufficient_for_report" if len(all_risk_indicators) >= 3
                else "investigate_more"
            ),
            "reasoning": (
                f"Fallback analysis: {len(all_risk_indicators)} risk indicators "
                f"from {len(evidence)} sources."
            ),
        }


# =====================================================================
# SINGLETON INSTANCE
# =====================================================================

vision_agent = VisionAgent()
