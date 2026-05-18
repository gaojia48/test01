from __future__ import annotations

import os

from agent.config import DeepSeekConfig


class DeepSeekClient:
    def __init__(self, config: DeepSeekConfig):
        _load_dotenv_if_available()
        self.config = config
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.model = os.getenv("DEEPSEEK_MODEL", config.model).strip() or config.model
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", config.base_url).strip() or config.base_url
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _ensure_client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def complete(self, prompt: str, system: str | None = None) -> str:
        if not self.available:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")

        client = self._ensure_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2,
            timeout=self.config.timeout_seconds,
        )
        return response.choices[0].message.content or ""

    def summarize_report(self, user_request: str, raw_output: str) -> str:
        system = (
            "你是 Linux 运维诊断助手。请根据命令输出写出简洁、可答辩展示的中文报告。"
            "报告必须包含：问题概述、关键证据、可能原因、建议处理步骤、涉及的 Linux 命令、风险提示。"
        )
        prompt = (
            f"用户请求：{user_request}\n\n"
            "以下是受控 Shell 脚本的输出，请生成诊断报告：\n"
            f"{raw_output[:12000]}"
        )
        return self.complete(prompt, system=system)


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()
