import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

from ingestion.retriever import retrieve


MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"

_tokenizer = None
_model = None


def load_llm():
    global _tokenizer, _model

    if _tokenizer is not None and _model is not None:
        return _tokenizer, _model

    _tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)

    _model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
    )

    return _tokenizer, _model


def build_prompt(question: str, contexts: list[dict]) -> str:
    context_blocks = []

    for i, ctx in enumerate(contexts, start=1):
        meta = ctx["metadata"]

        context_blocks.append(
            f"[S{i}]\n"
            f"Path: {meta.get('path')}\n"
            f"Language: {meta.get('language')}\n"
            f"Title: {meta.get('title')}\n"
            f"Content:\n{ctx['content']}\n"
        )

    joined_context = "\n\n".join(context_blocks)

    return f"""
You are Sentinel, an AI assistant for the Apache Superset codebase.

Answer using ONLY the provided Superset context.

Rules:
- Do not use outside knowledge.
- Do not guess.
- If a detail is only partially supported, say "The retrieved context only partially supports this."
- Cite specific sources using [S1], [S2], etc.
- Prefer concrete file/module references over generic explanation.
- Do not cite a source unless it directly supports the sentence.

Answer format:
1. Direct answer
2. Evidence from retrieved sources
3. Relevant files/modules
4. What is still unclear from the retrieved context

SUPERSET CONTEXT:
{joined_context}

USER QUESTION:
{question}

ANSWER:
""".strip()


def generate_text(prompt: str) -> str:
    tokenizer, model = load_llm()

    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=220,
            do_sample=False,
        )

    full_text = tokenizer.decode(output[0], skip_special_tokens=True)

    if "ANSWER:" in full_text:
        return full_text.split("ANSWER:", 1)[-1].strip()

    return full_text.strip()


def ask_sentinel(question: str, top_k: int = 5) -> dict:
    contexts = retrieve(question, top_k=top_k)
    prompt = build_prompt(question, contexts)
    answer = generate_text(prompt)

    sources = []

    for i, ctx in enumerate(contexts, start=1):
        meta = ctx["metadata"]
        sources.append(
            {
                "id": f"S{i}",
                "path": meta.get("path"),
                "language": meta.get("language"),
                "title": meta.get("title"),
                "distance": ctx.get("distance"),
                "preview": ctx["content"][:500],
            }
        )

    return {
        "question": question,
        "answer": answer,
        "sources": sources,
        "top_k": top_k,
        "model": MODEL_ID,
    }