from __future__ import annotations

import base64
import ipaddress
import math
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .common import ToolError


def local_url(url: str) -> str:
    # Do not include the supplied URL in error messages: it can contain secrets.
    invalid = "模型地址无效；只支持带合法端口的 localhost 或 loopback IP。"
    try:
        parts = urlsplit(url)
        # Accessing .port performs numeric/range validation; urlsplit itself does not.
        port = parts.port
        local = (
            parts.hostname == "localhost" or ipaddress.ip_address(parts.hostname or "").is_loopback
        )
    except ValueError as exc:
        raise ToolError(invalid) from exc
    if (
        not local
        or parts.scheme not in {"http", "https"}
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or port == 0
    ):
        raise ToolError(invalid)
    return url.rstrip("/")


class LocalClient:
    def __init__(
        self,
        base_url="http://127.0.0.1:11434/v1",
        model="minicpm5-2b",
        *,
        ocr_url=None,
        ocr_model="minicpm-ocr",
        embedding_url=None,
        embedding_model="bge-m3",
        timeout=180,
    ):
        self.base_url = local_url(base_url)
        self.model = model
        self.ocr_url = local_url(ocr_url or base_url)
        self.ocr_model = ocr_model
        self.embedding_url = local_url(embedding_url or base_url)
        self.embedding_model = embedding_model
        try:
            self.timeout = float(timeout)
        except (ValueError, TypeError) as exc:
            raise ToolError("模型超时秒数必须为正数。") from exc
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ToolError("模型超时秒数必须为正数。")

    @classmethod
    def from_env(cls):
        return cls(
            base_url=os.getenv("MINICPM_BASE_URL", "http://127.0.0.1:11434/v1"),
            model=os.getenv("MINICPM_MODEL", "minicpm5-2b"),
            ocr_url=os.getenv("MINICPM_OCR_URL"),
            ocr_model=os.getenv("MINICPM_OCR_MODEL", "minicpm-ocr"),
            embedding_url=os.getenv("MINICPM_EMBED_URL"),
            embedding_model=os.getenv("MINICPM_EMBED_MODEL", "bge-m3"),
            timeout=os.getenv("MINICPM_TIMEOUT", "180"),
        )

    def _request(self, base, route, payload=None):
        try:
            # Never inherit proxy environment variables or follow redirects off-device.
            with httpx.Client(
                timeout=self.timeout, trust_env=False, follow_redirects=False
            ) as client:
                response = (
                    client.get(base + route)
                    if payload is None
                    else client.post(base + route, json=payload)
                )
                if response.status_code == 400:
                    # Read the local error only for classification; never echo it,
                    # since a compatible backend may include private prompt text.
                    try:
                        error = response.json().get("error")
                        message = error.get("message", "") if isinstance(error, dict) else error
                    except (ValueError, AttributeError):
                        message = None
                    if isinstance(message, str) and re.search(
                        r"(?:exceed|too (?:many|long)|maximum|max).{0,120}(?:context|token)|"
                        r"(?:context|token).{0,120}(?:exceed|too (?:many|long)|maximum|max)",
                        message,
                        flags=re.IGNORECASE | re.DOTALL,
                    ):
                        raise ToolError("输入超过模型上下文长度；请缩短内容或分段后重试。")
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
            # Server error bodies can echo sensitive inputs: don't print them.
            raise ToolError(
                f"本地模型请求失败（{type(exc).__name__}）。检查服务、模型名称与超时设置。"
            ) from exc

    def chat(
        self,
        prompt: str,
        system: str = "",
        *,
        model=None,
        image: Path | None = None,
        temperature: float = 0.0,
    ) -> str:
        return self._chat(self.base_url, model or self.model, prompt, system, image, temperature)

    def _chat(self, base, model, prompt, system, image, temperature=0.0):
        content = prompt
        if image is not None:
            image = Path(image)
            if image.stat().st_size > 20 * 1024 * 1024:
                raise ToolError("图片超过 20 MB；请先缩小图片。")
            data = image.read_bytes()
            mime = (
                "image/png"
                if data.startswith(b"\x89PNG")
                else "image/jpeg"
                if data.startswith(b"\xff\xd8")
                else None
            )
            if mime is None:
                raise ToolError("图像请求只支持 PNG 或 JPEG。")
            content = [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"},
                },
                {"type": "text", "text": prompt},
            ]
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": content}
        ]
        response = self._request(
            base,
            "/chat/completions",
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "top_p": 0.95,
                "max_tokens": 2048,
                "stream": False,
                "reasoning_effort": "none",
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        try:
            choice = response["choices"][0]
            result = choice["message"]["content"]
            if choice.get("finish_reason") == "length":
                raise ToolError("模型输出被长度限制截断；请缩短输入后重试。")
            if not isinstance(result, str):
                raise TypeError("not text")
            result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()
            if not result or "<think>" in result:
                raise ValueError("empty or unfinished thinking")
            return result
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ToolError("本地模型返回了空白或无法解析的文本。") from exc

    def ocr(self, image: Path) -> str:
        return self._chat(self.ocr_url, self.ocr_model, "Text Recognition:", "", image)

    def embed(self, texts: list[str]) -> list[list[float]]:
        data = self._request(
            self.embedding_url, "/embeddings", {"model": self.embedding_model, "input": texts}
        )
        try:
            rows = sorted(data["data"], key=lambda row: row["index"])
            vectors = [[float(x) for x in row["embedding"]] for row in rows]
            if [r["index"] for r in rows] != list(range(len(texts))) or not vectors:
                raise ValueError("count")
            size = len(vectors[0])
            if not size or any(
                len(v) != size or not all(math.isfinite(x) for x in v) or sum(x * x for x in v) == 0
                for v in vectors
            ):
                raise ValueError("invalid vectors")
            return vectors
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ToolError("Embedding 服务返回了无效向量。") from exc
