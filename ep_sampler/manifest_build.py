#!/usr/bin/env python3
"""Scan a sample library and auto-build a manifest from it.

Workflow:

1. `scan_library` walks a directory, classifies each audio file (via DeepSeek
   when available, otherwise a filename heuristic), and returns flat records.
2. The records are cached in a flat JSON file (no database) so a build can be
   re-run without rescanning.
3. `build_manifest` turns the records into a manifest: a *guide* (one of 8
   styles, like the Ting FX types) weights which categories to include, a
   random seed chooses *which* samples, and the result is always sensibly
   ordered - drums first (kicks before snares before hats ...), then bass,
   then chords/melody, then vocals/fx.
"""

import json
import random
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .ai import classify_filenames
from .factory import AUDIO_EXTS

# Sensible category order: drums, then bass, then harmony/melody, then voice/fx.
CATEGORIES = ("kick", "snare", "clap", "hat", "perc", "tom",
              "bass", "chord", "melody", "vocal", "fx")

# Category -> pad group (EP-133 has 4 groups of 12 pads).
GROUP_OF = {
    "kick": "A", "snare": "A", "clap": "A", "hat": "A", "perc": "A", "tom": "A",
    "bass": "B",
    "chord": "C", "melody": "C",
    "vocal": "D", "fx": "D",
}

# Sample-library slot ranges for each group (mirrors the factory grouping).
GROUP_BASE_SLOT = {"A": 1, "B": 100, "C": 200, "D": 300}

# Melodic samples are played chromatically; everything else is a one-shot.
PLAYMODE_OF = {"bass": "key", "chord": "key", "melody": "key"}

# --------------------------------------------------------------------------
# 16 manifest guides - genre-based full kits, each biasing the build.
# Every guide is a full kit: drums + bass + melodic + fx/vocals, just weighted
# toward its genre (nobody wants a Riddim with only drums).
# --------------------------------------------------------------------------

GUIDES = [
    {"key": "house", "name": "HOUSE",
     "essence": "four-on-the-floor - kick, clap, hats, bass, chords",
     "weights": {"kick": 4, "clap": 3, "hat": 3, "perc": 1, "bass": 3,
                 "chord": 2, "melody": 2, "fx": 1}, "shuffle": False},
    {"key": "techno", "name": "TECHNO",
     "essence": "driving - kicks, hats, percussion, bass",
     "weights": {"kick": 4, "hat": 3, "clap": 2, "perc": 2, "tom": 1,
                 "bass": 2, "melody": 1, "fx": 1}, "shuffle": False},
    {"key": "dub", "name": "DUB",
     "essence": "sound-system - heavy bass, fx, percussion",
     "weights": {"kick": 3, "hat": 1, "perc": 2, "tom": 1, "bass": 4,
                 "chord": 1, "melody": 1, "fx": 2, "vocal": 1},
     "shuffle": False},
    {"key": "hiphop", "name": "HIP-HOP",
     "essence": "boom-bap - kick, snare, hats, bass, melodic",
     "weights": {"kick": 3, "snare": 3, "hat": 2, "clap": 1, "perc": 1,
                 "bass": 3, "chord": 2, "melody": 1, "vocal": 1},
     "shuffle": False},
    {"key": "hyperpop", "name": "HYPERPOP",
     "essence": "glitchy, pitched-up pop - bright synths, fx and vocals",
     "weights": {"kick": 3, "snare": 2, "clap": 2, "hat": 3, "perc": 1,
                 "bass": 2, "chord": 2, "melody": 2, "fx": 3, "vocal": 3},
     "shuffle": False},
    {"key": "dnb", "name": "D&B",
     "essence": "breaks - kick, snares, hats, bass, fx",
     "weights": {"kick": 3, "snare": 3, "hat": 2, "perc": 1, "tom": 1,
                 "bass": 3, "melody": 1, "fx": 2}, "shuffle": False},
    {"key": "lofi", "name": "LO-FI",
     "essence": "mellow - soft drums, chords and melody",
     "weights": {"kick": 2, "snare": 2, "hat": 2, "perc": 1, "bass": 2,
                 "chord": 3, "melody": 3, "vocal": 1, "fx": 1},
     "shuffle": False},
    {"key": "ambient", "name": "AMBIENT",
     "essence": "textural - pads, melody, bass, light percussion",
     "weights": {"hat": 1, "perc": 1, "bass": 2, "chord": 3, "melody": 4,
                 "vocal": 1, "fx": 3}, "shuffle": False},
    {"key": "reggae", "name": "REGGAE",
     "essence": "one-drop - skank chords, bass, percussion",
     "weights": {"kick": 3, "hat": 2, "perc": 2, "tom": 1, "bass": 3,
                 "chord": 2, "melody": 1, "vocal": 2}, "shuffle": False},
    {"key": "funk", "name": "FUNK",
     "essence": "groove - kick, snare, clap, bass, melody",
     "weights": {"kick": 3, "snare": 2, "clap": 2, "hat": 2, "bass": 3,
                 "chord": 1, "melody": 2, "vocal": 1}, "shuffle": False},
    {"key": "soul", "name": "SOUL",
     "essence": "warm - soft drums, chords, melody, vocals",
     "weights": {"kick": 2, "snare": 2, "hat": 2, "clap": 1, "bass": 3,
                 "chord": 3, "melody": 2, "vocal": 2}, "shuffle": False},
    {"key": "garage", "name": "UK GARAGE",
     "essence": "2-step - swung hats, bass, chords",
     "weights": {"kick": 3, "snare": 2, "hat": 3, "perc": 1, "bass": 3,
                 "chord": 2, "vocal": 1, "fx": 1}, "shuffle": False},
    {"key": "jungle", "name": "JUNGLE",
     "essence": "amen - kick, snares, hats, bass, fx",
     "weights": {"kick": 3, "snare": 3, "hat": 2, "perc": 1, "tom": 1,
                 "bass": 3, "melody": 1, "fx": 2}, "shuffle": False},
    {"key": "breaks", "name": "BREAKS",
     "essence": "breakbeat - kick, snares, hats, bass, melody",
     "weights": {"kick": 3, "snare": 3, "hat": 2, "perc": 1, "bass": 2,
                 "chord": 1, "melody": 2, "fx": 1}, "shuffle": False},
    {"key": "synthwave", "name": "SYNTHWAVE",
     "essence": "retro - synth bass, pads, arps, drums",
     "weights": {"kick": 3, "snare": 2, "hat": 2, "bass": 3, "chord": 3,
                 "melody": 3, "fx": 1}, "shuffle": False},
    {"key": "chaos", "name": "CHAOS",
     "essence": "everything, randomly picked but still grouped",
     "weights": {c: 1.0 for c in CATEGORIES}, "shuffle": True},
]

# Keyword heuristics used when there is no DeepSeek API key.
_KEYWORDS = [
    ("kick", ("kick", "kik", "bd", "boom")),
    ("snare", ("snare", "snr", "sd")),
    ("clap", ("clap", "clp")),
    ("hat", ("hat", "hh", "oh", "ride", "cym", "crash")),
    ("perc", ("perc", "rim", "shk", "shake", "cow", "tamb", "bongo", "cong",
              "marac", "clav", "guiro")),
    ("tom", ("tom",)),
    ("bass", ("bass", "sub", "808")),
    ("chord", ("chord", "chrd", "stab")),
    ("melody", ("lead", "mel", "synth", "pad", "pluck", "key", "arp", "piano",
                "guitar", "flute", "horn", "string", "organ")),
    ("vocal", ("vox", "voc", "voice", "chant", "sing", "acap")),
]


@dataclass
class SampleRec:
    file: str
    name: str
    category: str
    bpm: float | None = None


def humanize_stem(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"[-_]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem[:20] or "sample"


def heuristic_classify(filename: str) -> dict:
    low = filename.lower()
    for cat, words in _KEYWORDS:
        for w in words:
            if w in low:
                return {"category": cat, "name": "", "bpm": None}
    return {"category": "fx", "name": "", "bpm": None}


def scan_library(directory: Path, use_ai: bool, api_key: str = "",
                 model: str = "", base_url: str = "",
                 known: dict[str, SampleRec] | None = None) -> list[SampleRec]:
    """Walk `directory` and classify every audio file found.

    `known` maps relative file paths to already-classified records; those are
    reused as-is, so only new files are classified (saves API calls on
    re-scans). Files in `known` that no longer exist are dropped.
    """
    directory = directory.expanduser()
    files: list[Path] = []
    if directory.is_dir():
        for ext in AUDIO_EXTS:
            batch: list[Path] = []
            for p in directory.rglob(f"*{ext}"):
                batch.append(p)
                n = len(files) + len(batch)
                if n % 5000 == 0:
                    print(f"  ... {n} sounds found")
            files.extend(sorted(batch))

    if not files:
        print("  nothing to listen to here")
        return []

    rel_of = {f: str(f.relative_to(directory)) for f in files}
    known = known or {}

    new_files = [f for f in files if rel_of[f] not in known]
    print(f"  found {len(files)} sounds ({len(new_files)} new)")

    ai_map: dict[str, dict] = {}
    if new_files:
        if use_ai:
            print("  asking deepseek to identify the new sounds ...")

            def _progress(done: int, total: int) -> None:
                if done < total:
                    print(f"  ... identified {done}/{total} sounds")

            ai_map = classify_filenames([rel_of[f] for f in new_files], api_key,
                                        model=model or "deepseek-chat",
                                        base_url=base_url or "https://api.deepseek.com",
                                        on_progress=_progress)
            if ai_map:
                print(f"  deepseek named {len(ai_map)}/{len(new_files)} sounds")
        else:
            print("  identifying new sounds from their names ...")
    else:
        print("  nothing new - reusing the cached index")

    recs: list[SampleRec] = []
    for f in files:
        rel = rel_of[f]
        if rel in known:
            recs.append(known[rel])
        else:
            info = ai_map.get(rel) or heuristic_classify(rel)
            name = info.get("name") or humanize_stem(f)
            recs.append(SampleRec(file=rel, name=name,
                                  category=info["category"], bpm=info.get("bpm")))
    return recs


def save_index(path: Path, directory: Path, samples: list[SampleRec]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "dir": str(directory),
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "count": len(samples),
        "samples": [asdict(s) for s in samples],
    }
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def load_index(path: Path) -> list[SampleRec] | None:
    path = path.expanduser()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [SampleRec(**s) for s in data.get("samples", [])]
    except (json.JSONDecodeError, TypeError):
        return None


def _guide_by_key(key: str) -> dict:
    for g in GUIDES:
        if g["key"] == key:
            return g
    raise ValueError(f"unknown guide {key!r}")


def _apportion(weights: dict[str, float], capacity: int) -> dict[str, int]:
    """Largest-remainder apportionment of `capacity` across weighted keys."""
    total = sum(weights.values())
    if total <= 0 or capacity <= 0:
        return {k: 0 for k in weights}
    quota = {k: capacity * w / total for k, w in weights.items()}
    counts = {k: int(q) for k, q in quota.items()}
    remainder = capacity - sum(counts.values())
    for k in sorted(weights, key=lambda k: quota[k] - counts[k], reverse=True):
        if remainder <= 0:
            break
        counts[k] += 1
        remainder -= 1
    return counts


def build_manifest(samples: list[SampleRec], guide_key: str,
                   seed: int | None = None, max_total: int = 48,
                   shuffle: bool | None = None) -> list[dict]:
    """Return manifest rows (one per pad), sensibly ordered.

    A guide weights which categories to include, `seed` randomises which
    concrete samples are picked, and rows are ordered by category then name.
    `shuffle` overrides the guide's own shuffle flag (used to force a
    different sample selection per programme).
    """
    guide = _guide_by_key(guide_key)
    rng = random.Random(seed)
    do_shuffle = guide["shuffle"] if shuffle is None else shuffle
    max_total = min(max_total, 48)  # 4 groups x 12 pads

    by_cat: dict[str, list[SampleRec]] = {}
    for s in samples:
        by_cat.setdefault(s.category, []).append(s)

    # Fill every populated group up to 12 pads (the hardware limit), splitting
    # each group across its categories by the guide's weights. If max_total is
    # lower than a full 48-pad kit, trim pads from the least-weighted groups.
    weights = guide["weights"]
    group_cats: dict[str, dict[str, float]] = {}
    for g in "ABCD":
        cats = {c: weights[c] for c in CATEGORIES
                if weights.get(c, 0) > 0 and GROUP_OF[c] == g}
        if cats:
            group_cats[g] = cats

    n_groups = len(group_cats)
    target = min(max_total, n_groups * 12)
    group_cap: dict[str, int] = {g: 12 for g in group_cats}
    surplus = n_groups * 12 - target
    if surplus > 0:
        for g in sorted(group_cats,
                        key=lambda g: sum(group_cats[g].values())):
            if surplus <= 0:
                break
            remove = min(12, surplus)
            group_cap[g] -= remove
            surplus -= remove

    picks: dict[str, int] = {}
    for g, cap in group_cap.items():
        if cap <= 0:
            continue
        for c, n in _apportion(group_cats[g], cap).items():
            picks[c] = n

    # Choose which samples, grouped and ordered.
    chosen: dict[str, list[SampleRec]] = {}
    for c, n in picks.items():
        pool = sorted(by_cat.get(c, []), key=lambda s: s.name.lower())
        if not pool:
            continue
        if do_shuffle:
            rng.shuffle(pool)
        chosen[c] = pool[:n]

    # Emit rows: group -> (category order, then name) -> pad/slot.
    rows: list[dict] = []
    pad_of = {"A": 0, "B": 0, "C": 0, "D": 0}
    for c in CATEGORIES:
        for s in chosen.get(c, []):
            g = GROUP_OF[c]
            pad_of[g] += 1
            if pad_of[g] > 12:
                continue
            pad = pad_of[g]
            slot = GROUP_BASE_SLOT[g] + pad - 1
            bpm = s.bpm if s.bpm else ""
            rows.append({
                "slot": slot, "group": g, "pad": pad,
                "bpm": bpm,
                "time_mode": "bpm" if bpm else "off",
                "playmode": PLAYMODE_OF.get(c, "oneshot"),
                "name": s.name, "file": s.file, "category": c,
            })
    return rows


def build_kits(samples: list[SampleRec], guide_key: str,
               seed: int | None = None, count: int = 8,
               max_total: int = 48) -> list[list[dict]]:
    """Generate `count` kits (one manifest's worth each) with sequential
    seeds. When generating more than one, sample selection is shuffled so
    each programme gets a different random set of samples."""
    force_shuffle = count > 1
    kits: list[list[dict]] = []
    for i in range(count):
        s = (seed + i) if seed is not None else None
        kits.append(build_manifest(samples, guide_key, seed=s,
                                   max_total=max_total,
                                   shuffle=True if force_shuffle else None))
    return kits
