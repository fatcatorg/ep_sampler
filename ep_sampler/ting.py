#!/usr/bin/env python3
"""EP-2350 Ting (FX microphone) config.json builder and randomizer.

The Ting is a standalone handheld FX mic. It mounts a tiny writable disk and
reads a single `config.json` that defines up to 4 effect presets (the four
"FX" buttons: ECHO, SPRING, PIXIE, ROBOT) plus optional sample triggers.

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

This module can also *randomize* the FX: random effect chains, random parameter
values (kept inside the documented ranges), and random handle/shake/lfo/trigger
modulation - "go crazy".
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

# Effects that process the live microphone voice (excludes SAMPLE, which only
# plays a stored sample). Factory presets are voice FX.
VOICE_EFFECTS = [e for e in EFFECTS if e != "SAMPLE"]

LFO_SHAPES = ("sine", "square", "sawtooth", "random")
PLAYMODES = ("oneshot", "hold", "startstop")

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


def _random_param(rng: random.Random, effect: str) -> str | None:
    params = list(EFFECTS[effect])
    return rng.choice(params) if params else None


def random_effect(rng: random.Random, allow_sample: bool = True) -> dict:
    pool = list(EFFECTS) if allow_sample else VOICE_EFFECTS
    name = rng.choice(pool)
    eff: dict = {"effect": name}
    for param, (lo, hi) in EFFECTS[name].items():
        if rng.random() < 0.75:
            eff[param] = _rand(rng, lo, hi)
    if rng.random() < 0.15:
        eff["BUS"] = rng.choice((1, 2))
    return eff


def random_preset(rng: random.Random, pos: int, crazy: bool = True) -> dict:
    n = rng.randint(1, 5 if crazy else 3)
    chain = [random_effect(rng) for _ in range(n)]
    preset: dict = {"pos": pos, "list": chain}

    # handle: continuous control of one parameter
    if rng.random() < 0.7:
        row = rng.randrange(len(chain))
        param = _random_param(rng, chain[row]["effect"])
        if param:
            preset["handle"] = {"row": row, "param": param,
                                "depth": round(rng.uniform(-1.0, 1.0), 3)}

    # shake: momentary glitch
    if rng.random() < 0.55:
        row = rng.randrange(len(chain))
        param = _random_param(rng, chain[row]["effect"])
        if param:
            preset["shake"] = {"row": row, "param": param,
                               "depth": round(rng.uniform(0.2, 1.0), 3)}

    # lfo: automatic cycling (sometimes handle-driven instead)
    if rng.random() < 0.5:
        row = rng.randrange(len(chain))
        param = _random_param(rng, chain[row]["effect"])
        if param:
            lfo = {"row": row, "param": param,
                   "depth": round(rng.uniform(0.05, 0.6), 3),
                   "shape": rng.choice(LFO_SHAPES),
                   "speed": round(rng.uniform(0.2, 8.0), 2),
                   "phase": rng.randint(0, 3)}
            preset["lfo"] = lfo
            if rng.random() < 0.3:
                preset["handle"] = {"target": "lfo", "param": "speed",
                                    "depth": round(rng.uniform(2.0, 15.0), 2)}

    # trigger: fire a sample from a chain row
    if rng.random() < 0.4:
        preset["trigger"] = {"row": rng.randrange(len(chain))}

    return preset


def build_config(name: str, presets: list[dict],
                 samples: list[dict] | None = None) -> dict:
    cfg: dict = {"name": name}
    if samples:
        cfg["samples"] = samples
    cfg["presets"] = presets
    return cfg


def default_config(name: str) -> dict:
    presets = []
    for pos, p in enumerate(DEFAULT_PRESETS):
        presets.append({"pos": pos, **p})
    return build_config(name, presets)


def random_config(name: str, seed: int | None = None,
                  crazy: bool = True) -> dict:
    rng = random.Random(seed)
    presets = [random_preset(rng, pos, crazy=crazy) for pos in range(4)]
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
