#!/usr/bin/env python3
"""Factory sample definitions for the EP-133 K.O. II and EP-1320 Medieval.

The factory sound set is shipped as two small text files under `data/`, one
`slot<TAB>name` pair per line. These are name/slot *lists* (not audio), sourced
from community documentation - see README for attribution.

This module also locates a user's copies of those samples on disk: files are
matched by name (case-insensitive, ignoring punctuation/spaces) so a factory
sample named "BATTLE KIK" matches `battle_kik.wav`, `BATTLE KIK.WAV`, etc.
"""

from dataclasses import dataclass
from pathlib import Path

AUDIO_EXTS = (".wav", ".aif", ".aiff", ".mp3", ".flac", ".ogg", ".m4a")

# Device identity used in the .ppak meta.json. The hardware SKU is shared
# across the TE032 family; device_version reflects the running OS. The EP-40
# Riddim ships the 128 MiB board (TE032AS002). These are sensible defaults -
# verify against a real Sample Tool backup of your own unit (`inspect`).
DEVICES = {
    "ep40": {
        "device_name": "EP-40",
        "device_sku": "TE032AS002",
        "base_sku": "TE032AS001",
    },
    "ep133": {
        "device_name": "EP-133",
        "device_sku": "TE032AS001",
        "base_sku": "TE032AS001",
    },
    "ep1320": {
        "device_name": "EP-1320",
        "device_sku": "TE032AS001",
        "base_sku": "TE032AS001",
    },
}

# Only these devices ship a factory sample set in this tool.
FACTORY_DEVICES = ("ep133", "ep1320")

# Menu labels, in menu order (EP-40 first so it is the default).
DEVICE_LABELS = {
    "ep40": "EP-40 Riddim",
    "ep133": "EP-133",
    "ep1320": "EP-1320",
}
DEVICE_ORDER = ("ep40", "ep133", "ep1320")


@dataclass
class FactorySound:
    slot: int
    name: str


def normalize_device(device: str) -> str:
    """Normalise 'ep-40' / 'riddim' / '133' / 'EP1320' -> 'ep40' etc."""
    d = device.strip().lower().replace("-", "").replace("_", "")
    aliases = {
        "ep40": "ep40", "40": "ep40", "riddim": "ep40",
        "ep133": "ep133", "133": "ep133", "ko2": "ep133",
        "ep1320": "ep1320", "1320": "ep1320", "medieval": "ep1320",
    }
    d = aliases.get(d, d)
    if d not in DEVICES:
        raise ValueError(
            f"unknown device {device!r}; use 'ep40', 'ep133' or 'ep1320'")
    return d


def device_meta(device: str) -> dict:
    return dict(DEVICES[normalize_device(device)])


def device_label(device: str) -> str:
    return DEVICE_LABELS[normalize_device(device)]


def load_factory(device: str) -> list[FactorySound]:
    d = normalize_device(device)
    if d not in FACTORY_DEVICES:
        raise ValueError(
            f"no factory sample set is bundled for {device_label(d)}; "
            f"factory builds are available for EP-133 and EP-1320")
    path = Path(__file__).parent / "data" / f"factory_{d}.txt"
    sounds: list[FactorySound] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            slot_s, _, name = line.partition("\t")
            sounds.append(FactorySound(int(slot_s), name.strip()))
    return sounds


def _norm(text: str) -> str:
    """Lowercase and keep only ASCII letters/digits, for fuzzy name matching."""
    return "".join(c for c in text.lower() if c.isascii() and c.isalnum())


def build_index(dirs: list[Path]) -> dict[str, Path]:
    """Map normalised file stem -> path, scanning `dirs` recursively.

    Directories are searched in order; the first match wins, and `.wav` is
    preferred over other audio extensions within a directory."""
    index: dict[str, Path] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for ext in AUDIO_EXTS:
            for path in sorted(d.rglob(f"*{ext}")):
                key = _norm(path.stem)
                if key and key not in index:
                    index[key] = path
    return index


def find_samples(device: str, dirs: list[Path]) -> tuple[list, list]:
    """Return (found, missing) for the device's factory sound set.

    `found` is a list of (FactorySound, Path); `missing` a list of
    FactorySound. `dirs` are searched in the given order."""
    index = build_index(dirs)
    found: list[tuple[FactorySound, Path]] = []
    missing: list[FactorySound] = []
    for sound in load_factory(device):
        path = index.get(_norm(sound.name))
        if path:
            found.append((sound, path))
        else:
            missing.append(sound)
    return found, missing
