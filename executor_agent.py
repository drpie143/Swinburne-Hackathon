# ====================================================================
# EXECUTOR_AGENT.PY - AI-Driven Executor Agent (Gemini LLM)
# ====================================================================
#
# THIẾT KẾ MỚI: True AI Agent, KHÔNG phải router.
#
# Flow:
#   1. Nhận PlannerTask (từ Planner Agent)
#   2. Gửi task description + DB schema → Gemini LLM
#   3. Gemini SINH QUERY tự động (Cypher, MongoDB filter, search text...)
#   4. Executor chạy các query đã sinh qua DATABASE TOOLS
#   5. Gửi raw results → Gemini LLM phân tích
#   6. Gemini trả về risk_indicators + analysis
#   7. Return ExecutorResult
#
# DATABASE TOOLS (LLM chọn và sinh params):
#   - neo4j_cypher: Sinh Cypher query cho Neo4j
#   - neo4j_neighbors / neo4j_shared_entities / neo4j_circular_flows
#   - mongodb_profile / mongodb_history / mongodb_related / mongodb_query
#   - chromadb_search: Sinh search query cho vector DB
#   - redis_velocity / redis_blacklist
#
# AN TOÀN: Không dùng eval(). LLM sinh structured JSON (tool + params),
#           Executor dispatch qua pre-defined tool functions.
# ====================================================================

from __future__ import annotations
import json
from typing import Optional

from models import PlannerTask, ExecutorResult, TaskType
from simulators import redis_service
from mongo_db import mongodb_client
from graph_db import neo4j_client
from vector_store import vector_store
from llm_providers import gemini_provider


# =====================================================================
# SYSTEM PROMPTS CHO GEMINI
# =====================================================================

TOOL_SCHEMA = """
Các công cụ truy vấn database cho điều tra gian lận:

1. neo4j_cypher — Chạy truy vấn Cypher trên Neo4j (graph database)
   params: {"query": "MATCH ...", "params": {"key": "value"}}
   Schema Neo4j:
     Nodes: (:Account {id, name, risk_score}), (:Device {id, type}), (:IP {id, label}), (:Merchant {id, name, category})
     Relationships:
       (:Account)-[:TRANSFERS_TO {amount, timestamp}]->(:Account)
       (:Account)-[:USES_DEVICE]->(:Device)
       (:Account)-[:CONNECTS_FROM]->(:IP)
       (:Account)-[:PAYS_TO]->(:Merchant)

2. neo4j_neighbors — Lấy các node láng giềng của tài khoản trong đồ thị
   params: {"account_id": "ACC_001", "depth": 2}

3. neo4j_shared_entities — Tìm tài khoản khác dùng chung thiết bị hoặc IP
   params: {"account_id": "ACC_001", "entity_type": "device" hoặc "ip"}

4. neo4j_circular_flows — Phát hiện luồng tiền vòng tròn (rửa tiền)
   params: {"account_id": "ACC_001"}

5. neo4j_blacklisted — Tìm kết nối đến tài khoản bị chặn (blacklist)
   params: {"account_id": "ACC_001"}

6. mongodb_profile — Lấy hồ sơ khách hàng (KYC, mức rủi ro, tuổi tài khoản, hành vi cơ sở)
   params: {"account_id": "ACC_001"}

7. mongodb_history — Lấy lịch sử giao dịch gần đây
   params: {"account_id": "ACC_001", "limit": 20}

8. mongodb_related — Lấy danh sách tài khoản đã giao dịch cùng
   params: {"account_id": "ACC_001"}

9. mongodb_query — Chạy truy vấn MongoDB tùy chỉnh (chỉ đọc)
   params: {"collection": "customer_profiles" hoặc "transaction_history", "filter": {...}, "limit": 20}

10. chromadb_search — Tìm kiếm ngữ nghĩa trong cơ sở tri thức gian lận (patterns, vụ án cũ, quy định)
    params: {"query": "mô tả nội dung cần tìm", "top_k": 3, "filter_type": "fraud_pattern" hoặc "past_investigation" hoặc null}

11. redis_velocity — Đếm tốc độ giao dịch (số lượng trong khoảng thời gian)
    params: {"account_id": "ACC_001", "hours": 1}

12. redis_blacklist — Kiểm tra tài khoản có trong danh sách đen không
    params: {"account_id": "ACC_001"}
""".strip()

QUERY_GEN_SYSTEM = f"""Bạn là Executor Agent trong hệ thống phát hiện gian lận ngân hàng.
Nhiệm vụ: nhận task điều tra và sinh các truy vấn database tối ưu để thu thập bằng chứng.

{TOOL_SCHEMA}

QUY TẮC:
- Sinh 1-5 tool_calls phù hợp nhất với task điều tra.
- Với neo4j_cypher, dùng parameterized queries với cú pháp $param để đảm bảo an toàn.
- Chọn tool phù hợp loại task (phân tích đồ thị → neo4j, hành vi → mongodb, tri thức → chromadb, v.v.)
- Cụ thể: bao gồm account ID thực tế, từ khóa tìm kiếm, filter liên quan.
- Chỉ trả về JSON hợp lệ, không thêm text.

Định dạng output:
{{
  "reasoning": "Giải thích ngắn gọn chiến lược truy vấn",
  "tool_calls": [
    {{"tool": "tên_tool", "params": {{...}}}}
  ]
}}"""

ANALYSIS_SYSTEM = """Bạn là chuyên gia phân tích gian lận AI. Phân tích kết quả truy vấn database từ cuộc điều tra gian lận.

QUY TẮC:
- Xác định các chỉ số rủi ro cụ thể, dựa trên bằng chứng từ dữ liệu.
- Định dạng mỗi risk_indicator: "LOẠI_CHỈ_SỐ: chi tiết bằng chứng cụ thể"
- Ví dụ: "HIGH_VELOCITY: 15 giao dịch trong 1h (baseline 2/h)", "SHARED_DEVICE: DEV_X dùng chung với MULE_001", "KYC_NOT_VERIFIED: tài khoản ACC_001 status=pending"
- Chỉ gắn cờ rủi ro khi có bằng chứng thực tế trong dữ liệu.
- Nếu dữ liệu không có gì đáng ngờ, trả về risk_indicators rỗng.
- Phân tích ngắn gọn nhưng kỹ lưỡng.
- Chỉ trả về JSON hợp lệ, không thêm text.

Định dạng output:
{
  "analysis": "Phân tích 2-5 câu về phát hiện",
  "risk_indicators": ["LOẠI_CHỈ_SỐ: chi tiết", ...]
}"""


# =====================================================================
# EXECUTOR AGENT CLASS — AI-DRIVEN
# =====================================================================

class ExecutorAgent:
    """
    AI-Driven Executor Agent.

    Thay vì hardcoded handlers, dùng Gemini LLM để:
    1. Sinh query tự động (Cypher, MongoDB, search text...)
    2. Chạy query qua database tools
    3. Phân tích kết quả bằng LLM → risk_indicators
    """

    def __init__(self):
        self.max_retries: int = 1
        # Map tool name → safe execution function
        self._tools: dict[str, callable] = {
            "neo4j_cypher": self._tool_neo4j_cypher,
            "neo4j_neighbors": self._tool_neo4j_neighbors,
            "neo4j_shared_entities": self._tool_neo4j_shared_entities,
            "neo4j_circular_flows": self._tool_neo4j_circular_flows,
            "neo4j_blacklisted": self._tool_neo4j_blacklisted,
            "mongodb_profile": self._tool_mongodb_profile,
            "mongodb_history": self._tool_mongodb_history,
            "mongodb_related": self._tool_mongodb_related,
            "mongodb_query": self._tool_mongodb_query,
            "chromadb_search": self._tool_chromadb_search,
            "redis_velocity": self._tool_redis_velocity,
            "redis_blacklist": self._tool_redis_blacklist,
        }

    # =================================================================
    # PUBLIC API (giữ nguyên interface cho orchestrator)
    # =================================================================

    def execute_task(self, task: PlannerTask) -> ExecutorResult:
        """
        Thực thi 1 PlannerTask bằng AI (với bounded self-correction).
        """
        for attempt in range(self.max_retries + 1):
            try:
                print(f"   ⚡ EXECUTOR: [{task.task_type.value}] (attempt {attempt + 1})...")

                # ── Step 1: LLM sinh query plan ──
                query_plan = self._generate_query_plan(task)
                tool_calls = query_plan.get("tool_calls", [])

                if not tool_calls:
                    print(f"      🧠 LLM returned no tool calls, using fallback")
                    tool_calls = self._fallback_tool_calls(task)

                print(f"      🧠 LLM planned {len(tool_calls)} queries: "
                      f"{query_plan.get('reasoning', 'N/A')[:100]}")

                # ── Step 2: Chạy các query đã sinh ──
                tool_results = self._execute_tool_calls(tool_calls)

                # ── Step 3: LLM phân tích kết quả ──
                analysis = self._analyze_results(task, tool_results)

                result = ExecutorResult(
                    task_id=task.task_id,
                    task_type=task.task_type,
                    success=True,
                    raw_data={
                        "query_plan": query_plan,
                        "tool_results": tool_results,
                    },
                    analysis=analysis.get("analysis", ""),
                    risk_indicators=analysis.get("risk_indicators", []),
                )

                status = "✅" if result.success else "❌"
                print(f"   {status} EXECUTOR: [{task.task_type.value}] "
                      f"→ {len(result.risk_indicators)} indicators")
                return result

            except Exception as e:
                if attempt < self.max_retries:
                    print(f"   ⚠️  Retry ({e})")
                    continue
                return ExecutorResult(
                    task_id=task.task_id,
                    task_type=task.task_type,
                    success=False,
                    error_message=f"Failed: {str(e)}",
                )

    def execute_batch(self, tasks: list[PlannerTask]) -> list[ExecutorResult]:
        """Thực thi batch tasks."""
        print(f"\n{'─'*50}")
        print(f"⚡ EXECUTOR: Batch ({len(tasks)} tasks)")
        print(f"{'─'*50}")

        results = [self.execute_task(task) for task in tasks]

        success_count = sum(1 for r in results if r.success)
        total_indicators = sum(len(r.risk_indicators) for r in results)

        print(f"{'─'*50}")
        print(f"⚡ EXECUTOR: Done ({success_count}/{len(tasks)} ok, "
              f"{total_indicators} indicators)")
        print(f"{'─'*50}\n")

        return results

    # =================================================================
    # STEP 1: LLM SINH QUERY PLAN
    # =================================================================

    def _generate_query_plan(self, task: PlannerTask) -> dict:
        """Gửi task → Gemini → nhận lại tool_calls JSON."""
        user_message = (
            f"Task điều tra:\n"
            f"- Loại: {task.task_type.value}\n"
            f"- Mô tả: {task.description}\n"
            f"- Gợi ý truy vấn: {task.query or 'Không có'}\n"
            f"- Độ ưu tiên: {task.priority}\n\n"
            f"Sinh các truy vấn database tối ưu cho task này."
        )

        plan = gemini_provider.chat_json(
            system_prompt=QUERY_GEN_SYSTEM,
            user_message=user_message,
            temperature=0.1,
        )

        # Validate tool_calls structure
        if "tool_calls" in plan:
            validated = []
            for call in plan["tool_calls"]:
                if isinstance(call, dict) and "tool" in call:
                    if call["tool"] in self._tools:
                        validated.append(call)
                    else:
                        print(f"      ⚠️  Unknown tool '{call['tool']}', skipped")
            plan["tool_calls"] = validated

        return plan

    # =================================================================
    # STEP 2: CHẠY CÁC TOOL CALLS
    # =================================================================

    def _execute_tool_calls(self, tool_calls: list[dict]) -> list[dict]:
        """Chạy từng tool call và thu thập kết quả."""
        results = []
        for call in tool_calls:
            tool_name = call.get("tool", "")
            params = call.get("params", {})

            handler = self._tools.get(tool_name)
            if not handler:
                results.append({
                    "tool": tool_name,
                    "error": f"Unknown tool: {tool_name}",
                    "data": None,
                })
                continue

            try:
                data = handler(params)
                results.append({"tool": tool_name, "params": params, "data": data})
                # Log ngắn gọn
                data_summary = str(data)[:120] if data else "empty"
                print(f"      📊 {tool_name} → {data_summary}")
            except Exception as e:
                results.append({
                    "tool": tool_name,
                    "params": params,
                    "error": str(e),
                    "data": None,
                })
                print(f"      ❌ {tool_name} → {e}")

        return results

    # =================================================================
    # STEP 3: LLM PHÂN TÍCH KẾT QUẢ
    # =================================================================

    def _analyze_results(self, task: PlannerTask, results: list[dict]) -> dict:
        """Gửi raw results → Gemini → nhận risk_indicators + analysis."""
        # Truncate để tránh vượt token limit
        results_str = json.dumps(results, default=str, ensure_ascii=False)
        if len(results_str) > 8000:
            results_str = results_str[:8000] + "\n... (truncated)"

        user_message = (
            f"Task điều tra: [{task.task_type.value}] {task.description}\n\n"
            f"Kết quả truy vấn Database:\n{results_str}\n\n"
            f"Phân tích dữ liệu và xác định các chỉ số rủi ro gian lận."
        )

        analysis = gemini_provider.chat_json(
            system_prompt=ANALYSIS_SYSTEM,
            user_message=user_message,
            temperature=0.1,
        )

        # Ensure valid structure
        if "analysis" not in analysis:
            analysis["analysis"] = "LLM analysis unavailable"
        if "risk_indicators" not in analysis:
            analysis["risk_indicators"] = []

        return analysis

    # =================================================================
    # FALLBACK: Khi LLM không trả tool_calls
    # =================================================================

    def _fallback_tool_calls(self, task: PlannerTask) -> list[dict]:
        """
        Fallback tool calls dựa trên task_type khi LLM không trả kết quả.
        """
        # Extract account ID from description
        import re
        found = re.findall(r'(?:ACC_\w+|MULE_\w+)', task.description)
        acc_id = found[0] if found else "ACC_001"

        fallbacks = {
            TaskType.GRAPH_QUERY: [
                {"tool": "neo4j_neighbors", "params": {"account_id": acc_id, "depth": 2}},
                {"tool": "neo4j_shared_entities", "params": {"account_id": acc_id, "entity_type": "device"}},
                {"tool": "neo4j_blacklisted", "params": {"account_id": acc_id}},
            ],
            TaskType.BEHAVIORAL_ANALYSIS: [
                {"tool": "mongodb_profile", "params": {"account_id": acc_id}},
                {"tool": "mongodb_history", "params": {"account_id": acc_id, "limit": 20}},
            ],
            TaskType.KNOWLEDGE_RETRIEVAL: [
                {"tool": "chromadb_search", "params": {"query": task.description, "top_k": 3}},
            ],
            TaskType.DEVICE_ANALYSIS: [
                {"tool": "neo4j_shared_entities", "params": {"account_id": acc_id, "entity_type": "device"}},
                {"tool": "neo4j_shared_entities", "params": {"account_id": acc_id, "entity_type": "ip"}},
            ],
            TaskType.AMOUNT_PATTERN: [
                {"tool": "mongodb_history", "params": {"account_id": acc_id, "limit": 20}},
                {"tool": "mongodb_profile", "params": {"account_id": acc_id}},
            ],
        }
        return fallbacks.get(task.task_type, [
            {"tool": "mongodb_profile", "params": {"account_id": acc_id}},
        ])

    # =================================================================
    # DATABASE TOOL IMPLEMENTATIONS (Safe wrappers)
    # =================================================================

    def _tool_neo4j_cypher(self, params: dict):
        """Chạy Cypher query do LLM sinh — qua parameterized interface."""
        query = params.get("query", "")
        qparams = params.get("params", {})
        return neo4j_client.run_cypher(query, qparams)

    def _tool_neo4j_neighbors(self, params: dict):
        return neo4j_client.get_neighbors(
            params.get("account_id", ""),
            depth=params.get("depth", 2),
        )

    def _tool_neo4j_shared_entities(self, params: dict):
        return neo4j_client.find_shared_entities(
            params.get("account_id", ""),
            params.get("entity_type", "device"),
        )

    def _tool_neo4j_circular_flows(self, params: dict):
        return neo4j_client.detect_circular_flows(
            params.get("account_id", ""),
        )

    def _tool_neo4j_blacklisted(self, params: dict):
        return neo4j_client.find_connections_to_blacklisted(
            params.get("account_id", ""),
        )

    def _tool_mongodb_profile(self, params: dict):
        return mongodb_client.get_customer_profile(
            params.get("account_id", ""),
        )

    def _tool_mongodb_history(self, params: dict):
        return mongodb_client.get_transaction_history(
            params.get("account_id", ""),
            limit=params.get("limit", 20),
        )

    def _tool_mongodb_related(self, params: dict):
        return mongodb_client.get_related_accounts(
            params.get("account_id", ""),
        )

    def _tool_mongodb_query(self, params: dict):
        return mongodb_client.run_query(
            collection=params.get("collection", ""),
            filter_dict=params.get("filter", {}),
            limit=params.get("limit", 20),
        )

    def _tool_chromadb_search(self, params: dict):
        return vector_store.search(
            query=params.get("query", ""),
            top_k=params.get("top_k", 3),
            filter_type=params.get("filter_type"),
        )

    def _tool_redis_velocity(self, params: dict):
        return redis_service.get_velocity(
            params.get("account_id", ""),
            hours=params.get("hours", 1),
        )

    def _tool_redis_blacklist(self, params: dict):
        return redis_service.is_blacklisted(
            params.get("account_id", ""),
        )
