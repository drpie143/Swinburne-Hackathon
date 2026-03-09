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
from simulators import redis_sim
from mongo_db import mongodb_client
from graph_db import neo4j_client
from vector_store import vector_store
from llm_providers import gemini_provider


# =====================================================================
# SYSTEM PROMPTS CHO GEMINI
# =====================================================================

TOOL_SCHEMA = """
Available database tools for fraud investigation:

1. neo4j_cypher — Run arbitrary Cypher query on Neo4j graph database
   params: {"query": "MATCH ...", "params": {"key": "value"}}
   Neo4j Schema:
     Nodes: (:Account {id, name, risk_score}), (:Device {id, type}), (:IP {id, label}), (:Merchant {id, name, category})
     Relationships:
       (:Account)-[:TRANSFERS_TO {amount, timestamp}]->(:Account)
       (:Account)-[:USES_DEVICE]->(:Device)
       (:Account)-[:CONNECTS_FROM]->(:IP)
       (:Account)-[:PAYS_TO]->(:Merchant)

2. neo4j_neighbors — Get neighbor nodes of an account in the graph
   params: {"account_id": "ACC_001", "depth": 2}

3. neo4j_shared_entities — Find other accounts sharing the same device or IP
   params: {"account_id": "ACC_001", "entity_type": "device" or "ip"}

4. neo4j_circular_flows — Detect circular fund flow patterns
   params: {"account_id": "ACC_001"}

5. neo4j_blacklisted — Find connections to known blacklisted accounts
   params: {"account_id": "ACC_001"}

6. mongodb_profile — Get customer profile (KYC status, risk category, account age, behavioral baseline)
   params: {"account_id": "ACC_001"}

7. mongodb_history — Get recent transaction history
   params: {"account_id": "ACC_001", "limit": 20}

8. mongodb_related — Get list of accounts this account has transacted with
   params: {"account_id": "ACC_001"}

9. mongodb_query — Run custom read-only MongoDB query
   params: {"collection": "customer_profiles" or "transaction_history", "filter": {...}, "limit": 20}

10. chromadb_search — Semantic search in fraud knowledge base (patterns, past cases, regulations)
    params: {"query": "search text describing what to find", "top_k": 3, "filter_type": "fraud_pattern" or "past_investigation" or null}

11. redis_velocity — Get transaction velocity (count in time window)
    params: {"account_id": "ACC_001", "hours": 1}

12. redis_blacklist — Check if an account is on the blacklist
    params: {"account_id": "ACC_001"}
""".strip()

QUERY_GEN_SYSTEM = f"""You are the Executor Agent in a fraud detection system.
Your role: receive an investigation task and generate the optimal database queries to gather evidence.

{TOOL_SCHEMA}

RULES:
- Generate 1-5 tool_calls that best investigate the given task.
- For neo4j_cypher, use parameterized queries with $param syntax for safety.
- Choose tools that match the task type (graph tasks → neo4j tools, behavioral → mongodb, knowledge → chromadb, etc.)
- Be specific: include actual account IDs, search terms, relevant filters.
- Return ONLY valid JSON, no extra text.

Output format:
{{
  "reasoning": "Brief strategy explanation",
  "tool_calls": [
    {{"tool": "tool_name", "params": {{...}}}}
  ]
}}"""

ANALYSIS_SYSTEM = """You are a fraud analyst AI. Analyze database query results from a fraud investigation.

RULES:
- Identify specific, evidence-based risk indicators from the data.
- Each risk_indicator format: "INDICATOR_TYPE: specific evidence details"
- Examples: "HIGH_VELOCITY: 15 transactions in 1h (baseline 2/h)", "SHARED_DEVICE: DEV_X shared with MULE_001", "KYC_NOT_VERIFIED: account ACC_001 status=pending"
- Only flag risks supported by actual evidence in the data.
- If data shows nothing suspicious, return empty risk_indicators list.
- Be concise but thorough in analysis.
- Return ONLY valid JSON, no extra text.

Output format:
{
  "analysis": "2-5 sentence analysis of findings",
  "risk_indicators": ["INDICATOR_TYPE: details", ...]
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
            f"Investigation Task:\n"
            f"- Type: {task.task_type.value}\n"
            f"- Description: {task.description}\n"
            f"- Query hint: {task.query or 'None'}\n"
            f"- Priority: {task.priority}\n\n"
            f"Generate the optimal database queries for this task."
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
            f"Investigation Task: [{task.task_type.value}] {task.description}\n\n"
            f"Database Query Results:\n{results_str}\n\n"
            f"Analyze the data and identify fraud risk indicators."
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
        return redis_sim.get_velocity(
            params.get("account_id", ""),
            hours=params.get("hours", 1),
        )

    def _tool_redis_blacklist(self, params: dict):
        return redis_sim.is_blacklisted(
            params.get("account_id", ""),
        )
