# ====================================================================
# LLM_PROVIDERS.PY - Kết nối LLM Cloud API (Gemini 2.5 Flash)
# ====================================================================
# THAY ĐỔI QUAN TRỌNG:
#   1. Thread-safe: Lock toàn cục cho genai.configure() → tránh
#      race condition khi nhiều agents cùng gọi API với keys khác nhau
#   2. Exponential backoff: retry tự động khi bị 429 (rate limit)
#      → giải quyết lỗi quota liên tục khi Executor chạy parallel
#   3. Giữ nguyên interface cũ → backward compatible
#
# Gemini free tier: 15 req/min, 1,500 req/day
# Đăng ký: https://aistudio.google.com/apikey
# ====================================================================

from __future__ import annotations
import json
import time
import random
import threading
from typing import Optional

import google.generativeai as genai

from config import settings


# =====================================================================
# GEMINI CLIENT - Thread-Safe + Retry
# =====================================================================

class GeminiProvider:
    """
    Wrapper cho Google Gemini 2.5 Flash.
    
    Thread-safe: dùng Lock toàn cục vì genai.configure() thay đổi
    global state. Lock serialize tất cả API calls → cũng giúp giảm
    rate limit errors (free tier: 15 req/min).
    
    Retry: exponential backoff cho lỗi 429/503/quota.
    """
    
    # genai.configure() thay đổi global state → cần Lock
    # Serialize cũng giúp tự nhiên rate-limit (tốt cho free tier)
    _config_lock = threading.Lock()
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.gemini_api_key
        if not self.api_key:
            print("⚠️  GEMINI_API_KEY chưa được cấu hình! Agents sẽ dùng fallback.")
            self.model = None
        else:
            with GeminiProvider._config_lock:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel(settings.gemini_model_id)
    
    def _safe_call(self, fn, fallback_value, max_retries: int = 3):
        """
        Thread-safe LLM call với:
        1. Lock để tránh API key race condition giữa các agents
        2. Exponential backoff retry cho rate limit (429) errors
        3. Graceful fallback nếu tất cả retries fail
        """
        for attempt in range(max_retries + 1):
            try:
                with GeminiProvider._config_lock:
                    genai.configure(api_key=self.api_key)
                    return fn()
            except (json.JSONDecodeError, TypeError):
                # Lỗi parse → không retry
                return fallback_value
            except Exception as e:
                err = str(e).lower()
                retryable = any(k in err for k in [
                    "429", "quota", "rate", "resource_exhausted",
                    "too many", "overloaded", "503", "unavailable",
                ])
                if retryable and attempt < max_retries:
                    delay = (2 ** attempt) * 2 + random.uniform(0, 1)
                    print(f"   ⏳ Rate limit, retry in {delay:.1f}s "
                          f"(attempt {attempt + 1}/{max_retries})...")
                    time.sleep(delay)
                    continue
                print(f"   ⚠️  Gemini API error: {e}")
                return fallback_value
        return fallback_value
    
    def generate(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ) -> str:
        """Generate text từ Gemini (thread-safe + retry)."""
        if not self.model:
            return self._fallback_response(prompt)
        
        def _call():
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )
            return response.text or ""
        
        return self._safe_call(_call, self._fallback_response(prompt))
    
    def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: Optional[float] = None,
        max_tokens: int = 4096,
    ) -> str:
        """Chat-style generation: system prompt + user message."""
        prompt = f"{system_prompt}\n\n{user_message}"
        return self.generate(
            prompt,
            temperature=temperature if temperature is not None else 0.1,
            max_tokens=max_tokens,
        )
    
    def chat_json(
        self,
        system_prompt: str,
        user_message: str,
        temperature: Optional[float] = None,
    ) -> dict:
        """
        Chat + parse response thành JSON dict (thread-safe + retry).
        
        Strategies:
        1. JSON mode (response_mime_type="application/json")
        2. Plain text + json.loads()
        3. Extract JSON from markdown code block
        4. Extract JSON object from free text
        5. Fallback dict
        """
        if not self.model:
            raw = self._fallback_response(f"{system_prompt}\n\n{user_message}")
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return self._fallback_json(system_prompt)
        
        prompt = f"{system_prompt}\n\n{user_message}"
        temp = temperature if temperature is not None else 0.1
        
        # Strategy 1: JSON mode
        def _json_mode():
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temp,
                    max_output_tokens=4096,
                    response_mime_type="application/json",
                ),
            )
            raw = response.text or ""
            return json.loads(raw)
        
        result = self._safe_call(_json_mode, None)
        if result is not None:
            return result
        
        # Strategy 2: Plain text → parse
        def _text_mode():
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temp,
                    max_output_tokens=4096,
                ),
            )
            return response.text or ""
        
        raw = self._safe_call(_text_mode, "")
        
        if raw:
            # 2a: Direct parse
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
            
            # 2b: Extract from markdown code block
            for delimiter in ["```json", "```"]:
                if delimiter in raw:
                    try:
                        json_str = raw.split(delimiter)[1].split("```")[0].strip()
                        return json.loads(json_str)
                    except (json.JSONDecodeError, IndexError):
                        pass
            
            # 2c: Extract JSON object from free text
            extracted = self._extract_json_object(raw)
            if extracted is not None:
                return extracted
        
        print("   ⚠️  Không parse được JSON từ Gemini response")
        return self._fallback_json(system_prompt)
    
    def _extract_json_object(self, text: str) -> Optional[dict]:
        """Thử lấy JSON object hợp lệ từ chuỗi có thể lẫn text."""
        if not text:
            return None
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        end = -1
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            return None
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            return None
    
    def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        mime_type: str = "image/png",
    ) -> str:
        """Phân tích hình ảnh bằng Gemini Vision (thread-safe)."""
        if not self.model:
            return "Vision analysis không khả dụng (thiếu Gemini API key)"
        
        def _call():
            image_part = {"mime_type": mime_type, "data": image_bytes}
            response = self.model.generate_content([prompt, image_part])
            return response.text or ""
        
        return self._safe_call(_call, "Vision analysis failed: Gemini API unavailable")
    
    # =================================================================
    # FALLBACK RESPONSES
    # =================================================================
    
    def _fallback_response(self, prompt: str) -> str:
        """Fallback khi không có Gemini API key."""
        lower = prompt.lower()
        if "planner" in lower or "investigation plan" in lower:
            return json.dumps({
                "hypothesis": "Cần điều tra thêm dựa trên context Phase 1",
                "tasks": [
                    {"task_type": "behavioral_analysis", "description": "Phân tích behavioral profile của sender", "priority": 10},
                    {"task_type": "graph_query", "description": "Truy vấn graph DB tìm mối quan hệ", "priority": 9},
                    {"task_type": "knowledge_retrieval", "description": "Tìm fraud patterns tương tự trong knowledge base", "priority": 6},
                ]
            })
        elif "detective" in lower or "adjudic" in lower:
            return json.dumps({
                "decision": "escalate",
                "confidence": 0.5,
                "reasoning": "Không có LLM, cần human review",
                "risk_assessment": {"critical": [], "high": [], "medium": []},
                "actions": ["notify_human_reviewer", "hold_transaction"]
            })
        elif "đánh giá" in lower or "evaluate" in lower:
            return json.dumps({
                "done": True,
                "confidence": 0.7,
                "reasoning": "Fallback: đủ evidence để tạo báo cáo",
                "follow_up_tasks": []
            })
        elif "report" in lower or "báo cáo" in lower:
            return (
                "=== BÁO CÁO ĐIỀU TRA GIAN LẬN ===\n"
                "[Fallback mode - Gemini API key chưa cấu hình]\n"
                "Cần cấu hình GEMINI_API_KEY để có báo cáo chi tiết từ AI."
            )
        return "Fallback: Gemini API key chưa được cấu hình."
    
    def _fallback_json(self, system_prompt: str) -> dict:
        """Fallback JSON cho chat_json() khi parse fail."""
        lower = system_prompt.lower()
        if "planner" in lower:
            return {
                "hypothesis": "Default: cần điều tra",
                "tasks": [
                    {"task_type": "behavioral_analysis", "description": "Phân tích behavioral", "priority": 10},
                    {"task_type": "graph_query", "description": "Truy vấn graph", "priority": 9},
                ]
            }
        elif "detective" in lower:
            return {"decision": "escalate", "confidence": 0.5, "reasoning": "Cần human review", "actions": []}
        elif "đánh giá" in lower or "evaluate" in lower:
            return {"done": True, "confidence": 0.7, "reasoning": "Fallback evaluation", "follow_up_tasks": []}
        return {}


class GeminiProviderPool:
    """Round-robin pool cho nhiều GeminiProvider (dùng nhiều API keys)."""

    def __init__(self, providers: list[GeminiProvider]):
        self.providers = providers
        self._idx = 0
        self._lock = threading.Lock()

    def _next(self) -> GeminiProvider:
        with self._lock:
            provider = self.providers[self._idx]
            self._idx = (self._idx + 1) % len(self.providers)
            return provider

    def generate(self, *args, **kwargs):
        return self._next().generate(*args, **kwargs)

    def chat(self, *args, **kwargs):
        return self._next().chat(*args, **kwargs)

    def chat_json(self, *args, **kwargs):
        return self._next().chat_json(*args, **kwargs)

    def analyze_image(self, *args, **kwargs):
        return self._next().analyze_image(*args, **kwargs)


# =====================================================================
# PER-AGENT PROVIDER INSTANCES
# =====================================================================
# Mỗi agent dùng API key riêng → tránh hết quota khi demo
# Thread-safe: GeminiProvider._config_lock serialize API calls
# =====================================================================

gemini_provider_planner = GeminiProvider(api_key=settings.gemini_api_key_planner or None)

_executor_pool_keys = [
    key.strip() for key in settings.gemini_api_key_executor_pool.split(",")
    if key.strip()
]
if _executor_pool_keys:
    _executor_providers = [GeminiProvider(api_key=k) for k in _executor_pool_keys]
    gemini_provider_executor = GeminiProviderPool(_executor_providers)
else:
    gemini_provider_executor = GeminiProvider(api_key=settings.gemini_api_key_executor or None)

gemini_provider_detective = GeminiProvider(api_key=settings.gemini_api_key_detective or None)
gemini_provider_vision = GeminiProvider(api_key=settings.gemini_api_key_vision or None)
gemini_provider_report = GeminiProvider(api_key=settings.gemini_api_key_report or None)

# Backward-compatible default
gemini_provider = gemini_provider_planner
