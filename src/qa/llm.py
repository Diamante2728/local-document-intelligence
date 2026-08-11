"""Local MLX LLM wrapper. Single shared model instance (8GB machine — never load twice).

Runtime is fully offline: weights are read from the local HF cache. No cloud API is used
anywhere in this project (constraint #1).
"""
import json
import os
import re
import time

# Force offline before anything touches huggingface_hub, so a missing cache fails loudly
# rather than silently reaching for the network at runtime.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

MODEL_ID = "mlx-community/Qwen2.5-7B-Instruct-4bit"

_model = None
_tokenizer = None


def get_llm(model_id: str = MODEL_ID):
    global _model, _tokenizer
    if _model is None:
        from mlx_lm import load
        _model, _tokenizer = load(model_id)
    return _model, _tokenizer


def generate_text(prompt: str, max_tokens: int = 512, system: str = None, model_id: str = MODEL_ID):
    """Returns (text, elapsed_seconds)."""
    from mlx_lm import generate

    model, tokenizer = get_llm(model_id)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    formatted = tokenizer.apply_chat_template(messages, add_generation_prompt=True)

    t0 = time.perf_counter()
    text = generate(model, tokenizer, prompt=formatted, max_tokens=max_tokens, verbose=False)
    return text, time.perf_counter() - t0


def extract_json(text: str):
    """Pull the first JSON object out of an LLM response.

    Small local models wrap JSON in prose or ```json fences even when told not to; this is a
    parsing concession, NOT a place to invent values. If no valid JSON is present we return
    None and the caller must treat that as a failure — never as an empty-but-usable plan.
    """
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidates = []
    if fenced:
        candidates.append(fenced.group(1).strip())
    candidates.append(text.strip())

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        start = candidate.find("{")
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(candidate)):
                ch = candidate[i]
                if esc:
                    esc = False
                    continue
                if ch == "\\" and in_str:
                    esc = True
                    continue
                if ch == '"':
                    in_str = not in_str
                elif not in_str:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                return json.loads(candidate[start:i + 1])
                            except json.JSONDecodeError:
                                break
            start = candidate.find("{", start + 1)
    return None
