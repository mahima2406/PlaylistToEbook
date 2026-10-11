"""Pilot drafting through the gateway. Stages 3-5 replace this per-video draft."""
import json
import re
from pathlib import Path
from .core import digest, read, write, validate_chapter
from .llm import gateway_from_config


def generate(root, config, video_id, gateway=None):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", video_id):
        raise ValueError("Invalid video identifier")
    root = Path(root)
    packet = read(root / "evidence" / f"{video_id}.json")
    prompt = Path("prompts/writer.txt").read_text()
    # Fail explicitly instead of silently truncating a long lecture.
    if len(str(packet["items"])) > config["chunk_characters"]:
        raise ValueError("Lecture exceeds pilot context budget; increase config chunk_characters after checking model limits")
    gateway = gateway or gateway_from_config(root, config)
    user = {"reader": config["reader"], "evidence": packet["items"]}
    messages = [{"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(user)}]
    result = gateway.call_json("writer", messages, stage="draft", input_id=video_id,
                               validate=lambda chapter: validate_chapter(chapter, packet["items"]))
    chapter = result["parsed"]
    write(root / "chapters" / f"{video_id}.json",
          {"source_hash": packet["source_hash"], "prompt_hash": digest(prompt),
           "model_version": result["model_version"], "cache_key": result["key"], "chapter": chapter})
    return chapter
