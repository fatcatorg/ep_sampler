# EP-40 (TE032AS006) .pak project format — reverse-engineering notes

The EP-40 Riddim uses the same `.pak` (ZIP) and `meta.json` scheme as the
EP-133 K.O. II, but its project TARs and pad records are **not identical**.
These notes record what `ep_sampler` has reverse-engineered so far, separating
what is verified from what is still unknown. They are the EP-40 counterpart to
[`ZacharySBrown/ep133-ppak`](https://github.com/ZacharySBrown/ep133-ppak)'s
`PROTOCOL.md` (which covers the EP-133).

> Sources: the bundled EP-40 factory projects in `ep_sampler/data/projects/ep40/`
> (`P01`–`P09.tar`), the real factory-content pak
> `ep-40-factory-content-C42FyxWp.pak`, and the sample files in the user's
> `EP-40_defaults` folder (slot-prefixed filenames).

---

## 1. Slot layout (factory sound set)

The EP-40 factory set lives in slot ranges, each a sub-folder of `EP-40_defaults`:

| Range | Folder | Role |
| --- | --- | --- |
| 001–055 | KICKS | drums |
| 100–164 | SNARES | drums |
| 200–244 | CYMBALS | drums |
| 300–375 | PERCUSSION | drums |
| 400–417 | BASS | bass |
| 500–528 | LEADS | melody |
| 600–628 | SKANKS | chords |
| 700–754 | VOX FX | vocals / fx |
| 800–898 | LOOPS | loops |

These map onto the EP-40 pad groups as: **A = drums, B = bass, C = chords/melody
(skanks + leads), D = vocals/fx**. `ep_sampler/manifest_build.py`'s `GROUP_OF`
table already mirrors this.

---

## 2. Pad record — 29 bytes

Every `pads/{a|b|c|d}/p{NN}` file in an EP-40 project TAR is **29 bytes**.
(The EP-133's is 26 bytes.) The first 26 bytes are the **same layout** as the
EP-133 record; the EP-40 appends a **3-byte tail**.

### 2.1 Bytes 0–25 (same as EP-133, verified)

| Offset | Field | Notes |
| --- | --- | --- |
| 0 | zero | always `0x00` |
| 1–2 | sample slot, u16 LE | confirmed: slot 405 → `95 01` |
| 3–7 | zero | `0x00 × 5` (see §5 for empty pads) |
| 8–11 | sample length in frames, u32 LE | matches the 44.1 kHz WAV frame count |
| 12–15 | BPM, float32 LE | e.g. 85.0 → `00 00 aa 42` |
| 16 | volume, u8 | e.g. 100 = `0x64` |
| 17 | pitch, i8 | e.g. `0xfd` = −3 semitones on a skank |
| 18 | pan, i8 | |
| 19 | attack, u8 | |
| 20 | envelope.release, u8 | `0xff` oneshot, `0x0f` key/legato |
| 21 | time.mode, u8 | 0 off, 1 bpm, 2 bar |
| 22 | choke group, u8 | |
| 23 | playmode, u8 | 0 oneshot, 1 key, 2 legato |
| 24 | root note, u8 | e.g. `0x3c` = 60 |
| 25 | zero | `0x00` |

(Offsets 17/18/19/22 are inherited from the community's EP-133 RE work and are
"likely" rather than diff-verified; 1–2, 8–11, 12–15, 16, 20, 21, 23, 24 are
the ones confirmed against the EP-40's own factory records.)

### 2.2 Bytes 26–28 — the tail (NOT decoded)

The 3 trailing bytes are the one part of the record that is **still unknown**.

What has been established:

- Byte 26 varies per *record* (often `0x00`, but seen as `0x2d`, `0x15`, `0x61`,
  `0x4f`, …).
- Bytes 27–28 (u16 LE) are **constant per sample slot** for populated pads —
  the same slot always carries the same `27..28` value across projects, even
  when byte 26 differs.
- The tail is **not** a CRC16 (xmodem/ccitt/arc/modbus/usb/maxim/kermit),
  CRC32, Adler-32, Fletcher-16, or byte-sum of the first 26 bytes, nor of the
  sample WAV's bytes. Its derivation is still unidentified.

Best guess: bytes 27–28 are a per-sample value the device computes at upload
time (an ID or hash) that can't be reproduced from the WAV alone.

`ep_sampler` currently emits `00 00 00` for the tail and treats it as
best-effort: this is the one place a scratch-built EP-40 project may still be
rejected by the device, so **validate on hardware**.

### 2.3 Empty pads

Unassigned EP-40 pads are **not** all-zero. They point at sentinel slots
`1004`–`1009` with:

- bytes 3–12 = `0xff` (9 bytes)
- length (8–11) = `0xffffffff`
- release = `0x00`, playmode = `0x02`, root = `0x3c`

The exact sentinel slot varies per group/project and is not fully mapped.
`ep_sampler` instead writes its 29-byte blank (`DEFAULT_BLANK_PAD_EP40`,
slot 0) for unassigned pads; slot 0 is the EP-133 convention and is accepted
by the device family.

---

## 3. Project TAR structure

| Entry | P01–P08 | P09 |
| --- | --- | --- |
| `live` | 48 bytes | — |
| `fx_settings` | — | present |
| `pads/a..d/p01..p12` | 29 bytes each | 29 bytes each |
| `patterns/` | empty dir | `patterns/a01..a03, b01..b03, c03` |
| `scenes` | — | present |
| `settings` | 222 bytes | 222 bytes |

`ep_sampler`'s EP-40 projects currently emit `pads/` (29-byte records) + an
empty `patterns/` — enough for pad assignments, which is all the hand-assigned
programmes use. The remaining files are documented below for future work.

---

## 4. `settings` — 222 bytes

Layout (matches `ep133-ppak`'s `DEVICE_DEFAULT_SETTINGS` finding, with an
EP-40-specific trailer):

- bytes 0–3: zero
- bytes 4–7: project BPM, float32 LE (e.g. 85.0 → `00 00 aa 42`)
- bytes 8–23: zero
- bytes 24–215: 48 × float32 LE — one per pad. `-1.0` (`00 00 80 bf`) means
  "no override"; populated pads carry real values.
- bytes 216–221: 6-byte trailer. EP-133's device default is `00 00 00 00 00 02`;
  the EP-40's real trailers differ (P01: `00 00 05 00 00 02`,
  P09: `05 00 05 05 00 01`) — not decoded.

All-zero settings cause `ERR PATTERN` on scene transitions on the EP-133, so
the `-1.0` defaults matter; the EP-40 trailer remains unknown.

---

## 5. `live` — 48 bytes

Captured verbatim from P01; mostly zero with a handful of `0x01` bytes. Not
decoded, not emitted by `ep_sampler`.

---

## 6. What `ep_sampler` implements

- `pad_record.build_pad_record_ep40()` — 29-byte record (26-byte verified
  layout + zero tail).
- `pad_record.DEFAULT_BLANK_PAD_EP40` — 29-byte blank.
- `pak.build_project_tar(..., ep40=True)` — 29-byte pads + empty `patterns/`.
- `cmd_build_factory` sets `ep40` when the target `device_sku` is
  `TE032AS006`, so `build-factory … --as ep40` (and the EP-1320 hand-assigned
  programmes) emit EP-40-sized pad records.

Still to do (unblocked by these notes, but not implemented):

1. Decode pad-record bytes 26–28 (per-slot value).
2. Decode the `settings` trailer and the `live` file.
3. Map the empty-pad sentinel slots (1004–1009).
4. Emit `patterns`/`scenes` for actual song data on the EP-40.
