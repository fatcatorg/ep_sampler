#!/usr/bin/env python3
"""Hand-assigned factory programmes for devices whose real factory project
data isn't bundled yet.

The EP-1320's official factory programmes (pad assignments) aren't available,
so `build-factory ep1320` falls back to these hand-made assignments until the
real ones are found. They follow the EP-40 group layout:

    group A - drums       (kicks, snares, claps, hats/tambos, toms, percussion)
    group B - bass        (bass + drones + low toms to fill the 12 pads)
    group C - chords/melody (fanfares, flutes, hurdy-gurdy, citole, shawn, stabs)
    group D - vocals/fx   (grunts, laughter, swords, animals)

Each programme has 12 pads per group; slot numbers refer to the factory
sample library (1..220 for the EP-1320). Some sounds are reused, which is fine.
"""

from pathlib import Path

from .pad_record import build_pad_record, build_pad_record_ep40
from .pak import _wav_frames, build_project_tar

# {device: [ {name, A: [12 slots], B: [...], C: [...], D: [...]}, ... ]}
# Pad 1..12 within a group map to the list order.
FACTORY_PROGRAMMES = {
    "ep1320": [
        {   # 1 SIEGE
            "name": "SIEGE",
            "A": [1, 10, 19, 27, 29, 46, 50, 32, 36, 42, 6, 20],
            "B": [125, 126, 127, 70, 93, 151, 152, 56, 59, 63, 125, 126],
            "C": [101, 87, 76, 128, 144, 71, 90, 118, 135, 138, 109, 130],
            "D": [189, 192, 203, 155, 156, 163, 166, 174, 176, 210, 214, 216],
        },
        {   # 2 DUNGEON
            "name": "DUNGEON",
            "A": [3, 12, 19, 28, 21, 48, 52, 33, 37, 39, 7, 22],
            "B": [125, 127, 126, 151, 152, 70, 57, 60, 64, 53, 125, 127],
            "C": [102, 88, 77, 129, 145, 72, 112, 119, 136, 139, 110, 131],
            "D": [190, 193, 204, 157, 158, 164, 167, 175, 177, 211, 215, 217],
        },
        {   # 3 TAVERN
            "name": "TAVERN",
            "A": [2, 11, 19, 24, 25, 47, 51, 34, 40, 44, 8, 23],
            "B": [126, 125, 127, 93, 151, 152, 58, 61, 65, 54, 126, 125],
            "C": [103, 89, 78, 132, 146, 73, 113, 120, 137, 140, 111, 133],
            "D": [191, 194, 205, 159, 160, 165, 168, 178, 180, 212, 218, 219],
        },
        {   # 4 WITCH HUNT
            "name": "WITCH HUNT",
            "A": [4, 13, 19, 26, 20, 49, 50, 35, 41, 45, 9, 30],
            "B": [127, 126, 125, 70, 93, 152, 59, 62, 66, 55, 127, 126],
            "C": [104, 83, 79, 134, 147, 74, 114, 122, 141, 142, 107, 153],
            "D": [192, 195, 206, 161, 162, 169, 170, 173, 179, 207, 208, 220],
        },
        {   # 5 ROYAL COURT
            "name": "ROYAL COURT",
            "A": [5, 14, 19, 29, 27, 46, 52, 31, 38, 43, 6, 25],
            "B": [125, 126, 127, 151, 152, 70, 56, 60, 64, 53, 125, 127],
            "C": [105, 84, 117, 130, 148, 75, 90, 118, 143, 138, 108, 154],
            "D": [196, 199, 200, 201, 209, 163, 171, 172, 181, 213, 216, 210],
        },
    ],
}


def has_factory_programmes(device: str) -> bool:
    """True if hand-assigned factory programmes are bundled for `device`."""
    return device in FACTORY_PROGRAMMES


def build_factory_projects(device: str, samples: list, sounds_dir: Path,
                           ep40: bool = False) -> dict[str, bytes]:
    """Build one project TAR per hand-assigned programme for `device`.

    `samples` are the factory `Sample` objects (already converted into
    `sounds_dir`); frame lengths are read from the converted WAVs so the pad
    records carry the correct lengths. `ep40` switches the pad records and
    blank pads to the EP-40's 29-byte format.
    """
    programmes = FACTORY_PROGRAMMES.get(device)
    if not programmes:
        return {}

    by_slot = {s.slot: s for s in samples}
    builder = build_pad_record_ep40 if ep40 else build_pad_record
    projects: dict[str, bytes] = {}
    for i, prog in enumerate(programmes, 1):
        records: dict[tuple[str, int], bytes] = {}
        for group in "abcd":
            for pad, slot in enumerate(prog[group.upper()], 1):
                sample = by_slot[slot]
                frames = _wav_frames(sounds_dir / sample.wav_name)
                records[(group, pad)] = builder(slot, frames)
        projects[f"P{i:02d}.tar"] = build_project_tar(records, ep40)
    return projects
