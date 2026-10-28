"""Covers: DP-2, RL-10, CP-4."""
import asyncio
import json

import httpx
import pytest

from common.llm import ProviderInfo, ProviderUnavailable, load_providers
from common.llm.fake import FakeLLM, NoLLM
from common.llm.openai_compat import OpenAICompatible

INFO = ProviderInfo(name="t", kind="openai_compatible", base_url="https://llm.test/v1", model="m",
                    api_key_env="", external=True, baa_signed=False, retains_data=True, region="us")


def test_load_providers_registry():
    providers = load_providers("config/providers.yaml")
    assert providers["openrouter-free"].external and providers["openrouter-free"].retains_data
    assert not providers["local-ollama"].external


async def test_fake_llm_streams_tokens():
    tokens = [t async for t in FakeLLM().stream([{"role": "user", "content": "Passages:\n[1] Hand v2\nWash."}])]
    assert len(tokens) > 1 and "[1]" in "".join(tokens)


async def test_no_llm_raises():
    with pytest.raises(ProviderUnavailable):
        async for _ in NoLLM().stream([]):
            pass


async def test_openai_compat_streams():
    def handler(request):
        body = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': t}}]})}\n\n" for t in ["Hi", " there"])
        return httpx.Response(200, text=body + "data: [DONE]\n\n")
    llm = OpenAICompatible(INFO, transport=httpx.MockTransport(handler))
    assert "".join([t async for t in llm.stream([{"role": "user", "content": "x"}])]) == "Hi there"


async def test_openai_compat_retries_then_raises():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)
    llm = OpenAICompatible(INFO, transport=httpx.MockTransport(handler), backoff=0)
    with pytest.raises(ProviderUnavailable):
        async for _ in llm.stream([{"role": "user", "content": "x"}]):
            pass
    assert len(calls) == 3


async def test_openrouter_enforces_zero_prices_on_outbound_request():
    from dataclasses import replace

    received = []

    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"Policy [1]."}}]}\n\ndata: [DONE]\n\n')

    info = replace(INFO, base_url="https://openrouter.ai/api/v1", model="openrouter/free")
    llm = OpenAICompatible(info, transport=httpx.MockTransport(handler), api_key="sk-or-test-key")
    assert "Policy" in "".join([token async for token in llm.stream([])])
    assert received[0]["provider"]["max_price"] == {"prompt": 0, "completion": 0, "request": 0, "image": 0}
    assert "models" not in received[0]


async def test_paid_openrouter_model_never_reaches_transport():
    from dataclasses import replace

    def handler(request):
        raise AssertionError("A paid request must not be sent")

    llm = OpenAICompatible(replace(INFO, base_url="https://openrouter.ai/api/v1", model="vendor/paid"),
                          transport=httpx.MockTransport(handler), api_key="sk-or-test-key")
    with pytest.raises(ProviderUnavailable, match="Paid"):
        async for _ in llm.stream([]):
            pass


async def test_network_disabled_while_waiting_prevents_http_dispatch(tmp_path):
    from dataclasses import replace

    from common.egress import EgressBlocked
    from common.llm.network import OpenRouterNetworkGuard
    from common.llm.preferences import ChatPreferences

    path = tmp_path / "chat.json"
    preferences = ChatPreferences(path)
    preferences.save("openrouter/free", network_access=True)

    def handler(request):
        raise AssertionError("Network-disabled requests must not reach the transport")

    llm = OpenAICompatible(replace(INFO, base_url="https://openrouter.ai/api/v1", model="openrouter/free"),
                          guard=OpenRouterNetworkGuard(str(path)), transport=httpx.MockTransport(handler),
                          api_key="sk-or-test-key", limit=1)
    await llm.semaphore.acquire()

    async def generate():
        return [token async for token in llm.stream([])]

    task = asyncio.create_task(generate())
    await asyncio.sleep(0)
    preferences.save("openrouter/free", network_access=False)
    llm.semaphore.release()
    with pytest.raises(EgressBlocked):
        await task


def test_fake_llm_quotes_first_real_sentence():
    from common.llm.fake import cited_answer
    text = cited_answer([{"role": "system", "content": "Passages:\n[1] Sepsis v2 — Purpose, p.1\n1. Purpose\n"
                                                      "Early recognition of sepsis saves lives. More."}])
    assert text.endswith("Early recognition of sepsis saves lives [1].") and not text.startswith("1")


# ---- empty answers from free reasoning models (1 in 6 live questions came back blank) -------------------------------

EMPTY = 'data: {"choices":[{"delta":{"reasoning":"thinking..."}}]}\n\ndata: [DONE]\n\n'
ANSWER = 'data: {"choices":[{"delta":{"content":"Rub for 20 seconds [1]."}}]}\n\ndata: [DONE]\n\n'


async def test_an_empty_answer_is_retried_and_the_next_one_is_used():
    replies = iter([EMPTY, ANSWER])
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, text=next(replies))

    llm = OpenAICompatible(INFO, transport=httpx.MockTransport(handler), retries=2, backoff=0)
    assert "".join([t async for t in llm.stream([])]) == "Rub for 20 seconds [1]."
    assert len(calls) == 2


async def test_answers_that_stay_empty_are_reported_as_unavailable_not_returned_as_nothing():
    llm = OpenAICompatible(INFO, transport=httpx.MockTransport(lambda r: httpx.Response(200, text=EMPTY)),
                           retries=1, backoff=0)
    with pytest.raises(ProviderUnavailable):
        [t async for t in llm.stream([])]


async def test_openrouter_asks_for_low_reasoning_effort_and_room_for_the_answer():
    from dataclasses import replace

    received = []

    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, text=ANSWER)

    info = replace(INFO, base_url="https://openrouter.ai/api/v1", model="openrouter/free")
    llm = OpenAICompatible(info, transport=httpx.MockTransport(handler), api_key="sk-or-test-key")
    [t async for t in llm.stream([])]
    assert received[0]["reasoning"] == {"effort": "low", "exclude": True}
    assert received[0]["max_tokens"] >= 1500


async def test_rate_limited_free_model_fails_over_to_free_router_with_same_data_policy():
    from dataclasses import replace

    received = []

    def handler(request):
        body = json.loads(request.content)
        received.append(body)
        if body["model"] == "vendor/preferred:free":
            return httpx.Response(429, json={"error": {"code": 429, "message": "Shared upstream quota"}})
        return httpx.Response(200, text=ANSWER)

    info = replace(INFO, base_url="https://openrouter.ai/api/v1", model="vendor/preferred:free", retains_data=False)
    llm = OpenAICompatible(info, transport=httpx.MockTransport(handler), api_key="sk-or-test-key", backoff=0)
    assert "20 seconds" in "".join([t async for t in llm.stream([])])
    assert [body["model"] for body in received] == ["vendor/preferred:free", "openrouter/free"]
    for body in received:
        assert body["provider"]["data_collection"] == "deny"
        assert body["provider"]["max_price"] == {"prompt": 0, "completion": 0, "request": 0, "image": 0}
    assert llm.info.model == "vendor/preferred:free"


async def test_provider_http_status_is_preserved_without_retrying_invalid_credentials():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(401)

    llm = OpenAICompatible(INFO, transport=httpx.MockTransport(handler), backoff=0)
    with pytest.raises(ProviderUnavailable) as caught:
        [t async for t in llm.stream([])]
    assert len(requests) == 1
    assert caught.value.status_code == 401


async def test_usage_only_stream_events_do_not_discard_a_valid_answer():
    response = ANSWER.replace("data: [DONE]", 'data: {"choices":[],"usage":{"total_tokens":25}}\n\ndata: [DONE]')
    llm = OpenAICompatible(INFO, transport=httpx.MockTransport(lambda r: httpx.Response(200, text=response)))
    assert "".join([t async for t in llm.stream([])]) == "Rub for 20 seconds [1]."


async def test_streamed_rate_limit_also_fails_over_to_free_router():
    from dataclasses import replace

    models = []

    def handler(request):
        model = json.loads(request.content)["model"]
        models.append(model)
        if model == "vendor/preferred:free":
            return httpx.Response(200, text='data: {"error":{"code":429,"message":"Quota"}}\n\n')
        return httpx.Response(200, text=ANSWER)

    info = replace(INFO, base_url="https://openrouter.ai/api/v1", model="vendor/preferred:free")
    llm = OpenAICompatible(info, transport=httpx.MockTransport(handler), api_key="sk-or-test-key", backoff=0)
    assert "20 seconds" in "".join([t async for t in llm.stream([])])
    assert models == ["vendor/preferred:free", "openrouter/free"]


async def test_a_partial_answer_is_not_spliced_with_a_retried_answer():
    calls = []

    def handler(request):
        calls.append(request)
        text = 'data: {"choices":[{"delta":{"content":"Partial answer"}}]}\n\n'
        return httpx.Response(200, text=text + 'data: {"error":{"code":503}}\n\n')

    llm = OpenAICompatible(INFO, transport=httpx.MockTransport(handler), backoff=0)
    tokens = []
    with pytest.raises(ProviderUnavailable) as caught:
        async for token in llm.stream([]):
            tokens.append(token)
    assert tokens == ["Partial answer"] and len(calls) == 1
    assert caught.value.status_code == 503
