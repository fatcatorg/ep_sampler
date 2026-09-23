#!/usr/bin/env python3
"""Command-line interface for ep_sampler.

Commands:
    build    convert the manifest's samples and build the .ppak
    add      append one sample to the manifest
    inspect  list the contents of a built .ppak
"""

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

from . import __version__
from .audio import convert_wav
from .manifest import parse_manifest
from .pad_record import DEFAULT_BLANK_PAD, PAD_RECORD_SIZE
from .pak import build

DEFAULTS = {
    "samples_dir": "samples",
    "manifest_file": "manifest.txt",
    "out_dir": "out",
    "build_dir": "build",
    "pak_file_name": "project-__PROJECT__.ppak",
    "project": 1,
    "mode": "scratch",
    "base_pak": "",
    "device_name": "EP-133",
    "device_sku": "TE032AS001",
    "base_sku": "TE032AS001",
    "device_version": "2.0.5",
    "pak_release": "1.2.0",
    "pak_type": "project",
    "author": "computer",
    "audio_tool": "ffmpeg",
    "ffmpeg_bin": "ffmpeg",
    "sox_bin": "sox",
    "ffmpeg_extra_args": [],
    "sox_extra_args": [],
}


def load_config(path: Path | None) -> dict:
    cfg = dict(DEFAULTS)
    p = path or Path("config.json")
    if p.is_file():
        with open(p, "r", encoding="utf-8") as fh:
            user = json.load(fh)
        unknown = set(user) - set(DEFAULTS)
        if unknown:
            print(f"warning: ignoring unknown config keys: {sorted(unknown)}",
                  file=sys.stderr)
        cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
    return cfg


def _merge(cfg: dict, args, *names: str) -> dict:
    for n in names:
        val = getattr(args, n, None)
        if val is not None:
            cfg[n] = val
    return cfg


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def cmd_build(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    _merge(cfg, args,
           "samples_dir", "manifest_file", "out_dir", "project", "mode",
           "base_pak", "device_name", "device_sku", "base_sku",
           "device_version", "pak_release", "pak_type", "author",
           "audio_tool", "ffmpeg_bin", "sox_bin")

    samples_dir = Path(cfg["samples_dir"]).expanduser()
    manifest_path = Path(cfg["manifest_file"]).expanduser()
    out_dir = Path(cfg["out_dir"]).expanduser()
    sounds_dir = out_dir / cfg["build_dir"] / "sounds"

    if not manifest_path.is_file():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    samples = parse_manifest(manifest_path, samples_dir)

    tool = cfg["audio_tool"]
    if tool == "sox":
        extra = cfg.get("sox_extra_args") or []
    else:
        extra = cfg.get("ffmpeg_extra_args") or []
    for s in samples:
        if not s.src.is_file():
            print(f"sample file not found: {s.src} (slot {s.slot})",
                  file=sys.stderr)
            return 1
        dst = sounds_dir / s.wav_name
        if _needs_conversion(s.src, dst):
            print(f"converting {s.src.name} -> {s.wav_name}")
            convert_wav(s.src, dst, tool=tool,
                        ffmpeg_bin=cfg["ffmpeg_bin"], sox_bin=cfg["sox_bin"],
                        extra_args=extra)

    out_name = cfg["pak_file_name"].replace(
        "__PROJECT__", f"{cfg['project']:02d}")
    cfg["out"] = str(out_dir / out_name)

    summary = build(cfg, samples, sounds_dir)
    print(f"built {summary['out']}")
    print(f"  project P{summary['project']:02d}  samples {summary['samples']}")
    print("  pads " + ", ".join(summary["pads"]))
    return 0


def _needs_conversion(src: Path, dst: Path) -> bool:
    return not dst.is_file() or src.stat().st_mtime > dst.stat().st_mtime


# --------------------------------------------------------------------------
# add
# --------------------------------------------------------------------------

def cmd_add(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    manifest_path = Path(cfg["manifest_file"]).expanduser()

    src = Path(args.file).expanduser()
    if not src.is_file():
        print(f"not a file: {src}", file=sys.stderr)
        return 1

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if not manifest_path.is_file():
        manifest_path.write_text("", encoding="utf-8")

    existing = []
    if manifest_path.is_file():
        existing = parse_or_none(manifest_path, Path(cfg["samples_dir"]))
    existing = existing or []

    slot = args.slot
    if slot is None:
        slot = max([s.slot for s in existing] + [0]) + 1

    group = (args.group or "A").upper()
    pad = args.pad
    if pad is None:
        used = {s.pad for s in existing if s.group == group.lower()}
        pad = next((p for p in range(1, 13) if p not in used), 1)

    name = args.name
    if not name:
        name = re.sub(r"\.[^.]+$", "", src.name)
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "sample"
    name = name[:20]

    time_mode = args.time_mode or "off"
    playmode = args.playmode or "oneshot"
    bpm = args.bpm if args.bpm is not None else ""

    # store the file path relative to samples_dir when it is underneath it
    samples_dir = Path(cfg["samples_dir"]).expanduser()
    try:
        file_ref = str(src.resolve().relative_to(samples_dir.resolve()))
    except ValueError:
        file_ref = str(src)

    line = "\t".join(str(x) for x in
                     [slot, group, pad, bpm, time_mode, playmode, name, file_ref])
    with open(manifest_path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(f"added slot {slot} -> group {group} pad {pad} ({name})")
    return 0


def parse_or_none(path: Path, samples_dir: Path):
    try:
        return parse_manifest(path, samples_dir)
    except ValueError:
        return []


# --------------------------------------------------------------------------
# inspect
# --------------------------------------------------------------------------

def cmd_inspect(args: argparse.Namespace) -> int:
    path = Path(args.file).expanduser()
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 1

    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        print(f"{path.name}:")
        meta = json.loads(zf.read("/meta.json")) if "/meta.json" in names else None
        if meta:
            print("  meta:")
            for k, v in meta.items():
                print(f"    {k}: {v}")

        sounds = [n for n in names if n.startswith("/sounds/")]
        print(f"  sounds: {len(sounds)}")
        for n in sorted(sounds):
            print(f"    {n}")

        tars = [n for n in names if "/projects/" in n and n.endswith(".tar")]
        for t in tars:
            print(f"  project {t}:")
            _print_pads(zf.read(t))
    return 0


def _print_pads(tar_bytes: bytes) -> None:
    from .pak import find_pad_record_offsets
    import struct
    offsets = find_pad_record_offsets(tar_bytes)
    for (group, pad), off in sorted(offsets.items()):
        rec = tar_bytes[off:off + PAD_RECORD_SIZE]
        if rec == DEFAULT_BLANK_PAD:
            continue
        slot = rec[1]
        bpm = struct.unpack("<f", rec[12:16])[0]
        time_mode = {0: "off", 1: "bpm", 2: "bar"}.get(rec[21], "?")
        playmode = {0: "oneshot", 1: "key", 2: "legato"}.get(rec[23], "?")
        print(f"    {group.upper()}-{pad}: slot {slot}  bpm {bpm:.1f}  "
              f"{time_mode}  {playmode}")


# --------------------------------------------------------------------------
# argparse
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ep-sampler",
        description="Build a list of sample WAVs into an EP-133 .ppak backup.")
    p.add_argument("--version", action="version",
                   version=f"ep-sampler {__version__}")
    p.add_argument("--config", type=Path, default=None,
                   help="path to config.json (default: ./config.json)")

    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="convert samples and build the .ppak")
    b.add_argument("--samples-dir", default=None)
    b.add_argument("--manifest", dest="manifest_file", default=None)
    b.add_argument("--out-dir", default=None)
    b.add_argument("--project", type=int, default=None)
    b.add_argument("--mode", choices=["scratch", "base"], default=None)
    b.add_argument("--base", dest="base_pak", default=None)
    b.add_argument("--device-name", default=None)
    b.add_argument("--device-sku", default=None)
    b.add_argument("--base-sku", default=None)
    b.add_argument("--device-version", default=None)
    b.add_argument("--pak-release", default=None)
    b.add_argument("--pak-type", default=None)
    b.add_argument("--author", default=None)
    b.add_argument("--audio-tool", choices=["ffmpeg", "sox"], default=None)
    b.add_argument("--ffmpeg-bin", default=None)
    b.add_argument("--sox-bin", default=None)
    b.set_defaults(func=cmd_build)

    a = sub.add_parser("add", help="append one sample to the manifest")
    a.add_argument("file")
    a.add_argument("--slot", type=int, default=None)
    a.add_argument("--group", default=None)
    a.add_argument("--pad", type=int, default=None)
    a.add_argument("--bpm", type=float, default=None)
    a.add_argument("--time-mode", default=None)
    a.add_argument("--playmode", default=None)
    a.add_argument("--name", default=None)
    a.set_defaults(func=cmd_add)

    i = sub.add_parser("inspect", help="list the contents of a .ppak")
    i.add_argument("file")
    i.set_defaults(func=cmd_inspect)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
