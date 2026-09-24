#!/usr/bin/env python3
"""Assemble the .pak archive - the backup file the EP Sample Tool restores.

A .pak is a ZIP with (all entry paths carrying a leading "/"):

    /projects/PXX.tar   - one TAR holding a 26-byte record per pad
    /sounds/<n> name.wav- one 44.1 kHz stereo 16-bit WAV per sample slot
    /meta.json          - pak metadata

Two modes:
    scratch - build the archive from the documented format.
    base    - patch a real Sample Tool backup (its parser is strict, so this
              is the safest path). Only the bytes that change are modified.
"""

import io
import json
import os
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .pad_record import DEFAULT_BLANK_PAD, PAD_RECORD_SIZE, build_pad_record
from .manifest import Sample

TAR_BLOCK = 512


def timestamp_ms() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def build_meta(cfg: dict) -> bytes:
    meta = {
        "info": "teenage engineering - pak file",
        "pak_version": 1,
        "pak_type": cfg["pak_type"],
        "pak_release": cfg["pak_release"],
        "device_name": cfg["device_name"],
        "device_sku": cfg["device_sku"],
        "device_version": cfg["device_version"],
        "generated_at": timestamp_ms(),
        "author": cfg["author"],
    }
    if cfg.get("base_sku"):
        meta["base_sku"] = cfg["base_sku"]
    return json.dumps(meta, indent=2).encode("utf-8")


def _records_for(samples: list[Sample], sounds_dir: Path) -> dict[tuple[str, int], bytes]:
    """Return {(group, pad): 26-byte record} for every sample with a pad
    binding. Samples without a pad (e.g. factory sounds) are skipped."""
    records: dict[tuple[str, int], bytes] = {}
    for s in samples:
        if s.group is None or s.pad is None:
            continue
        frames = _wav_frames(sounds_dir / s.wav_name)
        records[(s.group, s.pad)] = build_pad_record(
            s.slot, frames, s.bpm, s.bpm_override, s.time_mode, s.playmode)
    return records


def _wav_frames(path: Path) -> int:
    import wave
    with wave.open(str(path), "rb") as w:
        return w.getnframes()


def build_project_tar(records: dict[tuple[str, int], bytes]) -> bytes:
    """Build a project TAR (ustar, all mtimes 0) with 48 pad records."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        def add_dir(name: str) -> None:
            ti = tarfile.TarInfo(name)
            ti.type = tarfile.DIRTYPE
            ti.mode = 0o755
            ti.mtime = 0
            tf.addfile(ti)

        def add_file(name: str, data: bytes) -> None:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mode = 0o644
            ti.mtime = 0
            tf.addfile(ti, io.BytesIO(data))

        add_dir("pads")
        for group in "abcd":
            add_dir(f"pads/{group}")
            for pad in range(1, 13):
                add_file(f"pads/{group}/p{pad:02d}",
                         records.get((group, pad), DEFAULT_BLANK_PAD))
        add_dir("patterns")
    return buf.getvalue()


def find_pad_record_offsets(tar_bytes: bytes) -> dict[tuple[str, int], int]:
    """Scan a project TAR and return {(group, pad): data_offset}."""
    offsets: dict[tuple[str, int], int] = {}
    pos = 0
    while pos + TAR_BLOCK <= len(tar_bytes):
        header = tar_bytes[pos:pos + TAR_BLOCK]
        if header[:4] == b"\x00\x00\x00\x00":
            break
        name = header[:100].split(b"\x00")[0].decode("ascii", "replace")
        size_field = header[124:136].split(b"\x00")[0].strip() or b"0"
        try:
            size = int(size_field, 8)
        except ValueError:
            size = 0
        typeflag = header[156:157]
        if (typeflag in (b"0", b"\x00") and
                name.startswith("pads/") and len(name) == len("pads/x/pNN")):
            group = name[5:6]
            try:
                pad = int(name[8:10])
            except ValueError:
                pad = 0
            if group in "abcd" and 1 <= pad <= 12:
                offsets[(group, pad)] = pos + TAR_BLOCK
        pos += TAR_BLOCK + ((size + TAR_BLOCK - 1) // TAR_BLOCK) * TAR_BLOCK
    return offsets


def patch_tar(tar_bytes: bytes, records: dict[tuple[str, int], bytes]) -> bytes:
    """Reset every pad to blank, then apply the bindings in `records`."""
    out = bytearray(tar_bytes)
    for key, off in find_pad_record_offsets(tar_bytes).items():
        out[off:off + PAD_RECORD_SIZE] = records.get(key, DEFAULT_BLANK_PAD)
    return bytes(out)


def _zip_info(name: str, now: datetime) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(name, date_time=(now.year, now.month, now.day,
                                          now.hour, now.minute, now.second))
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    zi.create_system = 3
    return zi


def build_scratch(cfg: dict, samples: list[Sample], sounds_dir: Path,
                  project_tars: dict[str, bytes] | None = None) -> None:
    meta_bytes = build_meta(cfg)
    now = datetime.now()
    project = cfg["project"]

    with zipfile.ZipFile(cfg["out"], "w", zipfile.ZIP_DEFLATED) as zf:
        # Entry order: projects -> sounds -> meta (matches Sample Tool).
        if project_tars:
            for name, data in project_tars.items():
                zf.writestr(_zip_info(f"/projects/{name}", now), data)
        else:
            records = _records_for(samples, sounds_dir)
            tar_bytes = build_project_tar(records)
            zf.writestr(_zip_info(f"/projects/P{project:02d}.tar", now), tar_bytes)
        for s in sorted(samples, key=lambda x: x.slot):
            zf.writestr(_zip_info(f"/sounds/{s.wav_name}", now),
                        (sounds_dir / s.wav_name).read_bytes())
        zf.writestr(_zip_info("/meta.json", now), meta_bytes)


def build_base(cfg: dict, samples: list[Sample], sounds_dir: Path) -> None:
    base = cfg["base"]
    if not os.path.isfile(base):
        raise SystemExit(f"base pak not found: {base}")

    records = _records_for(samples, sounds_dir)
    meta_bytes = build_meta(cfg)
    now = datetime.now()
    project_name = f"/projects/P{cfg['project']:02d}.tar"

    with zipfile.ZipFile(base, "r") as bz:
        names = bz.namelist()
        project_entries = [n for n in names if "/projects/" in n and n.endswith(".tar")]
        if not project_entries:
            raise SystemExit(f"base pak has no /projects/*.tar entry: {base}")
        project_tar_name = (project_name if project_name in names
                            else project_entries[0])

        patched_tar = patch_tar(bz.read(project_tar_name), records)

        new_sounds = {f"/sounds/{s.wav_name}": (sounds_dir / s.wav_name).read_bytes()
                      for s in samples}

        with zipfile.ZipFile(cfg["out"], "w", zipfile.ZIP_DEFLATED) as out:
            out.writestr(_zip_info(project_tar_name, now), patched_tar)
            for arcname in sorted(new_sounds):
                out.writestr(_zip_info(arcname, now), new_sounds[arcname])
            out.writestr(_zip_info("/meta.json", now), meta_bytes)
            for name in names:
                if name == project_tar_name or name.startswith("/sounds/") or name == "/meta.json":
                    continue
                out.writestr(_zip_info(name, now), bz.read(name))


def build(cfg: dict, samples: list[Sample], sounds_dir: Path,
          project_tars: dict[str, bytes] | None = None) -> dict[str, object]:
    """Build the .pak. Returns a small summary dict."""
    os.makedirs(os.path.dirname(os.path.abspath(cfg["out"])), exist_ok=True)
    if cfg["mode"] == "base":
        build_base(cfg, samples, sounds_dir)
    else:
        build_scratch(cfg, samples, sounds_dir, project_tars)
    return {
        "out": cfg["out"],
        "project": cfg["project"],
        "samples": len(samples),
        "pads": sorted(f"{s.group.upper()}-{s.pad}"
                      for s in samples if s.group is not None and s.pad is not None),
    }
