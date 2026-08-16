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

# Stage 2: path to a LoRA adapter directory to fuse on load, or None for the base model.
# Set by the 2C comparison harness to switch arms without reloading the module. Keyed into the
# cache below so switching arms cannot silently reuse the previously loaded weights — an arm that
# reports the wrong model's numbers would invalidate the entire before/after.
ADAPTER_PATH = None

_model = None
_tokenizer = None
_loaded_key = None


def get_llm(model_id: str = None, adapter_path: str = None):
    """Load (and cache) the model. `model_id=None` means "whatever MODEL_ID is set to NOW".

    NOT `model_id=MODEL_ID` as a default. A default argument is bound once, at function-definition
    time, so a caller that reassigns the module-level MODEL_ID would silently keep getting the
    original model. That bug ran the entire Stage 2C arm-1 evaluation on the 7B instead of the 3B
    it was configured for, and was only caught because the 3B LoRA adapter then failed to apply to
    7B-shaped weights (hidden dim 3584 vs 2048).
    """
    global _model, _tokenizer, _loaded_key
    model_id = model_id or MODEL_ID          # resolved at CALL time, never at def time
    adapter = adapter_path if adapter_path is not None else ADAPTER_PATH
    key = (model_id, adapter)
    if _model is None or _loaded_key != key:
        from mlx_lm import load
        _model, _tokenizer = load(model_id, adapter_path=adapter) if adapter else load(model_id)
        _loaded_key = key
    return _model, _tokenizer


def free_gpu_cache():
    """Release MLX's cached Metal buffers.

    WHY THIS IS NEEDED — found during the Stage 2C run, which stalled after ~24 questions.

    MLX keeps freed device buffers in a cache and reuses them. With a long-lived process asking
    many questions of varying sequence length, that cache grows monotonically: the evaluation
    process reached **7.8 GB on an 8 GB machine**, pushing swap to 4.7 GB and system free memory
    to 6%. The process was not deadlocked — a stack sample showed it inside a normal MLX
    generation loop — it was thrashing, and per-question latency had blown out from ~80 s to
    over 17 minutes.

    Killing it dropped swap from 4,737 MB to 2,054 MB instantly, which confirmed the process was
    the cause rather than a victim of unrelated system pressure.

    Called between questions so cache growth cannot accumulate across an evaluation run.
    """
    try:
        import mlx.core as mx
        mx.clear_cache()
    except Exception:
        pass          # never let cache hygiene break an evaluation


def cache_limit_gb(gb: float = 1.0):
    """Cap MLX's buffer cache. Belt and braces alongside free_gpu_cache()."""
    try:
        import mlx.core as mx
        mx.set_cache_limit(int(gb * 1024 ** 3))
    except Exception:
        pass


def generate_text(prompt: str, max_tokens: int = 512, system: str = None, model_id: str = None):
    """Returns (text, elapsed_seconds)."""
    from mlx_lm import generate

    model, tokenizer = get_llm(model_id)   # None -> current MODEL_ID, see get_llm docstring
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
