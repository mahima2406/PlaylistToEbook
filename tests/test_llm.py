"""Gateway behaviour against a fake provider. No network, no credentials."""
import json
import httpx
import pytest
from coursebook.core import read, write
from coursebook.llm import (Gateway, BudgetExceeded, CacheMiss, IntegrityError, MalformedOutput,
                            ProviderConfig, ProviderRefusal, ProviderTransient, TruncatedOutput)

SECRET = "sk-test-secret-value"
SETTINGS = {"base": "https://fake.example/openai/v1", "key": SECRET, "header": "api-key",
            "roles": {"writer": "writer-dep", "judge": "judge-dep"}}
MESSAGES = [{"role": "user", "content": "hello"}]


def ok(content='{"answer": 1}', finish="stop", model="writer-dep-2026-01-01"):
    return httpx.Response(200, json={"model": model, "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                                     "choices": [{"finish_reason": finish, "message": {"content": content}}]})


class FakeProvider:
    """Replays a scripted list of responses and records every request."""
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def gateway(tmp_path, provider, **kwargs):
    sleeps = []
    client = httpx.Client(transport=httpx.MockTransport(provider))
    gw = Gateway(tmp_path, SETTINGS, client=client, sleep=sleeps.append, run_id="test", **kwargs)
    return gw, sleeps


def test_second_call_is_served_from_cache(tmp_path):
    provider = FakeProvider(ok())
    gw, _ = gateway(tmp_path, provider)
    first = gw.call_json("writer", MESSAGES, stage="s", input_id="a")
    second = gw.call_json("writer", MESSAGES, stage="s", input_id="a")
    assert first["parsed"] == second["parsed"] == {"answer": 1}
    assert second["cache_hit"] and len(provider.requests) == 1
    assert first["model_version"] == "writer-dep-2026-01-01"


def test_offline_replay_uses_cache_and_misses_loudly(tmp_path):
    gw, _ = gateway(tmp_path, FakeProvider(ok()))
    gw.call_json("writer", MESSAGES, stage="s", input_id="a")
    offline, _ = gateway(tmp_path, FakeProvider(), offline=True)
    assert offline.call_json("writer", MESSAGES, stage="s", input_id="a")["cache_hit"]
    with pytest.raises(CacheMiss):
        offline.call_json("writer", [{"role": "user", "content": "new"}], stage="s", input_id="b")


def test_tampered_cache_entry_is_rejected(tmp_path):
    gw, _ = gateway(tmp_path, FakeProvider(ok()))
    key = gw.call_json("writer", MESSAGES, stage="s", input_id="a")["key"]
    path = tmp_path / "cache" / f"{key}.json"
    entry = read(path)
    entry["request"]["messages"][0]["content"] = "edited"
    write(path, entry)
    with pytest.raises(IntegrityError):
        gw.call_json("writer", MESSAGES, stage="s", input_id="a")


def test_model_version_change_invalidates_cache(tmp_path):
    gw, _ = gateway(tmp_path, FakeProvider(ok()))
    gw.call_json("writer", MESSAGES, stage="s", input_id="a")
    provider = FakeProvider(ok(model="writer-dep-2026-06-01"))
    pinned, _ = gateway(tmp_path, provider, expected_versions={"writer-dep": "writer-dep-2026-06-01"})
    result = pinned.call_json("writer", MESSAGES, stage="s", input_id="a")
    assert not result["cache_hit"] and len(provider.requests) == 1


def test_transient_errors_retry_with_backoff(tmp_path):
    provider = FakeProvider(httpx.Response(429), httpx.Response(503), httpx.ConnectTimeout("slow"), ok())
    gw, sleeps = gateway(tmp_path, provider)
    assert gw.call_json("writer", MESSAGES, stage="s", input_id="a")["parsed"] == {"answer": 1}
    assert sleeps == [2, 4, 8]


def test_retry_after_header_is_honoured_and_capped(tmp_path):
    provider = FakeProvider(httpx.Response(429, headers={"retry-after": "500"}), ok())
    gw, sleeps = gateway(tmp_path, provider)
    gw.call_json("writer", MESSAGES, stage="s", input_id="a")
    assert sleeps == [60]


def test_transient_errors_give_up_after_four_retries(tmp_path):
    gw, sleeps = gateway(tmp_path, FakeProvider(*[httpx.Response(500)] * 5))
    with pytest.raises(ProviderTransient):
        gw.call_json("writer", MESSAGES, stage="s", input_id="a")
    assert sleeps == [2, 4, 8, 16]


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_config_errors_stop_without_retry(tmp_path, status):
    provider = FakeProvider(httpx.Response(status, json={"error": {"code": "x", "message": "bad deployment"}}))
    gw, sleeps = gateway(tmp_path, provider)
    with pytest.raises(ProviderConfig, match="bad deployment"):
        gw.call_json("writer", MESSAGES, stage="s", input_id="a")
    assert sleeps == [] and len(provider.requests) == 1


def test_missing_role_and_missing_key_are_config_errors(tmp_path):
    gw, _ = gateway(tmp_path, FakeProvider())
    with pytest.raises(ProviderConfig):
        gw.call_json("editor", MESSAGES, stage="s", input_id="a")
    keyless = Gateway(tmp_path, {**SETTINGS, "key": None}, run_id="t")
    with pytest.raises(ProviderConfig):
        keyless.call_json("writer", MESSAGES, stage="s", input_id="a")


def test_content_filter_request_and_response_are_refusals(tmp_path):
    blocked = httpx.Response(400, json={"error": {"code": "content_filter", "message": "filtered"}})
    gw, _ = gateway(tmp_path, FakeProvider(blocked, ok(finish="content_filter")))
    with pytest.raises(ProviderRefusal):
        gw.call_json("writer", MESSAGES, stage="s", input_id="a")
    with pytest.raises(ProviderRefusal):
        gw.call_json("writer", MESSAGES, stage="s", input_id="b")


def test_truncated_output_is_not_cached(tmp_path):
    provider = FakeProvider(ok(finish="length"), ok())
    gw, _ = gateway(tmp_path, provider)
    with pytest.raises(TruncatedOutput):
        gw.call_json("writer", MESSAGES, stage="s", input_id="a")
    assert not list(tmp_path.glob("cache/*.json"))
    assert gw.call_json("writer", MESSAGES, stage="s", input_id="a")["parsed"] == {"answer": 1}


def test_empty_content_is_malformed(tmp_path):
    gw, _ = gateway(tmp_path, FakeProvider(ok(content="  ")))
    with pytest.raises(MalformedOutput):
        gw.call_json("writer", MESSAGES, stage="s", input_id="a")


def test_invalid_json_gets_one_repair_turn(tmp_path):
    provider = FakeProvider(ok(content="not json"), ok(content='{"answer": 2}'))
    gw, _ = gateway(tmp_path, provider)
    assert gw.call_json("writer", MESSAGES, stage="s", input_id="a")["parsed"] == {"answer": 2}
    repair_request = json.loads(provider.requests[1].content)
    assert "invalid" in repair_request["messages"][-1]["content"]


def test_validator_failure_after_repair_raises(tmp_path):
    provider = FakeProvider(ok(content='{"answer": 1}'), ok(content='{"answer": 1}'))
    gw, _ = gateway(tmp_path, provider)
    with pytest.raises(MalformedOutput, match="answer must be 2"):
        gw.call_json("writer", MESSAGES, stage="s", input_id="a",
                     validate=lambda o: [] if o["answer"] == 2 else ["answer must be 2"])


def test_budget_blocks_before_any_request(tmp_path):
    provider = FakeProvider(ok())
    prices = {"writer-dep": {"input": 1000.0, "output": 1000.0}}
    gw, _ = gateway(tmp_path, provider, budget_usd=1.0, prices=prices)
    with pytest.raises(BudgetExceeded):
        gw.call_json("writer", MESSAGES, stage="s", input_id="a", max_completion_tokens=2000)
    assert provider.requests == []


def test_budget_without_price_is_a_config_error(tmp_path):
    gw, _ = gateway(tmp_path, FakeProvider(ok()), budget_usd=10.0)
    with pytest.raises(ProviderConfig, match="no price"):
        gw.call_json("writer", MESSAGES, stage="s", input_id="a")


def test_ledger_records_cost_and_never_the_key(tmp_path):
    prices = {"writer-dep": {"input": 2.0, "output": 10.0}}
    gw, _ = gateway(tmp_path, FakeProvider(ok()), prices=prices)
    gw.call_json("writer", MESSAGES, stage="s", input_id="a")
    gw.call_json("writer", MESSAGES, stage="s", input_id="a")
    lines = [json.loads(x) for x in (tmp_path / "runs" / "test.jsonl").read_text().splitlines()]
    assert [x["cache"] for x in lines] == ["miss", "hit"]
    assert lines[0]["cost_usd"] == pytest.approx((100 * 2 + 50 * 10) / 1e6)
    assert gw.spent_usd() == pytest.approx(lines[0]["cost_usd"])
    stored = "".join(p.read_text() for p in tmp_path.rglob("*.json*"))
    assert SECRET not in stored


def test_map_keeps_order_under_concurrency(tmp_path):
    gw, _ = gateway(tmp_path, FakeProvider())
    assert gw.map(lambda x: x * 2, [3, 1, 2], workers=3) == [6, 2, 4]
