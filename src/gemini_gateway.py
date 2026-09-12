"""Google Gen AI Interactions API 包裝層。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TypeVar

from google import genai
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class GatewayError(RuntimeError):
    """對外不暴露 API Key 或完整供應商錯誤訊息。"""


@dataclass(frozen=True)
class TextResult:
    text: str
    latency_ms: int
    key_slot: int


@dataclass(frozen=True)
class StructuredResult:
    parsed: BaseModel
    raw_text: str
    latency_ms: int
    key_slot: int


class GeminiGateway:
    def __init__(self, api_keys: tuple[str, ...], model_name: str):
        self.api_keys = tuple(key for key in api_keys if key)
        self.model_name = model_name
        if not self.api_keys:
            raise ValueError("至少需要一把 Gemini API Key")

    def _client(self, api_key: str) -> genai.Client:
        return genai.Client(api_key=api_key)

    def generate_text(
        self,
        *,
        prompt: str,
        system_instruction: str,
        temperature: float,
        thinking_level: str = "low",
    ) -> TextResult:
        last_error: Exception | None = None
        for index, api_key in enumerate(self.api_keys, start=1):
            # Gemini 3.x 使用 thinking_level；若指定模型不支援，第二次會移除它。
            configs = (
                {"temperature": temperature, "thinking_level": thinking_level},
                {"temperature": temperature},
            )
            for generation_config in configs:
                started = time.perf_counter()
                try:
                    response = self._client(api_key).interactions.create(
                        model=self.model_name,
                        input=prompt,
                        system_instruction=system_instruction,
                        store=False,
                        # google-genai 2.23 的型別序列化器尚未保留 temperature；
                        # extra_body 是 SDK 提供的擴充欄位，可確保研究設定送達 API。
                        extra_body={"generation_config": generation_config},
                    )
                    text = (response.output_text or "").strip()
                    if not text:
                        raise ValueError("模型回傳空白內容")
                    latency = int((time.perf_counter() - started) * 1000)
                    return TextResult(text=text, latency_ms=latency, key_slot=index)
                except Exception as exc:  # SDK 錯誤型別會隨版本擴充；統一輪替 Key。
                    last_error = exc

        raise GatewayError(
            "Gemini API 呼叫失敗，請檢查 API Key、模型名稱、用量配額或稍後再試。"
        ) from last_error

    def generate_structured(
        self,
        *,
        prompt: str,
        system_instruction: str,
        temperature: float,
        schema: type[T],
        model_name: str | None = None,
    ) -> StructuredResult:
        selected_model = model_name or self.model_name
        last_error: Exception | None = None
        for index, api_key in enumerate(self.api_keys, start=1):
            configs = (
                {"temperature": temperature, "thinking_level": "low"},
                {"temperature": temperature},
            )
            for generation_config in configs:
                started = time.perf_counter()
                raw_text = ""
                try:
                    response = self._client(api_key).interactions.create(
                        model=selected_model,
                        input=prompt,
                        system_instruction=system_instruction,
                        response_format={
                            "type": "text",
                            "mime_type": "application/json",
                            "schema": schema.model_json_schema(),
                        },
                        store=False,
                        extra_body={"generation_config": generation_config},
                    )
                    raw_text = (response.output_text or "").strip()
                    parsed = schema.model_validate_json(raw_text)
                    latency = int((time.perf_counter() - started) * 1000)
                    return StructuredResult(
                        parsed=parsed,
                        raw_text=raw_text,
                        latency_ms=latency,
                        key_slot=index,
                    )
                except (ValidationError, ValueError, TypeError) as exc:
                    last_error = exc
                except Exception as exc:
                    last_error = exc

        raise GatewayError(
            "晤談後回饋產生失敗，原始逐字稿仍已保留；請檢查模型或配額後重試。"
        ) from last_error
