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
    
    Gemini 2.5 Flash hỗ trợ:
    - Text generation (báo cáo, reasoning, planning)
    - Vision (phân tích ảnh graph từ Neo4j)
    - Multimodal input
    
    Free tier: 15 req/min, 1,500 req/day
    Đăng ký: https://aistudio.google.com/apikey
    """
    
    def __init__(self):
        if not settings.gemini_api_key:
            print("⚠️  GEMINI_API_KEY chưa được cấu hình! Agents sẽ dùng fallback.")
            self.model = None
        else:
            genai.configure(api_key=settings.gemini_api_key)
            self.model = genai.GenerativeModel(settings.gemini_model_id)
    
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
        
        print(f"⚠️  Không parse được JSON từ Gemini response")
        
        # Fallback cho các agent cụ thể
        return self._fallback_json(system_prompt)
    
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
# SINGLETON INSTANCE - Import từ các module khác
# =====================================================================

gemini_provider = GeminiProvider()
