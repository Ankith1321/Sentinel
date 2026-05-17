import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

from ingestion.retriever import retrieve


MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"


def load_llm():
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
    )

    return tokenizer, model


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

SUPSERSET CONTEXT:
{joined_context}

USER QUESTION:
{question}

ANSWER:
""".strip()


def generate_answer(question: str, top_k: int = 5) -> str:
    contexts = retrieve(question, top_k=top_k)

    prompt = build_prompt(question, contexts)

    tokenizer, model = load_llm()

    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=500,
            do_sample=False,
        )

    full_text = tokenizer.decode(output[0], skip_special_tokens=True)

    answer = full_text.split("ANSWER:", 1)[-1].strip()

    sources = "\n\nSources:\n"
    for i, ctx in enumerate(contexts, start=1):
        meta = ctx["metadata"]
        sources += f"- [S{i}] {meta.get('path')}\n"

    return answer + sources


if __name__ == "__main__":
    question = input("Ask Sentinel: ")
    answer = generate_answer(question, top_k=5)
    print("\n" + answer)