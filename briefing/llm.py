import json

from openai import OpenAI

from .config import EMBED_MODEL, REASONING
from .cost import COST

_client = None


def client():
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def chat_json(step, model, system, user):
    """One chat call that must return a JSON object. Cost is logged under `step`."""
    extra = {"reasoning_effort": REASONING[model]} if model in REASONING else {}
    r = client().chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        **extra,
    )
    COST.add_tokens(step, model, r.usage.prompt_tokens, r.usage.completion_tokens)
    return json.loads(r.choices[0].message.content)


def embed(texts, batch=256):
    out = []
    for i in range(0, len(texts), batch):
        r = client().embeddings.create(model=EMBED_MODEL, input=texts[i : i + batch])
        COST.add_tokens("embed", EMBED_MODEL, r.usage.prompt_tokens)
        out.extend(d.embedding for d in r.data)
    return out
