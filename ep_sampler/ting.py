#!/usr/bin/env python3
"""EP-2350 Ting (FX microphone) config.json builder and FX "types".

The Ting is a standalone handheld FX mic. It mounts a tiny writable disk and
reads a single `config.json` that defines the four FX buttons as effect chains
plus optional handle / shake / lfo / trigger modulation.

Format (from the official EP-2350 user guide):

    {
      "name": "PACK NAME",
      "samples": [ {"pos": 0, "file": "1.wav", "playmode": "oneshot"}, ... ],
      "presets": [
        { "pos": 0, "name": "...", "list": [ {"effect": "DELAY", "time": 0.5} ],
          "handle": {"row": 0, "param": "time", "depth": 0.5},
          "shake":  {"row": 1, "param": "mix", "depth": 1.0},
          "lfo":    {"row": 0, "param": "time", "depth": 0.1, "shape": "sine",
                     "speed": 4.0, "phase": 0},
          "trigger": {"row": 2} }
      ]
    }

Beyond the four factory presets, this module defines 8 named FX "types" - each
captures the *essence* of a classic Teenage Engineering instant FX (dub echo,
spring, pitch-up, ring-mod, drive, wobble, radio, glitch) as a fixed effect
chain, then randomises every parameter inside that type's own ranges. That
keeps the character while making every pack different.
"""

import json
import random
from pathlib import Path

# effect name -> {parameter: (min, max)}. Ranges from the official guide §7.7.
EFFECTS = {
    "BALANCE": {"balance": (0.0, 1.0)},
    "DELAY": {
        "time": (0.0, 1.1),
        "lowpass-cutoff": (0.0, 1.0),
        "highpass-cutoff": (0.0, 1.0),
        "wet-level": (0.0, 1.0),
        "dry-level": (0.0, 1.0),
        "echo": (0.0, 1.0),
        "cross-feed": (0.0, 1.0),
        "balance": (0.0, 1.0),
    },
    "DIST": {
        "amount": (0.0, 40.0),
        "lowpass-cutoff": (0.0, 1.0),
        "highpass-cutoff": (0.0, 1.0),
        "mix": (0.0, 1.0),
    },
    "HARMONY": {
        "dry-level": (0.0, 1.0),
        "pitch": (0.5, 2.0),
    },
    "LOWPASS": {"cutoff": (0.0, 1.0)},
    "HIGHPASS": {"cutoff": (0.0, 1.0)},
    "SAMPLE": {
        "speed": (0.0, 4.0),
        "pitch": (-24.0, 24.0),
        "level": (0.0, 1.0),
        "balance": (0.0, 1.0),
    },
    "REVERB": {
        "dry-level": (0.0, 1.0),
        "wet-level": (0.0, 1.0),
        "time": (0.0, 1.0),
        "spring-mix": (0.0, 1.0),
        "highpass-cutoff": (0.0, 1.0),
    },
    "RING": {"frequency": (0.0, 20000.0), "mix": (0.0, 1.0)},
    "SSB": {"frequency": (-20000.0, 20000.0)},
}

LFO_SHAPES = ("sine", "square", "sawtooth", "random")
PLAYMODES = ("oneshot", "hold", "startstop")

# --------------------------------------------------------------------------
# 8 FX "types" - essence + recipe
# --------------------------------------------------------------------------
# A recipe is a fixed chain structure plus fixed modulation wiring; parameter
# ranges define the character, and values are random within them.

FX_TYPES = [
    {
        "name": "ECHO",
        "essence": "dub tape echo - repeats, feedback, space",
        "chain": [
            ("DELAY", {"time": (0.25, 0.7), "echo": (0.35, 0.8),
                       "wet-level": (0.35, 0.9), "dry-level": (0.2, 0.6)}),
        ],
        "mods": [
            {"src": "handle", "effect": "DELAY", "param": "time",
             "depth": (0.2, 0.6)},
            {"src": "lfo", "effect": "DELAY", "param": "echo",
             "shape": "sine", "speed": (0.5, 3.0), "depth": (0.05, 0.3)},
        ],
    },
    {
        "name": "SPRING",
        "essence": "spring reverb - boingy metallic space",
        "chain": [
            ("DELAY", {"time": (0.12, 0.3), "echo": (0.2, 0.4),
                       "wet-level": (0.25, 0.55)}),
            ("REVERB", {"time": (0.4, 0.8), "spring-mix": (0.6, 1.0),
                        "wet-level": (0.5, 0.9), "dry-level": (0.2, 0.5)}),
        ],
        "mods": [
            {"src": "handle", "effect": "REVERB", "param": "time",
             "depth": (0.2, 0.5)},
        ],
    },
    {
        "name": "PIXIE",
        "essence": "pitch-up harmony - chipmunk pixie voice",
        "chain": [
            ("HARMONY", {"pitch": (1.3, 2.0), "dry-level": (0.3, 0.7)}),
            ("REVERB", {"time": (0.15, 0.4), "wet-level": (0.2, 0.5)}),
        ],
        "mods": [
            {"src": "handle", "effect": "HARMONY", "param": "pitch",
             "depth": (-0.2, 0.2)},
            {"src": "lfo", "effect": "HARMONY", "param": "pitch",
             "shape": "sine", "speed": (0.3, 2.0), "depth": (0.02, 0.1)},
        ],
    },
    {
        "name": "ROBOT",
        "essence": "ring modulation - metallic robotic voice",
        "chain": [
            ("RING", {"frequency": (400.0, 4000.0), "mix": (0.4, 1.0)}),
            ("DIST", {"amount": (2.0, 15.0), "mix": (0.2, 0.6)}),
        ],
        "mods": [
            {"src": "lfo", "effect": "RING", "param": "frequency",
             "shape": "square", "speed": (0.5, 4.0), "depth": (0.1, 0.5)},
        ],
    },
    {
        "name": "GRIT",
        "essence": "distortion / fuzz - drive and saturation",
        "chain": [
            ("DIST", {"amount": (10.0, 40.0), "mix": (0.5, 1.0)}),
            ("LOWPASS", {"cutoff": (0.3, 0.8)}),
        ],
        "mods": [
            {"src": "handle", "effect": "DIST", "param": "amount",
             "depth": (4.0, 15.0)},
            {"src": "shake", "effect": "DIST", "param": "mix",
             "depth": (0.2, 0.6)},
        ],
    },
    {
        "name": "WOBBLE",
        "essence": "filter wobble - tremolo / wub-wub",
        "chain": [
            ("LOWPASS", {"cutoff": (0.2, 0.6)}),
            ("HIGHPASS", {"cutoff": (0.1, 0.4)}),
        ],
        "mods": [
            {"src": "lfo", "effect": "LOWPASS", "param": "cutoff",
             "shape": "sawtooth", "speed": (1.0, 8.0), "depth": (0.1, 0.5)},
            {"src": "handle", "effect": "LOWPASS", "param": "cutoff",
             "depth": (0.2, 0.5)},
        ],
    },
    {
        "name": "RADIO",
        "essence": "broken radio - bandpassed lo-fi static",
        "chain": [
            ("HIGHPASS", {"cutoff": (0.3, 0.7)}),
            ("LOWPASS", {"cutoff": (0.2, 0.6)}),
            ("DIST", {"amount": (3.0, 12.0), "mix": (0.2, 0.5)}),
            ("SSB", {"frequency": (-300.0, 300.0)}),
        ],
        "mods": [
            {"src": "handle", "effect": "LOWPASS", "param": "cutoff",
             "depth": (0.3, 0.6)},
            {"src": "shake", "effect": "SSB", "param": "frequency",
             "depth": (200.0, 2000.0)},
        ],
    },
    {
        "name": "GLITCH",
        "essence": "glitch / stutter - atonal chaos",
        "chain": [
            ("SSB", {"frequency": (-12000.0, 12000.0)}),
            ("RING", {"frequency": (200.0, 6000.0), "mix": (0.3, 0.8)}),
        ],
        "mods": [
            {"src": "shake", "effect": "SSB", "param": "frequency",
             "depth": (1000.0, 8000.0)},
            {"src": "lfo", "effect": "RING", "param": "mix",
             "shape": "random", "speed": (1.0, 10.0), "depth": (0.1, 0.5)},
            {"src": "trigger", "effect": "RING"},
        ],
    },
]

# Sane defaults approximating the four factory presets.
DEFAULT_PRESETS = [
    {"name": "ECHO",
     "list": [{"effect": "DELAY", "time": 0.4, "echo": 0.5, "wet-level": 0.6}]},
    {"name": "SPRING",
     "list": [{"effect": "DELAY", "time": 0.2, "echo": 0.3},
              {"effect": "REVERB", "time": 0.6, "spring-mix": 0.8}]},
    {"name": "PIXIE",
     "list": [{"effect": "HARMONY", "pitch": 1.6, "dry-level": 0.5},
              {"effect": "REVERB", "time": 0.3}]},
    {"name": "ROBOT",
     "list": [{"effect": "RING", "frequency": 900.0, "mix": 0.6},
              {"effect": "DIST", "amount": 8.0}]},
]


def _rand(rng: random.Random, lo: float, hi: float) -> float:
    return round(rng.uniform(lo, hi), 3)


def _row_of(chain: list[dict], effect: str) -> int:
    for i, e in enumerate(chain):
        if e["effect"] == effect:
            return i
    return 0


def build_typed_preset(rng: random.Random, spec: dict, pos: int) -> dict:
    """Build one preset from an FX-type recipe, randomising values in-range."""
    chain = []
    for effect, params in spec["chain"]:
        row = {"effect": effect}
        for param, (lo, hi) in params.items():
            row[param] = _rand(rng, lo, hi)
        chain.append(row)

    preset: dict = {"pos": pos, "name": spec["name"], "list": chain}

    for mod in spec.get("mods", []):
        src = mod["src"]
        if src == "trigger":
            preset["trigger"] = {"row": _row_of(chain, mod["effect"])}
            continue
        row = _row_of(chain, mod["effect"])
        param = mod["param"]
        if src == "lfo":
            preset["lfo"] = {
                "row": row, "param": param,
                "depth": _rand(rng, *mod.get("depth", (0.05, 0.5))),
                "shape": mod.get("shape", rng.choice(LFO_SHAPES)),
                "speed": _rand(rng, *mod.get("speed", (0.5, 4.0))),
                "phase": rng.randint(0, 3),
            }
        else:
            depth_lo, depth_hi = mod.get("depth", (-1.0, 1.0))
            preset[src] = {"row": row, "param": param,
                           "depth": _rand(rng, depth_lo, depth_hi)}
    return preset


def build_config(name: str, presets: list[dict],
                 samples: list[dict] | None = None) -> dict:
    cfg: dict = {"name": name}
    if samples:
        cfg["samples"] = samples
    cfg["presets"] = presets
    return cfg


def default_config(name: str) -> dict:
    presets = [{"pos": pos, **p} for pos, p in enumerate(DEFAULT_PRESETS)]
    return build_config(name, presets)


def typed_config(name: str, styles: list[int] | None = None,
                 seed: int | None = None) -> dict:
    """Four presets drawn from the 8 FX types.

    `styles` is a list of 0-based type indices (length 0..4). Given types are
    used in order for the first slots; the remaining slots are filled with
    random, distinct types from the rest of the list.
    """
    rng = random.Random(seed)
    styles = list(styles or [])
    if len(styles) > 4:
        raise ValueError("at most 4 FX styles fit the 4 slots")
    for i in styles:
        if not 0 <= i < len(FX_TYPES):
            raise ValueError(f"FX style {i + 1} out of range 1..8")
    if len(set(styles)) != len(styles):
        raise ValueError("duplicate FX style")

    pool = [i for i in range(len(FX_TYPES)) if i not in styles]
    rng.shuffle(pool)
    chosen = (styles + pool)[:4]

    presets = []
    for pos, idx in enumerate(chosen):
        presets.append(build_typed_preset(rng, FX_TYPES[idx], pos))
    return build_config(name, presets)


def sample_entries(files: list[str] | None = None) -> list[dict]:
    """Build a `samples` section. Defaults to 1.wav..4.wav, oneshot."""
    files = files or [f"{i}.wav" for i in (1, 2, 3, 4)]
    return [{"pos": i, "file": f, "playmode": "oneshot"}
            for i, f in enumerate(files[:4])]


def write_config(cfg: dict, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    return out
