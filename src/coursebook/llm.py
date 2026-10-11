"""Single gateway for every model call: cache, retries, typed errors, cost, budget.

    call_json(role, messages)
        |
        +-- cache/<key>.json exists? --yes--> verify key == digest(request) --> return (no network)
        |                                         (mismatch -> IntegrityError)
        |no
        +-- offline? --yes--> CacheMiss
        +-- budget would be exceeded? --yes--> BudgetExceeded (before any request)
        +-- POST /chat/completions
        |     429 / 5xx / timeout  -> backoff 2,4,8,16 s (or Retry-After), then ProviderTransient
        |     400 content_filter   -> ProviderRefusal
        |     other 4xx            -> ProviderConfig (no retry)
        +-- finish_reason length   -> TruncatedOutput (caller splits its input)
        +-- refusal / content_filter finish -> ProviderRefusal
        +-- not JSON or validator error -> one repair turn, then MalformedOutput
        +-- write cache entry + ledger line (never headers or keys)

The cache key is the request body (deployment, messages, parameters), so a changed
prompt template or input is a miss. Entries record the model version the API
reported; `expected_versions` turns a version change into a miss.
"""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from .core import digest, read, write

RETRY_DELAYS = (2, 4, 8, 16)
MAX_RETRY_AFTER = 60


class LLMError(Exception):
    """Base class; every subclass names a distinct way a call can fail."""


class ProviderTransient(LLMError):
    """Rate limit, server error or timeout that survived all retries."""


class ProviderConfig(LLMError):
    """Bad key, endpoint, deployment or request; retrying cannot help."""


class ProviderRefusal(LLMError):
    """Content filter or explicit model refusal."""


class TruncatedOutput(LLMError):
    """finish_reason=length; the caller must split its input."""


class MalformedOutput(LLMError):
    """Empty, non-JSON or schema-invalid output after one repair attempt."""


class BudgetExceeded(LLMError):
    """The next call would push spend past the configured ceiling."""


class CacheMiss(LLMError):
    """Offline replay needed a response that is not in the cache."""


class IntegrityError(LLMError):
    """A cache entry does not match the request it claims to answer."""


def settings_from_env():
    """Read endpoint, key and role deployments from the environment (.env)."""
    from dotenv import load_dotenv
    load_dotenv(".env", override=False)
    base = os.environ.get("AZURE_OPENAI_BASE_URL") or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1/")
    key = os.environ.get("AZURE_AI_FOUNDRY_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not base.startswith("https://"):
        raise ProviderConfig("Model endpoint must use HTTPS")
    header = "api-key" if os.environ.get("AZURE_OPENAI_BASE_URL") else "Authorization"
    roles = {"writer": os.environ.get("COURSEBOOK_MODEL"),
             "judge": os.environ.get("COURSEBOOK_JUDGE_MODEL") or os.environ.get("COURSEBOOK_MODEL")}
    return {"base": base.rstrip("/"), "key": key, "header": header, "roles": roles}


class Gateway:
    def __init__(self, root, settings=None, *, budget_usd=None, prices=None, offline=False,
                 expected_versions=None, run_id=None, client=None, sleep=time.sleep):
        self.root = Path(root)
        self.settings = settings or {"base": "", "key": None, "header": "api-key", "roles": {}}
        self.budget_usd = budget_usd
        self.prices = prices or {}
        self.offline = offline
        self.expected_versions = expected_versions or {}
        self.run_id = run_id or time.strftime("%Y%m%dT%H%M%S")
        self.client = client
        self.sleep = sleep
        self._lock = threading.Lock()

    # ---- paths and bookkeeping -------------------------------------------------
    def _cache_path(self, key):
        return self.root / "cache" / f"{key}.json"

    def _ledger_path(self):
        return self.root / "runs" / f"{self.run_id}.jsonl"

    def spent_usd(self):
        """Total recorded spend across every run ledger (cache hits cost nothing)."""
        total = 0.0
        for path in (self.root / "runs").glob("*.jsonl"):
            for line in path.read_text().splitlines():
                cost = json.loads(line).get("cost_usd")
                total += cost or 0.0
        return total

    def _log(self, **fields):
        fields = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **fields}
        path = self._ledger_path()
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as handle:
                handle.write(json.dumps(fields, ensure_ascii=False) + "\n")

    def _cost(self, deployment, usage):
        price = self.prices.get(deployment)
        if not price or not usage:
            return None
        return (usage.get("prompt_tokens", 0) * price["input"]
                + usage.get("completion_tokens", 0) * price["output"]) / 1_000_000

    def _check_budget(self, deployment, request):
        if self.budget_usd is None:
            return
        price = self.prices.get(deployment)
        if not price:
            raise ProviderConfig(f"budget_usd is set but no price is configured for '{deployment}'")
        # Rough upper bound: ~4 characters per input token plus the full output allowance.
        estimate = (len(json.dumps(request["messages"])) / 4 * price["input"]
                    + request.get("max_completion_tokens", 0) * price["output"]) / 1_000_000
        spent = self.spent_usd()
        if spent + estimate > self.budget_usd:
            raise BudgetExceeded(f"spent ${spent:.2f} + next call ~${estimate:.2f} exceeds budget ${self.budget_usd:.2f}")

    # ---- one raw request -------------------------------------------------------
    def _post(self, request):
        if not self.settings.get("key"):
            raise ProviderConfig("No API key; fill in .env (see .env.example)")
        value = self.settings["key"] if self.settings["header"] == "api-key" else f"Bearer {self.settings['key']}"
        client = self.client or httpx.Client(timeout=300)
        url = self.settings["base"] + "/chat/completions"
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                response = client.post(url, headers={self.settings["header"]: value}, json=request)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                reason = f"{type(exc).__name__}"
                retry_after = None
            else:
                if response.status_code == 200:
                    return response.json(), attempt
                body = _safe_json(response)
                code = (body.get("error") or {}).get("code") if isinstance(body.get("error"), dict) else None
                if response.status_code == 400 and code == "content_filter":
                    raise ProviderRefusal("Request blocked by the provider content filter")
                if response.status_code != 429 and response.status_code < 500:
                    message = (body.get("error") or {}).get("message", "") if isinstance(body.get("error"), dict) else ""
                    raise ProviderConfig(f"HTTP {response.status_code} for deployment "
                                         f"'{request['model']}': {message[:200]}")
                reason = f"HTTP {response.status_code}"
                retry_after = response.headers.get("retry-after")
            if attempt == len(RETRY_DELAYS):
                raise ProviderTransient(f"{reason} after {attempt + 1} attempts")
            delay = RETRY_DELAYS[attempt]
            if retry_after and retry_after.isdigit():
                delay = min(int(retry_after), MAX_RETRY_AFTER)
            self.sleep(delay)

    # ---- public API ------------------------------------------------------------
    def complete(self, role, messages, *, stage, input_id, json_mode=True,
                 max_completion_tokens=16000, extra=None):
        """Return {content, model_version, usage, cache_hit} for one chat request."""
        deployment = self.settings["roles"].get(role)
        if not deployment:
            raise ProviderConfig(f"No deployment configured for role '{role}'")
        request = {"model": deployment, "messages": messages,
                   "max_completion_tokens": max_completion_tokens, **(extra or {})}
        if json_mode:
            request["response_format"] = {"type": "json_object"}
        key = digest(request)
        path = self._cache_path(key)
        started = time.monotonic()
        if path.exists():
            entry = read(path)
            if entry.get("key") != key or digest(entry.get("request")) != key:
                raise IntegrityError(f"Cache entry {path.name} does not match its request")
            expected = self.expected_versions.get(deployment)
            if not expected or entry["model_version"] == expected:
                self._log(stage=stage, input_id=input_id, role=role, deployment=deployment,
                          model_version=entry["model_version"], cache="hit", tokens=0,
                          cost_usd=0.0, duration_s=0.0, outcome="ok")
                return {"content": entry["content"], "model_version": entry["model_version"],
                        "usage": entry["usage"], "cache_hit": True, "key": key}
        if self.offline:
            raise CacheMiss(f"{stage}/{input_id}: no cached response (key {key[:12]})")
        self._check_budget(deployment, request)
        try:
            body, attempt = self._post(request)
            outcome = _classify(body)
        except LLMError as exc:
            self._log(stage=stage, input_id=input_id, role=role, deployment=deployment,
                      cache="miss", outcome=type(exc).__name__, detail=str(exc)[:200],
                      duration_s=round(time.monotonic() - started, 2))
            raise
        usage = body.get("usage") or {}
        cost = self._cost(deployment, usage)
        self._log(stage=stage, input_id=input_id, role=role, deployment=deployment,
                  model_version=body.get("model"), cache="miss", attempts=attempt + 1,
                  tokens=usage.get("total_tokens"), cost_usd=cost,
                  duration_s=round(time.monotonic() - started, 2), outcome=outcome)
        if outcome != "ok":
            raise {"TruncatedOutput": TruncatedOutput, "ProviderRefusal": ProviderRefusal,
                   "MalformedOutput": MalformedOutput}[outcome](f"{stage}/{input_id}: {outcome}")
        content = body["choices"][0]["message"]["content"]
        write(path, {"key": key, "request": request, "content": content,
                     "model_version": body.get("model"), "usage": usage})
        return {"content": content, "model_version": body.get("model"), "usage": usage,
                "cache_hit": False, "key": key}

    def call_json(self, role, messages, *, stage, input_id, validate=None, **kwargs):
        """complete() + JSON parsing + optional validator, with one repair turn.

        `validate(obj)` returns a list of error strings (empty when valid)."""
        result = self.complete(role, messages, stage=stage, input_id=input_id, **kwargs)
        errors, parsed = _parse(result["content"], validate)
        if not errors:
            return {**result, "parsed": parsed}
        repair = messages + [
            {"role": "assistant", "content": result["content"]},
            {"role": "user", "content": "Your previous output was invalid: " + "; ".join(errors)[:2000]
             + ". Return the corrected JSON object only."}]
        result = self.complete(role, repair, stage=stage, input_id=input_id + ":repair", **kwargs)
        errors, parsed = _parse(result["content"], validate)
        if errors:
            raise MalformedOutput(f"{stage}/{input_id}: still invalid after repair: " + "; ".join(errors)[:300])
        return {**result, "parsed": parsed}

    def map(self, function, items, workers=4):
        """Run `function(item)` with bounded concurrency; results keep input order."""
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            return list(pool.map(function, items))


def gateway_from_config(root, config, *, offline=False, client=None, sleep=time.sleep):
    llm = config.get("llm", {})
    return Gateway(root, settings_from_env(), budget_usd=llm.get("budget_usd"),
                   prices=llm.get("prices_usd_per_1m"), offline=offline,
                   expected_versions=llm.get("expected_versions"), client=client, sleep=sleep)


def _safe_json(response):
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _classify(body):
    choices = body.get("choices") or []
    if not choices:
        return "MalformedOutput"
    choice = choices[0]
    message = choice.get("message") or {}
    if choice.get("finish_reason") == "content_filter" or message.get("refusal"):
        return "ProviderRefusal"
    if choice.get("finish_reason") == "length":
        return "TruncatedOutput"
    if not (message.get("content") or "").strip():
        return "MalformedOutput"
    return "ok"


def _parse(content, validate):
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        return [f"not valid JSON ({exc.msg} at char {exc.pos})"], None
    if not isinstance(parsed, dict):
        return ["top-level value must be a JSON object"], None
    return (validate(parsed) if validate else []), parsed
