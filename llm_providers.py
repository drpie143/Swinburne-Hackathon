# ====================================================================
# LLM_PROVIDERS.PY - Kết nối LLM Cloud API (Gemini 2.5 Flash)
# ====================================================================
# Tất cả agents dùng Google Gemini 2.5 Flash (free tier):
#   - Planner Agent: tạo kế hoạch điều tra
#   - Vision Agent: phân tích kết quả executor
#   - Report Agent: tạo báo cáo
#   - Detective Agent: ra quyết định cuối
#
# Gemini free tier: 15 req/min, 1,500 req/day
# Đăng ký: https://aistudio.google.com/apikey
# ====================================================================

from __future__ import annotations
import json
from typing import Optional

import google.generativeai as genai

from config import settings


# =====================================================================
# GEMINI CLIENT - Cho TẤT CẢ agents
# =====================================================================

class GeminiProvider:
    """
    Wrapper cho Google Gemini 2.5 Flash.
    
    Mỗi agent có instance riêng với API key riêng để tránh hết quota.
    Nếu api_key không truyền vào → fallback về gemini_api_key chung.
    
    Free tier: 15 req/min, 1,500 req/day PER KEY
    """
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.gemini_api_key
        if not self.api_key:
            print("⚠️  GEMINI_API_KEY chưa được cấu hình! Agents sẽ dùng fallback.")
            self.model = None
        else:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(settings.gemini_model_id)
    
    def _ensure_configured(self):
        """Đảm bảo global genai config đang dùng đúng API key của provider này."""
        if self.api_key:
            genai.configure(api_key=self.api_key)
    
    def generate(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ) -> str:
        """
        Generate text từ Gemini.
        
        Args:
            prompt: Full prompt (system + user combined)
            temperature: Creativity level
            max_tokens: Max output tokens
            
        Returns:
            Generated text
        """
        if not self.model:
            return self._fallback_response(prompt)
        
        self._ensure_configured()
        try:
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )
            return response.text or ""
        except Exception as e:
            print(f"⚠️  Gemini API error: {e}")
            return self._fallback_response(prompt)
    
    def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: Optional[float] = None,
        max_tokens: int = 4096,
    ) -> str:
        """
        Chat-style generation: system prompt + user message.
        
        Dùng bởi Planner Agent, Detective Agent.
        
        Args:
            system_prompt: Vai trò / instructions cho LLM
            user_message: Message chính cần LLM xử lý
            temperature: Override temperature
            max_tokens: Giới hạn tokens output
            
        Returns:
            Text response
        """
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
        Chat + parse response thành JSON dict.
        
        Dùng cho Planner (tạo task list JSON) và Detective (decision JSON).
        
        Returns:
            Parsed JSON dict, hoặc {} nếu parse fail
        """
        if not self.model:
            raw = self._fallback_response(f"{system_prompt}\n\n{user_message}")
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return self._fallback_json(system_prompt)
        
        prompt = f"{system_prompt}\n\n{user_message}"
        
        # Dùng response_mime_type để buộc Gemini trả JSON thuần
        self._ensure_configured()
        try:
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature if temperature is not None else 0.1,
                    max_output_tokens=4096,
                    response_mime_type="application/json",
                ),
            )
            raw = response.text or ""
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
        except Exception as e:
            print(f"⚠️  Gemini JSON mode error: {e}")
        
        # Fallback: gọi bình thường rồi parse
        raw = self.chat(
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=temperature,
        )
        
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

        # Thử extract JSON object từ chuỗi tự do (thinking/markdown)
        extracted = self._extract_json_object(raw)
        if extracted is not None:
            return extracted
        
        print(f"⚠️  Không parse được JSON từ Gemini response")
        
        # Fallback cho các agent cụ thể
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
        """
        Phân tích hình ảnh bằng Gemini Vision.
        """
        if not self.model:
            return "Vision analysis không khả dụng (thiếu Gemini API key)"
        
        self._ensure_configured()
        try:
            image_part = {
                "mime_type": mime_type,
                "data": image_bytes,
            }
            response = self.model.generate_content([prompt, image_part])
            return response.text or ""
        except Exception as e:
            print(f"⚠️  Gemini Vision error: {e}")
            return f"Vision analysis failed: {str(e)}"
    
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


# =====================================================================
# PER-AGENT PROVIDER INSTANCES
# =====================================================================
# Mỗi agent dùng API key riêng → tránh hết quota khi demo
# Nếu key riêng trống → fallback về GEMINI_API_KEY chung
# =====================================================================

gemini_provider_planner = GeminiProvider(api_key=settings.gemini_api_key_planner or None)
gemini_provider_detective = GeminiProvider(api_key=settings.gemini_api_key_detective or None)
gemini_provider_vision = GeminiProvider(api_key=settings.gemini_api_key_vision or None)
gemini_provider_report = GeminiProvider(api_key=settings.gemini_api_key_report or None)

# Executor pool: tối đa 5 providers, mỗi provider giữ 1 API key riêng
# Cho phép chạy song song tối đa 5 tasks đồng thời
_executor_keys = settings.gemini_api_key_executor_list
if not _executor_keys:
    # Fallback: dùng API key chung
    _executor_keys = [settings.gemini_api_key] if settings.gemini_api_key else []

gemini_provider_executor_pool: list[GeminiProvider] = [
    GeminiProvider(api_key=key) for key in _executor_keys
]

print(f"   🔑 Executor pool: {len(gemini_provider_executor_pool)} API keys loaded")

# Backward-compatible: giữ lại 1 instance cho import cũ
gemini_provider_executor = gemini_provider_executor_pool[0] if gemini_provider_executor_pool else GeminiProvider()

# Backward-compatible default
gemini_provider = gemini_provider_planner

