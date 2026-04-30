from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger("weiren.llm")

DEFAULT_BASE_URL = "http://172.16.18.176:11434"
DEFAULT_MODEL = "gemma4:e2b"
SYSTEM_PROMPT = (
    "你是一个本地记忆整理助手。你的任务是根据用户提供的资料来回答问题。\n"
    "规则：\n"
    "1. 只根据下方「相关资料」中的内容回答，不要调用你自己的知识\n"
    "2. 如果资料不足以回答问题，直接说「现有资料不足以确认」\n"
    "3. 回答要简洁、自然，用口语化的中文\n"
    "4. 不要编造具体细节（日期、事件、对话内容）\n"
    "5. 不要提及你是 AI 或语言模型"
)


class LLMService:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_url = f"{self.base_url}/v1/chat/completions"
        self.client = httpx.Client(timeout=60.0)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> Optional[str]:
        try:
            resp = self.client.post(
                self.api_url,
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            choice = data.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content")
            if content:
                return content.strip()
            logger.warning("LLM returned empty response: %s", data)
            return None
        except httpx.HTTPError as exc:
            logger.error("LLM request failed: %s", exc)
            return None
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.error("LLM response parse failed: %s", exc)
            return None

    def answer_from_evidence(self, question: str, evidence_text: str) -> Optional[str]:
        if not evidence_text.strip():
            return None
        return self.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"问题：{question}\n\n相关资料：\n{evidence_text}",
                },
            ],
            temperature=0.3,
            max_tokens=1024,
        )

    def check_available(self) -> bool:
        try:
            resp = self.client.get(f"{self.base_url}/api/version", timeout=5.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self.client.close()
