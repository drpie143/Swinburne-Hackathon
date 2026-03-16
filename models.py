# ====================================================================
# MODELS.PY - Data Models (Pydantic) - ENRICHED cho Dynamic Planning
# ====================================================================
# Định nghĩa tất cả data structures dùng trong hệ thống.
#
# THAY ĐỔI QUAN TRỌNG so với bản cũ:
#   Phase1Result được MỞ RỘNG với context chi tiết:
#   - risk_details: Chi tiết từng rule đã trigger + dữ liệu đi kèm
#   - velocity_data: Thông tin velocity cụ thể từ Redis
#   - account_flags: Trạng thái whitelist/blacklist/risk của sender+receiver
#
#   → Planner Agent nhận CONTEXT ĐẦY ĐỦ từ Phase 1
#   → LLM tạo kế hoạch điều tra KHÁC NHAU tùy tình huống
#   → Không còn "luôn nguyên 1 kế hoạch" như bản cũ
#
# Flow dữ liệu:
#   Transaction → Phase1Result (enriched) → InvestigationRequest →
#   PlannerTask[] → ExecutorResult[] → InvestigationReport →
#   FinalDecision
# ====================================================================

from __future__ import annotations
from enum import Enum
from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field


# =====================================================================
# ENUMS
# =====================================================================

class RiskLevel(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class FinalDecision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    ESCALATE = "escalate"


class TaskType(str, Enum):
    """
    Các loại subtask mà Planner Agent tạo ra cho Executor.
    
    Consolidated types (mới — ưu tiên):
    - ACCOUNT_PROFILING: Tổng hợp behavioral + amount pattern từ MongoDB
    - NETWORK_ANALYSIS: Tổng hợp graph + device analysis từ Neo4j
    - KNOWLEDGE_RETRIEVAL: Tìm fraud patterns từ ChromaDB (RAG)
    
    Legacy types (vẫn hỗ trợ):
    - GRAPH_QUERY, BEHAVIORAL_ANALYSIS, DEVICE_ANALYSIS, AMOUNT_PATTERN
    """
    # Consolidated types
    ACCOUNT_PROFILING = "account_profiling"
    NETWORK_ANALYSIS = "network_analysis"
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval"
    # Legacy types (backward compat)
    GRAPH_QUERY = "graph_query"
    BEHAVIORAL_ANALYSIS = "behavioral_analysis"
    DEVICE_ANALYSIS = "device_analysis"
    AMOUNT_PATTERN = "amount_pattern"


# =====================================================================
# TRANSACTION - Giao dịch đầu vào
# =====================================================================

class Transaction(BaseModel):
    """
    Một giao dịch ngân hàng cần được kiểm tra.
    Đầu vào đầu tiên vào hệ thống (từ Kinesis trong production).
    """
    transaction_id: str = Field(..., description="ID duy nhất của giao dịch")
    timestamp: str = Field(..., description="Thời gian giao dịch (ISO format)")
    
    sender_id: str = Field(..., description="ID tài khoản người gửi")
    sender_name: str = Field(default="", description="Tên người gửi")
    sender_account_type: str = Field(default="checking", description="Loại TK")
    
    receiver_id: str = Field(..., description="ID tài khoản người nhận")
    receiver_name: str = Field(default="", description="Tên người nhận")
    
    amount: float = Field(..., description="Số tiền giao dịch (USD)")
    currency: str = Field(default="USD", description="Loại tiền tệ")
    transaction_type: str = Field(default="transfer", description="Loại GD")
    
    device_id: str = Field(default="", description="ID thiết bị thực hiện GD")
    ip_address: str = Field(default="", description="Địa chỉ IP")
    channel: str = Field(default="mobile", description="Kênh: mobile/web/atm")
    location: str = Field(default="", description="Vị trí địa lý")
    
    merchant_id: str = Field(default="", description="ID merchant")
    description: str = Field(default="", description="Mô tả giao dịch")


# =====================================================================
# PHASE 1 RESULT - ENRICHED (Thay đổi quan trọng!)
# =====================================================================

class RuleDetail(BaseModel):
    """
    Chi tiết 1 rule đã trigger trong Phase 1.
    
    MỚI: Không chỉ tên rule, mà còn GIÁ TRỊ CỤ THỂ.
    Ví dụ: thay vì chỉ "HIGH_VELOCITY", giờ có:
      rule="HIGH_VELOCITY", value=15, threshold=5, severity="high",
      detail="15 GD trong 1 giờ qua (threshold: 5)"
    
    → Planner Agent đọc được chi tiết → tạo plan phù hợp hơn
    """
    rule: str = Field(..., description="Tên rule đã trigger")
    severity: str = Field(default="medium", description="Mức độ: low/medium/high/critical")
    value: Optional[float] = Field(default=None, description="Giá trị thực tế")
    threshold: Optional[float] = Field(default=None, description="Ngưỡng so sánh")
    detail: str = Field(default="", description="Mô tả chi tiết")


class AccountFlags(BaseModel):
    """
    Trạng thái của 1 tài khoản từ Redis (Phase 1).
    
    MỚI: Cung cấp TOÀN BỘ thông tin Redis cho Planner:
    - Whitelist/blacklist status
    - Risk score hiện tại
    - Velocity gần đây
    
    → Planner biết tài khoản nào nghi ngờ → plan accordingly
    """
    account_id: str
    is_whitelisted: bool = False
    is_blacklisted: bool = False
    risk_score: float = 0.0
    velocity_1h: int = 0
    velocity_24h: int = 0


class Phase1Result(BaseModel):
    """
    Kết quả từ Phase 1: Real-time Screening (Lambda + Redis).
    
    ĐÃ MỞ RỘNG với context chi tiết:
    - triggered_rules → list[RuleDetail] (có giá trị cụ thể)
    - sender_flags, receiver_flags → AccountFlags (từ Redis)
    - context_summary → text tóm tắt cho Planner prompt
    
    Planner Agent nhận Phase1Result enriched này →
    LLM hiểu CHÍNH XÁC tại sao giao dịch bị flag →
    Tạo kế hoạch điều tra KHÁC NHAU tùy tình huống.
    """
    transaction_id: str = Field(..., description="ID giao dịch gốc")
    risk_level: RiskLevel = Field(..., description="Mức rủi ro: green/yellow/red")
    risk_score: float = Field(default=0.0, description="Điểm rủi ro (0.0 - 1.0)")
    
    # ─── ENRICHED FIELDS (MỚI) ───
    triggered_rules: list[RuleDetail] = Field(
        default_factory=list,
        description="Chi tiết từng rule đã trigger (có giá trị cụ thể)"
    )
    sender_flags: Optional[AccountFlags] = Field(
        default=None,
        description="Trạng thái sender từ Redis"
    )
    receiver_flags: Optional[AccountFlags] = Field(
        default=None,
        description="Trạng thái receiver từ Redis"
    )
    context_summary: str = Field(
        default="",
        description="Tóm tắt context cho Planner Agent prompt"
    )
    
    requires_investigation: bool = Field(default=False)
    message: str = Field(default="")


# =====================================================================
# INVESTIGATION REQUEST
# =====================================================================

class InvestigationRequest(BaseModel):
    """
    Yêu cầu điều tra gửi vào Phase 2.
    Chứa transaction + Phase1Result enriched.
    """
    request_id: str = Field(..., description="ID yêu cầu điều tra")
    transaction: Transaction = Field(..., description="Giao dịch cần điều tra")
    phase1_result: Phase1Result = Field(..., description="Kết quả Phase 1 (enriched)")
    priority: int = Field(default=5, description="Độ ưu tiên: 1-10")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# =====================================================================
# PLANNER TASK
# =====================================================================

class PlannerTask(BaseModel):
    """
    Một subtask do Planner Agent (LLM) tạo.
    
    Planner dùng Gemini LLM để phân tích Phase1Result enriched
    và tạo plan ĐỘNG - khác nhau tùy context.
    """
    task_id: str = Field(..., description="ID của subtask")
    task_type: TaskType = Field(..., description="Loại task")
    description: str = Field(..., description="Mô tả chi tiết (LLM-generated)")
    query: str = Field(default="", description="Query cụ thể (Cypher/search)")
    priority: int = Field(default=5, description="Độ ưu tiên (LLM-assigned)")
    depends_on: list[str] = Field(default_factory=list, description="Dependencies")


# =====================================================================
# EXECUTOR RESULT
# =====================================================================

class ExecutorResult(BaseModel):
    """
    Kết quả thực thi 1 subtask bởi Executor Agent.
    """
    task_id: str = Field(..., description="ID task đã thực hiện")
    task_type: TaskType = Field(..., description="Loại task đã thực hiện")
    success: bool = Field(default=True)
    raw_data: dict = Field(default_factory=dict, description="Dữ liệu thô")
    analysis: str = Field(default="", description="Phân tích sơ bộ")
    risk_indicators: list[str] = Field(default_factory=list, description="Chỉ báo rủi ro")
    error_message: str = Field(default="")


# =====================================================================
# INVESTIGATION REPORT
# =====================================================================

class InvestigationReport(BaseModel):
    """
    Báo cáo điều tra tổng hợp do Report Agent (Gemini) tạo.
    Audit-ready, chi tiết, do LLM generate.
    """
    request_id: str = Field(...)
    transaction_id: str = Field(...)
    summary: str = Field(default="")
    evidence: list[ExecutorResult] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    mitigating_factors: list[str] = Field(default_factory=list)
    confidence_score: float = Field(default=0.0)
    recommended_decision: FinalDecision = Field(default=FinalDecision.ESCALATE)
    detailed_analysis: str = Field(default="")


# =====================================================================
# DECISION RESULT
# =====================================================================

class DecisionResult(BaseModel):
    """
    Quyết định cuối cùng từ Detective Agent (Gemini LLM).
    """
    request_id: str = Field(...)
    transaction_id: str = Field(...)
    decision: FinalDecision = Field(...)
    confidence: float = Field(default=0.0)
    reasoning: str = Field(default="")
    actions: list[str] = Field(default_factory=list)
    investigation_report: Optional[InvestigationReport] = Field(default=None)



# NOTE: PipelineState đã bị xóa — hệ thống dùng GraphState (TypedDict)
# trong orchestrator.py thay vì Pydantic model.

