"""Run the stages for a set of lectures. Each stage is skipped when its inputs are unchanged.

    segment -> extract -> reader (reader.md) -> outline -> frame (intro, openers, at a glance)
      -> write -> verify -> takeaways -> diagrams -> plants -> (evaluate, render)
"""
from pathlib import Path
from .core import read
from .stages.segment import run_segment
from .stages.extract import run_extract
from .stages.outline import run_outline
from .stages.write import run_write
from .stages.verify import run_verify
from .stages.plants import run_plants
from .stages.frame import run_frame, run_takeaways
from .stages.diagrams import run_diagrams
from .stages.reader import run_reader, reader_for_prompts
from .stages.listings import run_listings
from .stages.crosscheck import run_crosscheck

STAGES = ["segment", "extract", "reader", "outline", "frame", "write", "verify", "takeaways", "diagrams", "plants",
          "listings", "crosscheck"]


def select_entries(root, config, lectures=None):
    """Playlist entries to build: the given playlist positions (or config 'lectures'),
    restricted to lectures whose captions were captured."""
    manifest = read(Path(root) / "manifest.json")
    wanted = lectures or config.get("lectures")
    captured = {p.stem for p in (Path(root) / "evidence").glob("*.json")}
    entries = [e for e in manifest["entries"] if e["video_id"] in captured
               and (not wanted or e["playlist_index"] in wanted)]
    if not entries:
        raise ValueError("No captured lectures match the selection; run capture first")
    return entries


def run(root, config, gateway, lectures=None, until="plants", only=None, log=print):
    entries = select_entries(root, config, lectures)
    workers = config.get("llm", {}).get("concurrency", 4)
    stop = STAGES.index(until)
    log(f"lectures: {', '.join(str(e['playlist_index']) for e in entries)}")
    for entry in entries:
        run_segment(root, entry["video_id"])
    if stop >= 1:
        for entry in entries:
            points = run_extract(root, gateway, entry, workers)["points"]
            log(f"extract L{entry['playlist_index']:02d}: {len(points)} points")
    if stop < 2:
        return None
    reader = run_reader(root, gateway, config, entries)
    log(f"reader: {reader['contract']['reader_profile']['value'][:80]}")
    # With reader_profile.enabled, every writing prompt gets reader.md instead of the one-line brief.
    config = {**config, "reader": reader_for_prompts(root, config)}
    if stop < 3:
        return None
    outline = run_outline(root, gateway, config, entries)
    log(f"outline: {len(outline['chapters'])} chapters, "
        f"{sum(len(c['sections']) for c in outline['chapters'])} sections, {len(outline['dropped'])} points dropped")
    if stop >= 4 and not only:
        framed = run_frame(root, gateway, config, outline, workers)
        log(f"frame: intro + {len(framed) - 1} chapter openers, {sum(len(f['queue']) for f in framed)} queued")
    if stop >= 5:
        written = run_write(root, gateway, config, outline, only, workers)
        log(f"write: {len(written)} sections")
    if stop >= 6:
        verified = run_verify(root, gateway, config, outline, only, workers)
        log(f"verify: {sum(len(v['queue']) for v in verified)} sentences in the review queue")
    if stop >= 7 and not only:
        takeaways = run_takeaways(root, gateway, config, outline, workers)
        log(f"takeaways: {sum(len(t['paragraphs']) for t in takeaways)} items, {sum(len(t['queue']) for t in takeaways)} queued")
    if stop >= 8 and not only:
        diagrams = run_diagrams(root, gateway, config, outline, workers)
        log(f"diagrams: {sum(len(d['diagrams']) for d in diagrams)} kept, {sum(len(d['dropped']) for d in diagrams)} dropped")
    if stop >= 9 and not only:
        planted = run_plants(root, gateway, config, outline, workers)
        log(f"plants: caught {sum(p['caught'] for p in planted)} / {sum(p['planted'] for p in planted)}")
    if stop >= 10 and not only:
        listings = run_listings(root, gateway, config, outline, workers)
        log(f"listings: {sum(len(l['listings']) for l in listings)} kept, {sum(len(l['rejected']) for l in listings)} rejected")
    if stop >= 11 and not only:
        checked = run_crosscheck(root, gateway, config, outline, workers)
        log(f"crosscheck: {sum(c['checked'] for c in checked)} sentences compared, {sum(len(c['conflicts']) for c in checked)} conflicts")
    return outline
