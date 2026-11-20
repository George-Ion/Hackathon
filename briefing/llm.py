import json

from .config import EMBED_MODEL, REASONING, PRICES
from .cost import COST, ensure_budget

_client = None


def client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(timeout=90, max_retries=3)
    return _client


def _estimate_chat_usd(model: str, system: str, user: str) -> float:
    # Rough 4 chars/token heuristic; assume 30% as completion share
    chars = len(system or "") + len(user or "")
    tok_in = max(1, chars // 4)
    tok_out = max(1, int(tok_in * 0.3))
    p_in, p_out = PRICES.get(model, (0.0, 0.0))
    return tok_in / 1e6 * p_in + tok_out / 1e6 * p_out


def chat_json(step, model, system, user):
    """One chat call that must return a JSON object. Cost is logged under `step`."""
    # Budget gate before the call
    ensure_budget(_estimate_chat_usd(model, system, user), step, model)
    extra = {"reasoning_effort": REASONING[model]} if model in REASONING else {}
    # First attempt
    r = client().chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        **extra,
    )
    COST.add_tokens(step, model, r.usage.prompt_tokens, r.usage.completion_tokens)
    content = r.choices[0].message.content
    try:
        return json.loads(content)
    except Exception:
        # Retry once on JSON parse error with a second API call
        r2 = client().chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            **extra,
        )
        COST.add_tokens(step, model, r2.usage.prompt_tokens, r2.usage.completion_tokens)
        content2 = r2.choices[0].message.content
        try:
            return json.loads(content2)
        except Exception as e:
            raise ValueError(f"chat_json step '{step}' returned non-JSON twice") from e


def _estimate_embed_usd(model: str, texts) -> float:
    chars = sum(len(t or "") for t in texts)
    tok_in = max(1, chars // 4)
    p_in, _ = PRICES.get(model, (0.0, 0.0))
    return tok_in / 1e6 * p_in


def embed(texts, batch=256):
    out = []
    for i in range(0, len(texts), batch):
        subset = texts[i : i + batch]
        ensure_budget(_estimate_embed_usd(EMBED_MODEL, subset), "embed", EMBED_MODEL)
        r = client().embeddings.create(model=EMBED_MODEL, input=subset)
        COST.add_tokens("embed", EMBED_MODEL, r.usage.prompt_tokens)
        out.extend(d.embedding for d in r.data)
    return out
