#!/usr/bin/env python3
"""The sample manifest - one line per sample, TAB-separated columns:

    slot  group  pad  bpm  time_mode  playmode  name  file

`file` is relative to SAMPLES_DIR unless it starts with "/".
"""

from dataclasses import dataclass
from pathlib import Path

GROUPS = "abcd"
PLAYMODES = {"oneshot", "key", "legato"}
TIME_MODES = {"off", "bpm", "bar"}


@dataclass
class Sample:
    slot: int
    group: str | None = None     # lowercase "a".."d"; None = no pad binding
    pad: int | None = None       # 1..12, TAR "pNN" convention (bottom-up)
    bpm: float | None = None
    bpm_override: bool = False
    time_mode: str = "off"
    playmode: str = "oneshot"
    name: str = ""
    src: Path | None = None      # absolute path to the source WAV

    @property
    def wav_name(self) -> str:
        return f"{self.slot} {self.name}.wav"


def parse_manifest(path: Path, samples_dir: Path) -> list[Sample]:
    """Parse the manifest and validate it. Raises ValueError with a clear
    message on the first problem."""
    samples: list[Sample] = []
    slots: set[int] = set()
    pads: set[tuple[str, int]] = set()

    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue

            fields = line.split("\t")
            if len(fields) < 8:
                raise ValueError(
                    f"manifest line {lineno}: expected 8 TAB-separated columns, "
                    f"got {len(fields)}: {line!r}")
            slot_s, group, pad_s, bpm_s, time_mode, playmode, name, file = fields[:8]

            try:
                slot = int(slot_s)
            except ValueError:
                raise ValueError(f"manifest line {lineno}: slot {slot_s!r} is not a number")
            if not 1 <= slot <= 999:
                raise ValueError(f"manifest line {lineno}: slot {slot} out of range 1..999")

            group = group.strip().lower()
            if group not in GROUPS:
                raise ValueError(f"manifest line {lineno}: group {group!r} must be A/B/C/D")

            try:
                pad = int(pad_s)
            except ValueError:
                raise ValueError(f"manifest line {lineno}: pad {pad_s!r} is not a number")
            if not 1 <= pad <= 12:
                raise ValueError(f"manifest line {lineno}: pad {pad} out of range 1..12")

            bpm = None
            bpm_override = False
            bpm_s = bpm_s.strip()
            if bpm_s and bpm_s != "-":
                try:
                    bpm = float(bpm_s)
                except ValueError:
                    raise ValueError(f"manifest line {lineno}: bpm {bpm_s!r} is not a number")

            time_mode = time_mode.strip() or "off"
            if time_mode not in TIME_MODES:
                raise ValueError(
                    f"manifest line {lineno}: time_mode {time_mode!r} must be "
                    f"one of {sorted(TIME_MODES)}")
            playmode = playmode.strip() or "oneshot"
            if playmode not in PLAYMODES:
                raise ValueError(
                    f"manifest line {lineno}: playmode {playmode!r} must be "
                    f"one of {sorted(PLAYMODES)}")

            name = name.strip()
            if not name:
                raise ValueError(f"manifest line {lineno}: empty name")

            if slot in slots:
                raise ValueError(f"manifest: slot {slot} appears more than once")
            slots.add(slot)

            if (group, pad) in pads:
                raise ValueError(
                    f"manifest: pad {group.upper()}-{pad} assigned more than once")
            pads.add((group, pad))

            src = Path(file.strip())
            if not src.is_absolute():
                src = samples_dir / src

            samples.append(Sample(slot, group, pad, bpm, bpm_override,
                                  time_mode, playmode, name, src))

    if not samples:
        raise ValueError(f"manifest {path} contains no samples")
    return samples
