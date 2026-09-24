#!/usr/bin/env python3
"""Factory sample definitions for the EP-series samplers.

The EP-133 and EP-1320 factory sound sets ship as text files under `data/`, one
`slot<TAB>name` pair per line. These are name/slot *lists* (not audio), sourced
from community documentation - see README for attribution. Devices without a
bundled list (the EP-40) discover their factory set from the slot-numbered
filenames themselves.

This module also locates a user's copies of those samples on disk: files are
matched by name (case-insensitive, ignoring punctuation/spaces) so a factory
sample named "BATTLE KIK" matches `battle_kik.wav`, `BATTLE KIK.WAV`, etc.
"""

import re
from dataclasses import dataclass
from pathlib import Path

AUDIO_EXTS = (".wav", ".aif", ".aiff", ".mp3", ".flac", ".ogg", ".m4a")

# Device identity used in the .pak meta.json. Values are verified against
# real Sample Tool backups where possible (EP-40, EP-133); the EP-1320 still
# needs its backup to confirm device_version / pak_release / pak_type.
DEVICES = {
    "ep40": {
        "device_name": "EP-40",
        "device_sku": "TE032AS006",
        "base_sku": "",
        "device_version": "2.5.1",
        "pak_release": "1.2.0",
        "pak_type": "user",
    },
    "ep133": {
        "device_name": "EP-133",
        "device_sku": "TE032AS001",
        "base_sku": "",
        "device_version": "1.1.0",
        "pak_release": "1.1.0",
        "pak_type": "factory",
    },
    "ep1320": {
        "device_name": "EP-1320",
        "device_sku": "TE032AS001",
        "base_sku": "",
    },
    # The Ting is an FX microphone, not a sampler - it has no .pak / SKU, so
    # these fields are placeholders. It is handled by the ting config builder.
    "ep2350": {
        "device_name": "EP-2350",
        "device_sku": "EP-2350",
        "base_sku": "EP-2350",
    },
}

# Devices that can run a factory build. The EP-40 has no bundled list, so
# `find_samples` discovers its set from slot-numbered filenames instead.
FACTORY_DEVICES = ("ep133", "ep1320", "ep40")

# Menu labels, in menu order (EP-40 first so it is the default).
DEVICE_LABELS = {
    "ep40": "EP-40 Riddim",
    "ep133": "EP-133",
    "ep1320": "EP-1320",
    "ep2350": "EP-2350 Ting",
}
DEVICE_ORDER = ("ep40", "ep133", "ep1320", "ep2350")


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
        "ep2350": "ep2350", "2350": "ep2350", "ting": "ep2350",
    }
    d = aliases.get(d, d)
    if d not in DEVICES:
        raise ValueError(
            f"unknown device {device!r}; use 'ep40', 'ep133', 'ep1320' "
            f"or 'ep2350'")
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
            f"factory builds are available for EP-40, EP-133 and EP-1320")
    path = Path(__file__).parent / "data" / f"factory_{d}.txt"
    if not path.is_file():
        return []  # no bundled list; `find_samples` discovers it from files
    sounds: list[FactorySound] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            slot_s, _, name = line.partition("\t")
            sounds.append(FactorySound(int(slot_s), name.strip()))
    return sounds


def has_factory_list(device: str) -> bool:
    """True if a bundled factory list file exists for `device`."""
    d = normalize_device(device)
    return d in FACTORY_DEVICES and \
        (Path(__file__).parent / "data" / f"factory_{d}.txt").is_file()


def load_factory_projects(device: str) -> dict[str, bytes]:
    """Return {tar_name: bytes} of bundled factory project TARs (pad
    assignments, patterns, scenes, FX settings), or {} if none are bundled."""
    d = normalize_device(device)
    pdir = Path(__file__).parent / "data" / "projects" / d
    projects: dict[str, bytes] = {}
    if pdir.is_dir():
        for tar in sorted(pdir.glob("*.tar")):
            projects[tar.name] = tar.read_bytes()
    return projects


def _norm(text: str) -> str:
    """Lowercase and keep only ASCII letters/digits, for fuzzy name matching."""
    return "".join(c for c in text.lower() if c.isascii() and c.isalnum())


# Slot number followed by a separator (space/underscore/etc.) or directly by
# a letter (some files are named like '198FINAL BREATH.wav').
_SLOT_RE = re.compile(r"^(\d{1,3})(?:[\s._\-]+|(?=[A-Za-z]))")


def _leading_slot(stem: str) -> int | None:
    """Return the leading slot number in a stem like '25_kick sub'."""
    m = _SLOT_RE.match(stem)
    return int(m.group(1)) if m else None


def _strip_slot(stem: str) -> str:
    """Remove a leading slot number (and separator) from a filename stem."""
    return _SLOT_RE.sub("", stem, count=1)


def build_index(dirs: list[Path]) -> tuple[dict[str, Path], dict[int, Path]]:
    """Map normalised stem -> path and slot number -> path, scanning `dirs`.

    Directories are searched in order; the first match wins, and `.wav` is
    preferred over other audio extensions within a directory. Filenames that
    begin with a slot number (e.g. `25_kick sub.wav`) are also indexed by
    that slot - the reliable way to pair factory samples with their files.
    """
    by_name: dict[str, Path] = {}
    by_slot: dict[int, Path] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for ext in AUDIO_EXTS:
            for path in sorted(d.rglob(f"*{ext}")):
                key = _norm(path.stem)
                if key and key not in by_name:
                    by_name[key] = path
                slot = _leading_slot(path.stem)
                if slot is not None and slot not in by_slot:
                    by_slot[slot] = path
    return by_name, by_slot


def find_samples(device: str, dirs: list[Path]) -> tuple[list, list]:
    """Return (found, missing) for the device's factory sound set.

    `found` is a list of (FactorySound, Path); `missing` a list of
    FactorySound. `dirs` are searched in the given order. A file is matched
    by its leading slot number first (e.g. `25_kick sub.wav` -> slot 25),
    falling back to a normalised name match.

    Devices with no bundled list (the EP-40) discover their factory set from
    the slot-numbered filenames themselves.
    """
    by_name, by_slot = build_index(dirs)
    sounds = load_factory(device)
    if not sounds:
        sounds = [
            FactorySound(slot=slot,
                         name=_strip_slot(by_slot[slot].stem).strip()
                              or f"SAMPLE {slot}")
            for slot in sorted(by_slot)
        ]
    found: list[tuple[FactorySound, Path]] = []
    missing: list[FactorySound] = []
    for sound in sounds:
        path = by_slot.get(sound.slot) or by_name.get(_norm(sound.name))
        if path:
            found.append((sound, path))
        else:
            missing.append(sound)
    return found, missing
