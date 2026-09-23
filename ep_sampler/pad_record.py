#!/usr/bin/env python3
"""26-byte pad records - the binary file inside a project TAR that binds a
sample slot to a physical pad, with per-pad BPM / time-mode / play mode.

Format is community reverse-engineering (see README). A pad record is 26 bytes:

    offset 1      sample slot (u8, 0 = no sample)
    offset 8..11  sample length in frames (u32 LE)
    offset 12..15 BPM float32 LE (default 120.0), or override encoding at 13..15
    offset 16     volume (u8, 100)
    offset 20     envelope.release (u8, 255)
    offset 21     time.mode (0 off, 1 bpm, 2 bar)
    offset 23     playmode (0 oneshot, 1 key, 2 legato)
    offset 24     root note (u8, 60)
"""

import struct

PAD_RECORD_SIZE = 26

# A default, empty pad record verbatim from a real factory backup.
DEFAULT_BLANK_PAD = bytes([
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0, 0x42,  # 120.0 float32
    0x64,                                               # volume 100
    0x00, 0x00, 0x00,
    0xff,                                               # release 255
    0x00, 0x00,
    0x00,                                               # playmode oneshot
    0x3c,                                               # root note 60
    0x00,
])
assert len(DEFAULT_BLANK_PAD) == PAD_RECORD_SIZE

PLAYMODES = {"oneshot": 0, "key": 1, "legato": 2}
TIME_MODES = {"off": 0, "bpm": 1, "bar": 2}
# playmode must be written together with a matched envelope.release.
RELEASE_BY_PLAYMODE = {"oneshot": 255, "key": 15, "legato": 15}


def build_pad_record(slot, length_frames, bpm=None, bpm_override=False,
                     time_mode="off", playmode="oneshot"):
    """Return the 26-byte record for one pad bound to `slot`."""
    rec = bytearray(DEFAULT_BLANK_PAD)
    rec[1] = slot & 0xFF
    rec[8:12] = struct.pack("<I", length_frames)

    if bpm is not None:
        if bpm_override:
            b = int(round(bpm))
            rec[12] = 0
            rec[13] = 0x80
            if b < 128:
                rec[14] = (b * 2) & 0xFF
                rec[15] = 0x00
            else:
                rec[14] = b & 0xFF
                rec[15] = 0x80
        else:
            rec[12:16] = struct.pack("<f", float(bpm))

    rec[21] = TIME_MODES.get(time_mode, 0)
    rec[23] = PLAYMODES.get(playmode, 0)
    rec[20] = RELEASE_BY_PLAYMODE.get(playmode, 255)
    return bytes(rec)
