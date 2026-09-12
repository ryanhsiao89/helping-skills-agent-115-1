"""Google Gen AI Interactions API 包裝層。

Gemini 3.x（含 gemini-3.8-flash）依官方 2026 遷移指引，不再傳送
sampling 參數 temperature / top_p / top_k；改用 thinking_level。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, TypeVar

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
        self.api_keys = tuple(key.strip() for key in api_keys if key and key.strip())
        self.model_name = model_name.strip()
        if not self.api_keys:
            raise ValueError("至少需要一把 Gemini API Key")
        if not self.model_name:
            raise ValueError("必須指定 Gemini 模型名稱")

    def _client(self, api_key: str) -> genai.Client:
        return genai.Client(api_key=api_key)

    @staticmethod
    def _is_gemini_3(model_name: str) -> bool:
        return model_name.startswith("gemini-3")

    def _generation_configs(
        self,
        *,
        model_name: str,
        temperature: float,
        thinking_level: str,
    ) -> tuple[dict[str, Any] | None, ...]:
        """產生相容的 generation_config 重試序列。

        Gemini 3.x：官方指引要求移除 temperature/top_p/top_k，改用 thinking_level。
        非 Gemini 3.x：保留 temperature；若 SDK/模型不接受設定，再以無設定重試。
        """
        if self._is_gemini_3(model_name):
            return (
                {"thinking_level": thinking_level},
                None,
            )

        return (
            {"temperature": temperature},
            None,
        )

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
            configs = self._generation_configs(
                model_name=self.model_name,
                temperature=temperature,
                thinking_level=thinking_level,
            )

            for generation_config in configs:
                started = time.perf_counter()
                try:
                    request: dict[str, Any] = {
                        "model": self.model_name,
                        "input": prompt,
                        "system_instruction": system_instruction,
                        "store": False,
                    }
                    if generation_config is not None:
                        request["generation_config"] = generation_config

                    response = self._client(api_key).interactions.create(**request)
                    text = (response.output_text or "").strip()
                    if not text:
                        raise ValueError("模型回傳空白內容")

                    latency = int((time.perf_counter() - started) * 1000)
                    return TextResult(text=text, latency_ms=latency, key_slot=index)
                except Exception as exc:  # SDK 錯誤型別會隨版本擴充；統一重試/輪替 Key。
                    last_error = exc

        raise GatewayError(
            "Gemini API 呼叫失敗，請檢查 API Key、模型存取權、用量配額或稍後再試。"
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
        selected_model = (model_name or self.model_name).strip()
        last_error: Exception | None = None

        for index, api_key in enumerate(self.api_keys, start=1):
            configs = self._generation_configs(
                model_name=selected_model,
                temperature=temperature,
                thinking_level="low",
            )

            for generation_config in configs:
                started = time.perf_counter()
                raw_text = ""
                try:
                    request: dict[str, Any] = {
                        "model": selected_model,
                        "input": prompt,
                        "system_instruction": system_instruction,
                        "response_format": {
                            "type": "text",
                            "mime_type": "application/json",
                            "schema": schema.model_json_schema(),
                        },
                        "store": False,
                    }
                    if generation_config is not None:
                        request["generation_config"] = generation_config

                    response = self._client(api_key).interactions.create(**request)
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
            "晤談後回饋產生失敗，原始逐字稿仍已保留；請檢查模型存取權或配額後重試。"
        ) from last_error
