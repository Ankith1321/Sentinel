import logging
import os
import threading
from collections.abc import Iterator
from functools import lru_cache
from typing import Protocol

import anthropic
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TextIteratorStreamer

from ingestion.config import ANTHROPIC_MODEL, LLM_PROVIDER, LOCAL_LLM_MODEL, LOCAL_LLM_QUANT

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


class LocalProvider:
    name = "local"

    def __init__(self, model: str, quantization: str = "") -> None:
        self.model = model
        # One generation at a time: concurrent requests would each need their own KV cache, and an
        # 8 GB card has no room for two.
        self.generation_lock = threading.Lock()
        self.tokenizer = AutoTokenizer.from_pretrained(model)
        self.llm = AutoModelForCausalLM.from_pretrained(model, device_map="auto", **self.load_options(quantization))
        logger.info("local LLM %s (%s) loaded on %s", model, quantization or "fp16", self.llm.device)

    @staticmethod
    def load_options(quantization: str) -> dict:
        if quantization == "4bit":
            return {
                "quantization_config": BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.float16,
                )
            }
        if quantization == "8bit":
            return {"quantization_config": BitsAndBytesConfig(load_in_8bit=True)}
        return {"dtype": torch.float16}

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


def resolve_provider_name() -> str:
    if LLM_PROVIDER in {"anthropic", "local"}:
        return LLM_PROVIDER

    return "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "local"


@lru_cache(maxsize=1)
def get_provider() -> LLMProvider:
    name = resolve_provider_name()
    logger.info("llm provider: %s", name)

    if name == "anthropic":
        return AnthropicProvider(ANTHROPIC_MODEL)

    return LocalProvider(LOCAL_LLM_MODEL, LOCAL_LLM_QUANT)
