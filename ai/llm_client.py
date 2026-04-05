# ai/llm_client.py
import json
import re
import httpx
from typing import Optional
from utils.logger import get_logger

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "deepseek-r1:8b"   


class OllamaClient:
    """
    对 Ollama /api/chat 的轻量封装。
    使用同步 httpx，适配当前项目风格；如需异步可换 AsyncClient。
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = OLLAMA_BASE_URL,
        timeout: float = 300.0,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.logger = get_logger(self.__class__.__name__)

    def chat(self, system: str, user: str) -> str:
        """
        发送一次 chat 请求，返回 assistant 纯文本回复。
        """
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            resp = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except httpx.HTTPStatusError as e:
            self.logger.error(f"Ollama HTTP error: {e.response.status_code} {e.response.text}")
            raise
        except Exception as e:
            self.logger.error(f"Ollama request failed: {e}")
            raise

    def extract_json(self, system: str, user: str) -> dict:
        """
        调用 chat 后，从回复中解析第一个 JSON 对象。
        DeepSeek 有时会在 <think>...</think> 包裹推理，需要剥离。
        """
        raw = self.chat(system, user)

        # 1. 剥离 <think>...</think> 块（DeepSeek-R1 推理痕迹）
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        # 2. 提取第一个 {...} JSON 块
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            self.logger.warning(f"未找到 JSON，原始回复：{raw[:200]}")
            raise ValueError("LLM 回复中未找到合法 JSON")

        return json.loads(match.group())