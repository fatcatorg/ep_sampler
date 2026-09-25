#!/usr/bin/env python3
"""Build an EP-1320 .pak that restores the factory sound set *and* adds 5
hand-assigned programmes (one project TAR each).

The real EP-1320 factory programmes (pad assignments) aren't available yet, so
this script fills them in manually, loosely following the EP-40 group types:

    group A - drums      (kicks, snares, claps, hats/tambos, toms, percussion)
    group B - bass       (bass + drones + low toms to fill the 12 pads)
    group C - chords/melody (fanfares, flutes, hurdy-gurdy, citole, shawn, stabs)
    group D - vocals/fx  (grunts, laughter, swords, animals)

Every programme has 12 pads in each of the 4 groups. Sounds are referenced by
their factory slot (1..220) and stay at those slots; some are reused across
programmes, which is fine.

Run from the repo root:

    python build_ep1320_programmes.py            # build ep1320-programmes-<date>.pak
    python build_ep1320_programmes.py --dry-run  # just print the assignments
    python build_ep1320_programmes.py --as ep40  # tag the pak for another device
"""

import argparse
import sys
from pathlib import Path

from ep_sampler.cli import (_cleanup_build_dir, _convert_samples,
                            _expand_pak_name, load_config)
from ep_sampler.factory import (device_meta, find_samples, has_factory_list,
                                normalize_device)
from ep_sampler.manifest import Sample
from ep_sampler.pad_record import build_pad_record
from ep_sampler.pak import _wav_frames, build, build_project_tar

# --------------------------------------------------------------------------
# The 5 programmes. Each is {group: [12 factory slots]}.
# Pad 1..12 within a group map to the list order.
# --------------------------------------------------------------------------

PROGRAMMES = [
    {   # 1 SIEGE
        "name": "SIEGE",
        "A": [1, 10, 19, 27, 29, 46, 50, 32, 36, 42, 6, 20],      # battle kik, fair snare, clap, tambo hat/cap, toms, coconut, dropper, metal clank, stomp
        "B": [125, 126, 127, 70, 93, 151, 152, 56, 59, 63, 125, 126],  # 3 basses + drones + deep toms/plague drums
        "C": [101, 87, 76, 128, 144, 71, 90, 118, 135, 138, 109, 130], # flute, citole, hurdy, stabb, chord, fanfare, shawn, trumpet, horn, gurdy
        "D": [189, 192, 203, 155, 156, 163, 166, 174, 176, 210, 214, 216],  # grunts, laugh, bell, anvil, arrow, sword, chain, drawbridge, bee, dragon, horse
    },
    {   # 2 DUNGEON
        "name": "DUNGEON",
        "A": [3, 12, 19, 28, 21, 48, 52, 33, 37, 39, 7, 22],       # axe kik, tambo snare, clap, tambo short, toms, coconut, scrap, debris, stomp
        "B": [125, 127, 126, 151, 152, 70, 57, 60, 64, 53, 125, 127],
        "C": [102, 88, 77, 129, 145, 72, 112, 119, 136, 139, 110, 131], # flute B, citole B, hurdy B, stabb B, chord B, fanfare B, shawn phrase, bagpipe, honk, horn B, gurdy B
        "D": [190, 193, 204, 157, 158, 164, 167, 175, 177, 211, 215, 217],  # grunt B, laugh B, armor, beheading, broadsword, sword B, chain thud, crowd, chickens, goat, horse B
    },
    {   # 3 TAVERN
        "name": "TAVERN",
        "A": [2, 11, 19, 24, 25, 47, 51, 34, 40, 44, 8, 23],       # medium evil kik, market snare, clap, tambo E/long, toms, coconut, debris, brush, stomp
        "B": [126, 125, 127, 93, 151, 152, 58, 61, 65, 54, 126, 125],
        "C": [103, 89, 78, 132, 146, 73, 113, 120, 137, 140, 111, 133], # flute C, hurdys, hurdy C, stab C, chord C, fanfare C, shawn phrase B, bow harp, honk long, horn C, gurdy C
        "D": [191, 194, 205, 159, 160, 165, 168, 178, 180, 212, 218, 219],  # grunt C, laugh C, clanks, broadsword B, sword C, machinery, tavern, cow, birdy, piggy
    },
    {   # 4 WITCH HUNT
        "name": "WITCH HUNT",
        "A": [4, 13, 19, 26, 20, 49, 50, 35, 41, 45, 9, 30],       # medikik, jester snare, clap, tambo tight, toms, coconut D, rubble, roller, stomp, clapper
        "B": [127, 126, 125, 70, 93, 152, 59, 62, 66, 55, 127, 126],
        "C": [104, 83, 79, 134, 147, 74, 114, 122, 141, 142, 107, 153], # flute D, glittern, hurdy D, stab E, chord D, fanfare D, shawn phrase C, mouth harp, bow, brass swell, bow harp, hurdy cmaj
        "D": [192, 195, 206, 161, 162, 169, 170, 173, 179, 207, 208, 220],  # grunts, scream, clink, knife, sword D, sword clink, boil oil, machinery B, vvitch, witch laughter, rooster
    },
    {   # 5 ROYAL COURT
        "name": "ROYAL COURT",
        "A": [5, 14, 19, 29, 27, 46, 52, 31, 38, 43, 6, 25],       # royal kik, tight snare, clap, tambo cap/hat, toms, clapper B, junk, chain hit, stomp, tambo long
        "B": [125, 126, 127, 151, 152, 70, 56, 60, 64, 53, 125, 127],
        "C": [105, 84, 117, 130, 148, 75, 90, 118, 143, 138, 108, 154], # flute E, glittern B, hurdy gurdy, stab A, gitrn chord, fanfare E, shawn mel, trumpet, drill, horn, bow harp B, hurdy cmin
        "D": [196, 199, 200, 201, 209, 163, 171, 172, 181, 213, 216, 210],  # grunt E, peasant hey/whey/hoo, yell, arrow, sword clang/scrape, scrapper, donkey, horse, bee
    },
]


def programme_tar(assignments: dict, by_slot: dict, sounds_dir: Path) -> bytes:
    """Build one project TAR: (group, pad) -> 26-byte pad record."""
    records: dict[tuple[str, int], bytes] = {}
    for group in "abcd":
        for pad, slot in enumerate(assignments[group.upper()], 1):
            sample = by_slot[slot]
            frames = _wav_frames(sounds_dir / sample.wav_name)
            records[(group, pad)] = build_pad_record(slot, frames)
    return build_project_tar(records)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", type=Path, default=None,
                    help="path to config.json (default: ./config.json)")
    ap.add_argument("--as", dest="as_device", default=None,
                    help="tag the pak as a different device (e.g. ep40)")
    ap.add_argument("--out", default=None, help="full output path")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the assignments without building")
    ap.add_argument("--device-version", default=None,
                    help="override device_version in meta.json")
    args = ap.parse_args()

    device = normalize_device("ep1320")
    cfg = load_config(args.config)

    meta = device_meta(device)
    tag = device_meta(normalize_device(args.as_device)) if args.as_device else None
    target = tag or meta
    cfg["device_name"] = target["device_name"]
    cfg["device_sku"] = target["device_sku"]
    cfg["base_sku"] = target.get("base_sku", "")
    if args.device_version:
        cfg["device_version"] = args.device_version
    cfg["pak_type"] = meta.get("pak_type", cfg["pak_type"])
    cfg["pak_release"] = meta.get("pak_release", cfg["pak_release"])

    out_dir = Path(cfg["out_dir"]).expanduser()
    sounds_dir = out_dir / cfg["build_dir"] / "sounds"

    # Same search order as `build-factory`.
    dirs: list[Path] = []
    for key in (f"{device}_samples_dir", "samples_dir"):
        if key == "samples_dir" and not has_factory_list(device):
            continue
        val = cfg.get(key)
        if val:
            p = Path(str(val)).expanduser()
            if p.is_dir():
                dirs.append(p)

    print("searching: " + ", ".join(str(d) for d in dirs))
    found, missing = find_samples(device, dirs)
    print(f"matched {len(found)}/{len(found) + len(missing)} factory samples")
    if missing:
        print(f"missing {len(missing)} samples (skipped):")
        for s in missing:
            print(f"  slot {s.slot:3d}  {s.name}")

    by_slot = {s.slot: Sample(slot=s.slot, name=s.name, src=path)
               for s, path in found}
    samples = sorted(by_slot.values(), key=lambda s: s.slot)

    if args.dry_run:
        for prog in PROGRAMMES:
            print(f"\n=== {prog['name']} ===")
            for g in "ABCD":
                names = [by_slot[s].name if s in by_slot else f"slot {s}?"
                         for s in prog[g]]
                print(f"  {g.upper()}: " + ", ".join(names))
        return 0

    if not _convert_samples(samples, sounds_dir, cfg):
        return 1

    # One project TAR per programme.
    projects = {}
    for i, prog in enumerate(PROGRAMMES, 1):
        projects[f"P{i:02d}.tar"] = programme_tar(prog, by_slot, sounds_dir)
    print(f"built {len(projects)} programme TARs")

    out = Path(args.out).expanduser() if args.out else \
        out_dir / _expand_pak_name(f"{device}-programmes-__DATE__.pak", cfg)
    cfg["out"] = str(out)
    cfg["mode"] = "scratch"

    summary = build(cfg, samples, sounds_dir, project_tars=projects)
    print(f"built {summary['out']}")
    print(f"  device {cfg['device_name']}  factory {meta['device_name']}  "
          f"samples {summary['samples']}  programmes {len(projects)}")
    _cleanup_build_dir(sounds_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
