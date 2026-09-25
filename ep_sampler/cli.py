#!/usr/bin/env python3
"""Command-line interface for ep_sampler.

Commands:
    build          convert the manifest's samples and build the .pak
    build-factory  build a .pak from the EP-133 / EP-1320 factory sample set
    ting           build an EP-2350 Ting config.json (FX mic)
    scan           scan the sample library and cache the index
    manifest       auto-build manifest.txt from the sample library
    add            append one sample to the manifest
    inspect        list the contents of a built .pak
"""

import argparse
import json
import os
import random
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from . import __version__
from .audio import convert_wav
from .factory import (DEVICE_LABELS, DEVICE_ORDER, FACTORY_DEVICES,
                      device_label, device_meta, find_samples,
                      has_factory_list, load_factory_projects,
                      normalize_device)
from .factory_programmes import (build_factory_projects,
                                 has_factory_programmes)
from .manifest import Sample, parse_manifest
from .manifest_build import (GUIDES, build_kits, build_manifest, load_index,
                             save_index, scan_library)
from .pad_record import DEFAULT_BLANK_PAD, PAD_RECORD_SIZE
from .pak import build
from .ting import (FX_TYPES, default_config, sample_entries, typed_config,
                   write_config)

DEFAULTS = {
    "samples_dir": "samples",
    "ep133_samples_dir": "",
    "ep1320_samples_dir": "",
    "ep40_samples_dir": "",
    "library_dir": "samples",
    "sample_index": "state/sample-index.json",
    "total_samples": 0,
    "sample_folders": [],
    "deepseek_api_key": "",
    "deepseek_model": "deepseek-chat",
    "deepseek_base_url": "https://api.deepseek.com",
    "manifest_file": "manifest.txt",
    "out_dir": "out",
    "build_dir": "build",
    "pak_file_name": "project-__PROJECT__-__DATE__.pak",
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


def _expand_pak_name(template: str, cfg: dict) -> str:
    """Expand __PLACEHOLDERS__ in a pak file name template."""
    now = datetime.now()
    device = str(cfg.get("device_name") or "device")
    device = re.sub(r"[^A-Za-z0-9_.-]+", "_", device).strip("._-") or "device"
    name = template
    name = name.replace("__PROJECT__", f"{cfg['project']:02d}")
    name = name.replace("__DEVICE__", device)
    name = name.replace("__DATE__", now.strftime("%Y-%m-%d"))
    name = name.replace("__DATETIME__", now.strftime("%Y-%m-%d_%H%M%S"))
    name = name.replace("__TIME__", now.strftime("%H%M%S"))
    return name


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

    if not _convert_samples(samples, sounds_dir, cfg):
        return 1

    out_name = _expand_pak_name(cfg["pak_file_name"], cfg)
    cfg["out"] = str(out_dir / out_name)

    summary = build(cfg, samples, sounds_dir)
    print(f"built {summary['out']}")
    print(f"  project P{summary['project']:02d}  samples {summary['samples']}")
    if summary["pads"]:
        print("  pads " + ", ".join(summary["pads"]))
    _cleanup_build_dir(sounds_dir)
    return 0


def _convert_samples(samples: list[Sample], sounds_dir: Path, cfg: dict) -> bool:
    """Convert each sample to the .pak format. Returns False on any error."""
    tool = cfg["audio_tool"]
    if tool == "sox":
        extra = cfg.get("sox_extra_args") or []
    else:
        extra = cfg.get("ffmpeg_extra_args") or []
    total = len(samples)
    for i, s in enumerate(samples, 1):
        if not s.src.is_file():
            print(f"sample file not found: {s.src} (slot {s.slot})",
                  file=sys.stderr)
            return False
        dst = sounds_dir / s.wav_name
        if _needs_conversion(s.src, dst):
            print(f"  [{i}/{total}] converting {s.src.name} -> {s.wav_name}")
            convert_wav(s.src, dst, tool=tool,
                        ffmpeg_bin=cfg["ffmpeg_bin"], sox_bin=cfg["sox_bin"],
                        extra_args=extra)
    return True


def _needs_conversion(src: Path, dst: Path) -> bool:
    return not dst.is_file() or src.stat().st_mtime > dst.stat().st_mtime


def _cleanup_build_dir(sounds_dir: Path) -> None:
    """Remove the temporary converted-audio working directory."""
    shutil.rmtree(sounds_dir, ignore_errors=True)
    try:
        sounds_dir.parent.rmdir()
    except OSError:
        pass


# --------------------------------------------------------------------------
# build-factory
# --------------------------------------------------------------------------

def cmd_build_factory(args: argparse.Namespace) -> int:
    device = normalize_device(args.device)
    cfg = load_config(args.config)

    meta = device_meta(device)  # the factory source (e.g. ep133)
    tag = (device_meta(args.as_device)
           if getattr(args, "as_device", None) else None)
    target = tag or meta  # where the pak will be loaded

    cfg["device_name"] = target["device_name"]
    cfg["device_sku"] = target["device_sku"]
    cfg["base_sku"] = target.get("base_sku", "")
    cfg["device_version"] = target.get("device_version", cfg["device_version"])
    cfg["pak_type"] = target.get("pak_type", meta.get("pak_type", cfg["pak_type"]))
    cfg["pak_release"] = target.get("pak_release", meta.get("pak_release", cfg["pak_release"]))
    _merge(cfg, args, "out_dir", "project", "device_version", "audio_tool",
           "ffmpeg_bin", "sox_bin")

    # The EP-40 (TE032AS006) uses 29-byte pad records (see docs/ep40-format.md).
    ep40 = target.get("device_sku") == "TE032AS006"

    print(f"building {meta['device_name']} factory pack "
          f"for {cfg['device_name']} ...")

    out_dir = Path(cfg["out_dir"]).expanduser()
    sounds_dir = out_dir / cfg["build_dir"] / "sounds"

    # Search dirs in order: the device's own default folder, then the main one
    # (the main folder is only a fallback for devices with a bundled list).
    dirs: list[Path] = []
    for key in (f"{device}_samples_dir", "samples_dir"):
        if key == "samples_dir" and not has_factory_list(device):
            continue
        val = cfg.get(key)
        if val:
            p = Path(str(val)).expanduser()
            if p.is_dir():
                dirs.append(p)

    print("  searching: " + ", ".join(str(d) for d in dirs))
    found, missing = find_samples(device, dirs)
    total = len(found) + len(missing)
    print(f"  matched {len(found)}/{total} factory samples")
    projects = load_factory_projects(device)
    if projects:
        print(f"  restoring {len(projects)} factory projects "
              f"(pads + patterns + scenes)")
    if missing:
        print(f"missing {len(missing)}/{total} factory samples:")
        for s in missing:
            print(f"  slot {s.slot:3d}  {s.name}")
        sys.stdout.flush()
    if not found:
        print(f"no factory samples found - set '{device}_samples_dir' in "
              "config.json to the folder holding the samples",
              file=sys.stderr)
        return 1
    if missing and args.strict:
        print("aborting: --strict and samples are missing", file=sys.stderr)
        return 1

    samples = [Sample(slot=s.slot, name=s.name, src=path)
               for s, path in found]

    if not _convert_samples(samples, sounds_dir, cfg):
        return 1

    if not projects and has_factory_programmes(device):
        projects = build_factory_projects(device, samples, sounds_dir, ep40)
        print(f"  assigning {len(projects)} factory programmes "
              f"(hand-assigned pads - real factory projects not bundled yet)")

    out = Path(args.out).expanduser() if args.out else \
        out_dir / _expand_pak_name(f"{device}-factory-__DATE__.pak", cfg)
    cfg["out"] = str(out)
    cfg["mode"] = "scratch"

    summary = build(cfg, samples, sounds_dir, project_tars=projects or None,
                    ep40=ep40)
    print(f"built {summary['out']}")
    print(f"  device {cfg['device_name']}  factory {meta['device_name']}  "
          f"project P{summary['project']:02d}  samples {summary['samples']}")
    if missing:
        print(f"  {len(missing)} factory samples not found and skipped")
    _cleanup_build_dir(sounds_dir)
    return 0


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


# --------------------------------------------------------------------------
# retag
# --------------------------------------------------------------------------

def cmd_retag(args: argparse.Namespace) -> int:
    """Rewrite an existing .pak's metadata so it loads on a different device.

    All entries are copied verbatim; only /meta.json's device identity is
    changed.
    """
    src = Path(args.file).expanduser()
    if not src.is_file():
        print(f"not a file: {src}", file=sys.stderr)
        return 1

    key = normalize_device(args.as_device)
    target = device_meta(key)

    out = (Path(args.out).expanduser() if args.out
           else src.with_name(f"{src.stem}-{key}.pak"))

    with zipfile.ZipFile(src, "r") as zin:
        names = zin.namelist()
        if "/meta.json" not in names:
            print("no /meta.json in the pak", file=sys.stderr)
            return 1
        meta = json.loads(zin.read("/meta.json"))
        orig = meta.get("device_name", "?")

        meta["device_name"] = target["device_name"]
        meta["device_sku"] = target["device_sku"]
        if target.get("base_sku"):
            meta["base_sku"] = target["base_sku"]
        else:
            meta.pop("base_sku", None)
        meta["device_version"] = target.get("device_version",
                                            meta.get("device_version", ""))
        if args.pak_type:
            meta["pak_type"] = args.pak_type
        if args.pak_release:
            meta["pak_release"] = args.pak_release

        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in names:
                if name == "/meta.json":
                    zout.writestr(name, json.dumps(meta, indent=2))
                else:
                    zout.writestr(name, zin.read(name))

    print(f"built {out}")
    print(f"  {orig} -> {target['device_name']} "
          f"(sku {target['device_sku']}, "
          f"version {meta.get('device_version', '?')})")
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
# scan + manifest (sample library -> manifest.txt)
# --------------------------------------------------------------------------

def _api_key(cfg: dict) -> str:
    return os.environ.get("DEEPSEEK_API_KEY") or cfg.get("deepseek_api_key") or ""


def _resolve_ai(flag: bool | None, cfg: dict) -> bool:
    """flag True/False forces AI on/off; None = auto (AI when a key exists)."""
    if flag is not None:
        return flag
    return bool(_api_key(cfg))


def _print_category_breakdown(samples) -> None:
    counts: dict[str, int] = {}
    for s in samples:
        counts[s.category] = counts.get(s.category, 0) + 1
    if not counts:
        return
    line = ", ".join(f"{c}:{n}" for c, n in
                     sorted(counts.items(), key=lambda kv: -kv[1]))
    print(f"  the machine hears -> {line}")


def cmd_scan(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    directory = (Path(args.dir).expanduser() if args.dir
                 else Path(cfg["library_dir"]).expanduser())
    if not directory.is_dir():
        print(f"sample directory not found: {directory}", file=sys.stderr)
        return 1

    use_ai = _resolve_ai(args.ai, cfg)
    if use_ai and not _api_key(cfg):
        print("no DeepSeek API key - falling back to filename heuristics",
              file=sys.stderr)
        use_ai = False

    index_path = Path(cfg["sample_index"]).expanduser()
    known = {s.file: s for s in (load_index(index_path) or [])}

    print(f"scanning {directory} ...")
    samples = scan_library(directory, use_ai, _api_key(cfg),
                           cfg["deepseek_model"], cfg["deepseek_base_url"],
                           known=known)
    save_index(index_path, directory, samples)
    print(f"indexed {len(samples)} samples -> {index_path}")
    _print_category_breakdown(samples)
    return 0


def _write_manifest(path: Path, rows: list[dict], guide: str, seed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"# auto-generated by ep-sampler manifest (guide={guide}, "
                 f"seed={seed})\n")
        for r in rows:
            fh.write("\t".join(str(r[k]) for k in
                               ("slot", "group", "pad", "bpm", "time_mode",
                                "playmode", "name", "file")) + "\n")


def _build_kits_pak(cfg: dict, kits: list[list[dict]]) -> int:
    """Convert every kit's samples and build one .pak with a project per kit."""
    samples_dir = Path(cfg["samples_dir"]).expanduser()
    all_samples: list[Sample] = []
    kit_samples: list[list[Sample]] = []
    slot = 1
    for kit in kits:
        cur: list[Sample] = []
        for r in kit:
            src = Path(r["file"])
            if not src.is_absolute():
                src = samples_dir / src
            bpm = r.get("bpm")
            bpm = float(bpm) if bpm not in (None, "", "-") else None
            cur.append(Sample(slot=slot, group=r["group"].lower(),
                              pad=r["pad"], bpm=bpm,
                              time_mode=r.get("time_mode", "off"),
                              playmode=r.get("playmode", "oneshot"),
                              name=r["name"], src=src))
            all_samples.append(cur[-1])
            slot += 1
        kit_samples.append(cur)

    out_dir = Path(cfg["out_dir"]).expanduser()
    sounds_dir = out_dir / cfg["build_dir"] / "sounds"
    if not _convert_samples(all_samples, sounds_dir, cfg):
        return 1

    cfg["out"] = str(out_dir / _expand_pak_name(cfg["pak_file_name"], cfg))
    cfg["mode"] = "scratch"

    summary = build(cfg, all_samples, sounds_dir, kits=kit_samples)
    print(f"built {summary['out']}")
    print(f"  programmes {len(kit_samples)}  samples {len(all_samples)}")
    _cleanup_build_dir(sounds_dir)
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if args.list_guides:
        _print_guides()
        return 0

    directory = Path(cfg["library_dir"]).expanduser()
    index_path = Path(cfg["sample_index"]).expanduser()

    samples = None if args.rescan else load_index(index_path)
    if samples is None:
        use_ai = _resolve_ai(args.ai, cfg)
        if use_ai and not _api_key(cfg):
            print("no DeepSeek API key - falling back to filename heuristics",
                  file=sys.stderr)
            use_ai = False
        print(f"scanning {directory} ...")
        samples = scan_library(directory, use_ai, _api_key(cfg),
                               cfg["deepseek_model"], cfg["deepseek_base_url"])
        save_index(index_path, directory, samples)
    if not samples:
        print(f"no samples found in {directory}", file=sys.stderr)
        return 1

    # Optional folder filter: keep only samples under the given folders
    # (relative to library_dir).
    folders = (list(args.folder) if args.folder
               else list(cfg.get("sample_folders") or []))
    folders = [f.strip("/") for f in folders if f and str(f).strip("/")]
    if folders:
        samples = [s for s in samples
                   if any(s.file == d or s.file.startswith(d + "/")
                          for d in folders)]
        if not samples:
            print(f"no samples found in folders: {', '.join(folders)}",
                  file=sys.stderr)
            return 1
        print(f"  filtering to {len(samples)} samples in {', '.join(folders)}")

    guide = args.guide
    if guide is None and args.randomize:
        guide = random.choice(GUIDES)["key"]
    guide = guide or GUIDES[0]["key"]

    if args.randomize:
        seed = args.seed if args.seed is not None \
            else random.SystemRandom().randint(0, 2**31 - 1)
    else:
        seed = args.seed if args.seed is not None else 0

    num = max(1, getattr(args, "programmes", 8) or 1)
    total = (args.samples if args.samples is not None
             else (cfg.get("total_samples") or 0))
    if total and total > 0:
        per_kit = min(48, (total + num - 1) // num)
        max_total = per_kit
    else:
        max_total = args.max
    kits = build_kits(samples, guide, seed=seed, count=num, max_total=max_total)

    out = (Path(args.out).expanduser() if args.out
           else Path(cfg["manifest_file"]).expanduser())
    _write_manifest(out, kits[0], guide, seed)
    print(f"built {out}  ({len(kits[0])} pads, guide {guide}, seed {seed})")
    groups: dict[str, int] = {}
    for r in kits[0]:
        groups[r["group"]] = groups.get(r["group"], 0) + 1
    print("  " + ", ".join(f"group {g}:{n}" for g, n in sorted(groups.items())))

    if num > 1:
        return _build_kits_pak(cfg, kits)
    return 0


def _print_guides() -> None:
    print("Manifest guides:")
    for i, g in enumerate(GUIDES, 1):
        print(f"  [{i}] {g['name']:<9} {g['essence']}")


def _prompt_guide() -> str | None:
    print("\nManifest guides (Enter = random):")
    for i, g in enumerate(GUIDES, 1):
        print(f"  [{i}] {g['name']:<9} {g['essence']}")
    while True:
        try:
            ans = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            raise
        if ans == "":
            return None
        if ans.isdigit() and 1 <= int(ans) <= len(GUIDES):
            return GUIDES[int(ans) - 1]["key"]
        for g in GUIDES:
            if ans == g["key"] or g["name"].lower().startswith(ans):
                return g["key"]
        print("  choose a number or guide name")


# --------------------------------------------------------------------------
# interactive menu
# --------------------------------------------------------------------------

def _prompt_choice(prompt: str, keys: list[str], labels: list[str],
                   default: str) -> str:
    """Prompt for one of `keys`, returning the chosen key (default on Enter)."""
    print(f"\n{prompt}")
    for i, (key, label) in enumerate(zip(keys, labels), 1):
        marker = " (default)" if key == default else ""
        print(f"  [{i}] {label}{marker}")
    while True:
        try:
            ans = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            raise
        if ans == "":
            return default
        if ans in keys:
            return ans
        if ans.isdigit() and 1 <= int(ans) <= len(keys):
            return keys[int(ans) - 1]
        for key, label in zip(keys, labels):
            if ans == label.lower() or label.lower().startswith(ans):
                return key
        print(f"  choose a number or one of: {', '.join(keys)}")


def cmd_menu(args: argparse.Namespace) -> int:
    """Interactive prompt-and-build flow (used when no subcommand is given)."""
    print(f"ep-sampler {__version__}")

    try:
        device = _prompt_choice(
            "Which EP device should we build a backup for?",
            list(DEVICE_ORDER), [DEVICE_LABELS[d] for d in DEVICE_ORDER],
            default="ep40")

        # The Ting is an FX mic - it takes a config.json, not a .pak.
        if device == "ep2350":
            rnd = _prompt_yesno("Randomise the FX presets?", default="n")
            styles = []
            if rnd == "y":
                styles = _prompt_fx_styles()
            fx = ",".join(str(s + 1) for s in styles) if styles else None
            ns = argparse.Namespace(
                config=args.config, name=None, randomize=(rnd == "y"),
                fx=fx, seed=None, samples=False, out=None, list_fx=False)
            return cmd_ting(ns)

        source = _prompt_choice(
            "What do you want to build?",
            ["manifest", "factory", "auto"],
            ["My manifest (manifest.txt)", "Factory sample folders",
             "Auto-build manifest from library"],
            default="manifest")
    except (EOFError, KeyboardInterrupt):
        print("\nno input - use a subcommand for non-interactive runs "
              "(e.g. 'ep-sampler build', 'ep-sampler build-factory ep133')")
        return 1

    if source == "auto":
        guide = _prompt_guide()
        rnd = _prompt_yesno("Randomise the selection?", default="y")
        ns = argparse.Namespace(
            config=args.config, list_guides=False, rescan=False, guide=guide,
            randomize=(rnd == "y"), seed=None, max=48, out=None, ai=None,
            programmes=8, samples=None, folder=None)
        return cmd_manifest(ns)

    if source == "factory":
        while device not in FACTORY_DEVICES:
            print(f"\n{device_label(device)} has no factory sample set here.")
            try:
                device = _prompt_choice(
                    "Which factory sample set?",
                    list(FACTORY_DEVICES),
                    [DEVICE_LABELS[d] for d in FACTORY_DEVICES],
                    default="ep133")
            except (EOFError, KeyboardInterrupt):
                print()
                return 1
        ns = argparse.Namespace(
            config=args.config, device=device, out_dir=None, out=None,
            project=None, device_version=None, audio_tool=None,
            ffmpeg_bin=None, sox_bin=None, strict=False, as_device=None)
        return cmd_build_factory(ns)

    # manifest source - set the target device identity for the build
    meta = device_meta(device)
    ns = argparse.Namespace(
        config=args.config, samples_dir=None, manifest_file=None, out_dir=None,
        project=None, mode=None, base_pak=None, device_name=meta["device_name"],
        device_sku=meta["device_sku"], base_sku=meta["base_sku"],
        device_version=None, pak_release=None, pak_type=None, author=None,
        audio_tool=None, ffmpeg_bin=None, sox_bin=None)
    return cmd_build(ns)


def _prompt_yesno(prompt: str, default: str = "n") -> str:
    while True:
        try:
            ans = input(f"\n{prompt} [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            raise
        if ans == "":
            return default
        if ans in ("y", "yes"):
            return "y"
        if ans in ("n", "no"):
            return "n"
        print("  answer y or n")


# --------------------------------------------------------------------------
# ting (EP-2350 FX mic config.json)
# --------------------------------------------------------------------------

def cmd_ting(args: argparse.Namespace) -> int:
    if args.list_fx:
        _print_fx_types()
        return 0

    cfg = load_config(args.config)
    out_dir = Path(cfg["out_dir"]).expanduser()
    out = Path(args.out).expanduser() if args.out else \
        out_dir / "ting" / "config.json"
    name = args.name or "TING PACK"

    styles = _parse_fx_styles(args.fx) if args.fx else []
    typed = bool(styles) or args.randomize
    if typed:
        data = typed_config(name, styles=styles, seed=args.seed)
    else:
        data = default_config(name)
    if args.samples:
        data["samples"] = sample_entries()

    write_config(data, out)
    print(f"built {out}")
    print(f"  presets {len(data['presets'])} "
          f"({'fx-types' if typed else 'factory-style'})")
    if "samples" in data:
        print(f"  samples {len(data['samples'])} (1.wav..4.wav, oneshot)")
    for p in data["presets"]:
        chain = " -> ".join(e["effect"] for e in p["list"])
        mods = [m for m in ("handle", "shake", "lfo", "trigger") if m in p]
        suffix = f"  [{' '.join(mods)}]" if mods else ""
        print(f"  slot {p['pos']}: {p.get('name', '')}  {chain}{suffix}")
    return 0


def _parse_fx_styles(spec: str) -> list[int]:
    """Parse '1,3,5,7' into 0-based type indices; validate 1..8."""
    styles: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
        except ValueError:
            raise ValueError(f"invalid FX style {part!r} (use numbers 1-8)")
        if not 1 <= n <= len(FX_TYPES):
            raise ValueError(f"FX style {n} out of range 1..{len(FX_TYPES)}")
        if n - 1 in styles:
            raise ValueError(f"duplicate FX style {n}")
        styles.append(n - 1)
    return styles


def _print_fx_types() -> None:
    print("FX styles:")
    for i, t in enumerate(FX_TYPES, 1):
        print(f"  [{i}] {t['name']:<8} {t['essence']}")


def _prompt_fx_styles() -> list[int]:
    print("\nFX styles (1-8, comma-separated, Enter = random 4):")
    for i, t in enumerate(FX_TYPES, 1):
        print(f"  [{i}] {t['name']:<8} {t['essence']}")
    while True:
        try:
            ans = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise
        if ans == "":
            return []
        try:
            return _parse_fx_styles(ans)
        except ValueError as exc:
            print(f"  {exc}")


# --------------------------------------------------------------------------
# argparse
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ep-sampler",
        description="Build a list of sample WAVs into an EP-133 .pak backup.")
    p.add_argument("--version", action="version",
                   version=f"ep-sampler {__version__}")
    p.add_argument("--config", type=Path, default=None,
                   help="path to config.json (default: ./config.json)")

    sub = p.add_subparsers(dest="command", required=False)

    b = sub.add_parser("build", help="convert samples and build the .pak")
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

    f = sub.add_parser(
        "build-factory",
        help="build a .pak from a device's factory sample set")
    f.add_argument("device", help="ep133 or ep1320")
    f.add_argument("--out-dir", default=None)
    f.add_argument("--out", default=None,
                   help="full output path (overrides the default file name)")
    f.add_argument("--project", type=int, default=None)
    f.add_argument("--device-version", default=None)
    f.add_argument("--audio-tool", choices=["ffmpeg", "sox"], default=None)
    f.add_argument("--ffmpeg-bin", default=None)
    f.add_argument("--sox-bin", default=None)
    f.add_argument("--strict", action="store_true",
                   help="fail if any factory sample is missing")
    f.add_argument("--as", dest="as_device", default=None,
                   help="tag the pak as a different device (e.g. --as ep40)")
    f.set_defaults(func=cmd_build_factory)

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

    i = sub.add_parser("inspect", help="list the contents of a .pak")
    i.add_argument("file")
    i.set_defaults(func=cmd_inspect)

    r = sub.add_parser("retag",
                       help="re-tag an existing .pak for a different device")
    r.add_argument("file")
    r.add_argument("--as", dest="as_device", required=True,
                   help="target device (e.g. ep40)")
    r.add_argument("--out", default=None,
                   help="output path (default: <name>-<device>.pak)")
    r.add_argument("--pak-type", default=None,
                   help="override the pak type (default: keep source's)")
    r.add_argument("--pak-release", default=None,
                   help="override the pak release (default: keep source's)")
    r.set_defaults(func=cmd_retag)

    t = sub.add_parser(
        "ting", help="build an EP-2350 Ting config.json (FX mic)")
    t.add_argument("--name", default=None, help="pack name (default: TING PACK)")
    t.add_argument("--fx", default=None, metavar="1,2,3,4",
                   help="FX styles 1-8 to use (comma-separated); remaining "
                        "slots are filled with random styles")
    t.add_argument("--randomize", action="store_true",
                   help="pick 4 random FX styles (or use --fx to choose)")
    t.add_argument("--list-fx", action="store_true",
                   help="list the 8 FX styles and exit")
    t.add_argument("--seed", type=int, default=None,
                   help="random seed for reproducible randomisation")
    t.add_argument("--samples", action="store_true",
                   help="include a samples section (1.wav..4.wav, oneshot)")
    t.add_argument("--out", default=None,
                   help="output path (default: out/ting/config.json)")
    t.set_defaults(func=cmd_ting)

    s = sub.add_parser("scan", help="scan the sample library and cache the index")
    s.add_argument("--dir", default=None,
                   help="sample directory (default: library_dir)")
    s.add_argument("--ai", dest="ai", action="store_true", default=None,
                   help="classify with DeepSeek")
    s.add_argument("--no-ai", dest="ai", action="store_false",
                   help="classify with filename heuristics")
    s.set_defaults(func=cmd_scan)

    m = sub.add_parser("manifest",
                       help="build manifest.txt from the sample library")
    m.add_argument("--guide", default=None, help="guide key (see --list-guides)")
    m.add_argument("--randomize", action="store_true",
                   help="randomise selection (and guide if none given)")
    m.add_argument("--seed", type=int, default=None,
                   help="random seed for reproducible builds")
    m.add_argument("--max", type=int, default=48,
                   help="max pads to fill per programme (default 48)")
    m.add_argument("--samples", type=int, default=None,
                   help="total samples to load, split evenly across programmes")
    m.add_argument("--folder", action="append", default=None,
                   help="only use samples under this folder, relative to "
                        "library_dir (repeatable)")
    m.add_argument("--rescan", action="store_true",
                   help="rescan the library instead of using the cached index")
    m.add_argument("--out", default=None,
                   help="output manifest path (default: manifest_file)")
    m.add_argument("--list-guides", action="store_true",
                   help="list the manifest guides and exit")
    m.add_argument("--programmes", type=int, default=8,
                   help="number of programmes/kits to build "
                        "(1 = write manifest.txt only)")
    m.add_argument("--ai", dest="ai", action="store_true", default=None)
    m.add_argument("--no-ai", dest="ai", action="store_false")
    m.set_defaults(func=cmd_manifest)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command is None:
            return cmd_menu(args)
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
