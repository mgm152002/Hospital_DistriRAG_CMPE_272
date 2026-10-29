"""Free-only OpenRouter policy. No network or credentials in this module."""
import re
from decimal import Decimal, InvalidOperation
from typing import Any

DEFAULT_MODEL = "openrouter/free"
FREE_VARIANT = re.compile(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+:free")
ROUTER = {"id": DEFAULT_MODEL, "name": "Automatic · available free models", "context_length": 0}


def require_free_model(model: str) -> str:
    if model != DEFAULT_MODEL and not FREE_VARIANT.fullmatch(model):
        raise ValueError("Choose OpenRouter's free router or an available :free model. Paid models are disabled.")
    return model


def free_models(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {DEFAULT_MODEL: dict(ROUTER)}
    for model in catalog.get("data", []):
        try:
            model_id = require_free_model(model["id"])
            pricing = model["pricing"]
            if not {"prompt", "completion"} <= pricing.keys():
                continue
            if not all(Decimal(str(value)).is_finite() and Decimal(str(value)) == 0 for value in pricing.values()):
                continue
            found[model_id] = {"id": model_id, "name": str(model.get("name") or model_id),
                               "context_length": int(model.get("context_length") or 0)}
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
    return [found.pop(DEFAULT_MODEL)] + sorted(found.values(), key=lambda entry: entry["name"].casefold())


# The free router may pick a reasoning model, which can spend the whole budget thinking and return no answer.
# Ask for low effort, keep the reasoning out of the stream, and leave room for the answer itself.
REASONING = {"effort": "low", "exclude": True}
MIN_TOKENS = 1500


def free_request(model: str, messages: list[dict], max_tokens: int) -> dict:
    return {"model": require_free_model(model), "messages": messages, "stream": True,
            "max_tokens": max(max_tokens, MIN_TOKENS), "temperature": 0.1, "reasoning": dict(REASONING),
            "provider": {"max_price": {"prompt": 0, "completion": 0, "request": 0, "image": 0}}}
