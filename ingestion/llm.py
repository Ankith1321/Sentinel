import json
import logging
import os
import threading
from collections.abc import Iterator
from functools import lru_cache
from typing import Protocol

import anthropic
import httpx
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer

from ingestion.config import ANTHROPIC_MODEL, LLM_PROVIDER, LOCAL_LLM_MODEL, OPENAI_BASE_URL, OPENAI_MODEL

logger = logging.getLogger(__name__)

REFUSAL_NOTICE = "The model declined to answer this request."


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(self, system: str, messages: list[dict], max_tokens: int) -> str: ...

    def stream(self, system: str, messages: list[dict], max_tokens: int) -> Iterator[str]: ...


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str) -> None:
        self.model = model
        self.client = anthropic.Anthropic()

    def complete(self, system: str, messages: list[dict], max_tokens: int) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )

        if response.stop_reason == "refusal":
            return REFUSAL_NOTICE

        return "".join(block.text for block in response.content if block.type == "text").strip()

    def stream(self, system: str, messages: list[dict], max_tokens: int) -> Iterator[str]:
        with self.client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        ) as stream:
            yield from stream.text_stream
            if stream.get_final_message().stop_reason == "refusal":
                yield REFUSAL_NOTICE


class OpenAICompatibleProvider:
    name = "openai"

    def __init__(self, model: str, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        self.model = model
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
            transport=transport,
        )

    def payload(self, system: str, messages: list[dict], max_tokens: int, stream: bool) -> dict:
        return {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": stream,
            "messages": [{"role": "system", "content": system}, *messages],
        }

    def complete(self, system: str, messages: list[dict], max_tokens: int) -> str:
        response = self.client.post("/chat/completions", json=self.payload(system, messages, max_tokens, False))
        response.raise_for_status()
        return (response.json()["choices"][0]["message"]["content"] or "").strip()

    def stream(self, system: str, messages: list[dict], max_tokens: int) -> Iterator[str]:
        body = self.payload(system, messages, max_tokens, True)
        with self.client.stream("POST", "/chat/completions", json=body) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                data = line.removeprefix("data: ")
                if data == "[DONE]":
                    break
                delta = json.loads(data)["choices"][0]["delta"].get("content")
                if delta:
                    yield delta


class LocalProvider:
    name = "local"

    def __init__(self, model: str) -> None:
        self.model = model
        # One generation at a time: concurrent requests would each need their own KV cache, and an
        # 8 GB card has no room for two.
        self.generation_lock = threading.Lock()
        self.tokenizer = AutoTokenizer.from_pretrained(model)
        self.llm = AutoModelForCausalLM.from_pretrained(model, device_map="auto", dtype=torch.float16)
        logger.info("local LLM %s (fp16) loaded on %s", model, self.llm.device)

    def build_inputs(self, system: str, messages: list[dict]):
        text = self.tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, *messages],
            tokenize=False,
            add_generation_prompt=True,
        )
        return self.tokenizer(text, return_tensors="pt").to(self.llm.device)

    def complete(self, system: str, messages: list[dict], max_tokens: int) -> str:
        inputs = self.build_inputs(system, messages)

        with self.generation_lock, torch.no_grad():
            output = self.llm.generate(**inputs, max_new_tokens=max_tokens, do_sample=False)

        new_tokens = output[0][inputs["input_ids"].shape[1]:]
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    def stream(self, system: str, messages: list[dict], max_tokens: int) -> Iterator[str]:
        inputs = self.build_inputs(system, messages)
        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)

        def generate() -> None:
            with torch.no_grad():
                self.llm.generate(**inputs, max_new_tokens=max_tokens, do_sample=False, streamer=streamer)

        with self.generation_lock:
            worker = threading.Thread(target=generate, daemon=True)
            worker.start()
            yield from streamer
            worker.join()


def openai_compatible_configured() -> bool:
    return bool(OPENAI_BASE_URL and OPENAI_MODEL and os.getenv("SENTINEL_OPENAI_API_KEY"))


def resolve_provider_name() -> str:
    if LLM_PROVIDER in {"anthropic", "openai", "local", "none"}:
        return LLM_PROVIDER

    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"

    if openai_compatible_configured():
        return "openai"

    return "local" if torch.cuda.is_available() else "none"


@lru_cache(maxsize=1)
def get_provider() -> LLMProvider | None:
    name = resolve_provider_name()
    logger.info("llm provider: %s", name)

    if name == "anthropic":
        return AnthropicProvider(ANTHROPIC_MODEL)

    if name == "openai":
        return OpenAICompatibleProvider(OPENAI_MODEL, OPENAI_BASE_URL, os.environ["SENTINEL_OPENAI_API_KEY"])

    if name == "local":
        return LocalProvider(LOCAL_LLM_MODEL)

    return None
