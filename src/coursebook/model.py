"""Explicit OpenAI-compatible HTTP adapter; Azure v1 accepts api-key auth."""
import os
import re
from pathlib import Path
import httpx
from .core import digest, read, write, validate_chapter


def generate(root, config, video_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", video_id):
        raise ValueError("Invalid video identifier")
    from dotenv import load_dotenv
    load_dotenv(override=False)
    base = os.environ.get("AZURE_OPENAI_BASE_URL") or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1/")
    key = os.environ.get("AZURE_AI_FOUNDRY_API_KEY") or os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("COURSEBOOK_MODEL")
    if not key or not model:
        raise ValueError("Set model deployment and credentials in local .env; see .env.example")
    if not base.startswith("https://"):
        raise ValueError("Model endpoint must use HTTPS")
    root = Path(root)
    packet = read(root / "evidence" / f"{video_id}.json")
    prompt = Path("prompts/writer.txt").read_text()
    # Fail explicitly instead of silently truncating a long lecture.
    if len(str(packet["items"])) > config["chunk_characters"]:
        raise ValueError("Lecture exceeds pilot context budget; increase config chunk_characters after checking model limits")
    user = {"reader": config["reader"], "evidence": packet["items"]}
    request = {"model": model, "messages": [{"role": "system", "content": prompt},
               {"role": "user", "content": __import__("json").dumps(user)}],
               "response_format": {"type": "json_object"}}
    headers = {"api-key": key} if os.environ.get("AZURE_OPENAI_BASE_URL") else {"Authorization": f"Bearer {key}"}
    response = httpx.post(base.rstrip("/") + "/chat/completions", headers=headers, json=request, timeout=180)
    if response.status_code != 200:
        raise ValueError(f"Model request failed (HTTP {response.status_code}); check endpoint, deployment and credentials")
    body = response.json()
    chapter = __import__("json").loads(body["choices"][0]["message"]["content"])
    errors = validate_chapter(chapter, packet["items"])
    run = {"request": request, "response": body, "source_hash": packet["source_hash"], "prompt_hash": digest(prompt), "errors": errors}
    write(root / "runs" / f"{digest(run)}.json", run)
    if errors:
        raise ValueError("Generated chapter failed structural validation; inspect saved run")
    write(root / "chapters" / f"{video_id}.json", {"source_hash": packet["source_hash"], "chapter": chapter})
    return chapter
