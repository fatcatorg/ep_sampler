# ep-sampler

Build Teenage Engineering EP-series backup files from your own samples — no
official tool required to create them.

| Device | What ep-sampler does for it |
| --- | --- |
| **EP-133 K.O. II** | Build `.pak` backups from a sample list, or rebuild the factory sound set. |
| **EP-1320 Medieval** | Same — `.pak` backups and the factory sound set. |
| **EP-40 Riddim** | Build `.pak` backups from a sample list, or rebuild its factory set. |
| **EP-2350 Ting** | Generate `config.json` FX presets for the FX microphone. |

It also **auto-builds the sample list for you**: scan a folder of samples, work
out what they are (optionally with the DeepSeek API), and write `manifest.txt`
using one of 16 genre-based "full kit" guides.

## Requirements

- **Python 3.10+** — the tool uses only the standard library.
- **ffmpeg** (or **sox**) — used to convert samples to the format the EP
  accepts.
- Optional: a **DeepSeek API key** for AI sample classification (see below).

```bash
ffmpeg -version      # verify ffmpeg is installed
```

## Install

```bash
# optional, but gives you the shorter `ep-sampler` command:
pip install -e .

# otherwise run the package directly from the repo:
python -m ep_sampler --help
```

## Quick start

**1. Build a backup from your samples.** Put WAVs in `samples/`, list them in
`manifest.txt`, then:

```bash
python -m ep_sampler build          # or: ep-sampler build
```

The result is `out/project-01.pak`. In the official **EP Sample Tool**, use
**Load** / **Upload** and point it at that file.

**2. Rebuild a device's factory sound set** (EP-133 / EP-1320) from your own
copies of the samples:

```bash
ep-sampler build-factory ep133
ep-sampler build-factory ep1320
```

**3. Generate FX presets for the Ting microphone:**

```bash
ep-sampler ting --randomise
```

## Interactive menu

Run `ep-sampler` with no arguments and it walks you through the choices:

```text
$ ep-sampler

Which EP device should we build a backup for?
  [1] EP-40 Riddim (default)
  [2] EP-133
  [3] EP-1320
  [4] EP-2350 Ting
> 

What do you want to build?
  [1] My manifest (manifest.txt) (default)
  [2] Factory sample folders
  [3] Auto-build manifest from library
>
```

- The device defaults to **EP-40 Riddim** (just press Enter).
- **My manifest** builds `manifest.txt` for the chosen device.
- **Factory sample folders** builds the EP-133 / EP-1320 factory set, or the
  EP-40 set from its slot-numbered sample files.
- **Auto-build manifest** scans your sample folder and writes `manifest.txt`
  for you.
- Choosing **EP-2350 Ting** skips to its FX-config builder.

Everything the menu does can also be run non-interactively with the subcommands
below (so it can be scripted).

## Commands

| Command | What it does |
| --- | --- |
| `ep-sampler build` | Convert `manifest.txt`'s samples and build the `.pak`. |
| `ep-sampler build-factory ep133` | Build a `.pak` from the EP-133/EP-1320 factory sample set. |
| `ep-sampler scan` | Scan the sample library and cache what it finds. |
| `ep-sampler manifest` | Auto-build a backup from the library — 8 programmes by default (see below). |
| `ep-sampler ting` | Build an EP-2350 Ting `config.json`. |
| `ep-sampler add <file.wav>` | Append one sample to `manifest.txt`. |
| `ep-sampler inspect <file.pak>` | List a `.pak`'s metadata, sounds and pads. |
| `ep-sampler retag <file.pak> --as <device>` | Re-tag an existing `.pak`'s device identity. |

Add `--help` to any command for its full options (for example
`ep-sampler manifest --help`). Note that `--config <path>` goes **before** the
subcommand: `ep-sampler --config config.json build`.

## The manifest file

`manifest.txt` is one sample per line, columns separated by **TAB** (`#` starts
a comment):

```
slot  group  pad  bpm  time_mode  playmode  name  file
```

| Column | Meaning |
| --- | --- |
| `slot` | Sample slot `1..999` (each must be unique). |
| `group` | Pad group `A`, `B`, `C` or `D`. |
| `pad` | Pad `1..12` — see the pad-numbering table below. |
| `bpm` | Optional tempo for time-stretch (`-` or blank = default). |
| `time_mode` | `off`, `bar` or `bpm`. |
| `playmode` | `oneshot`, `key` or `legato`. |
| `name` | Display name (becomes `<padded-slot> <name>.wav`, e.g. `001 Kick.wav`). |
| `file` | Path to the WAV, relative to `samples_dir` (or absolute). |

Example:

```
100	A	10	120	off	oneshot	Kick	kick.wav
101	A	11	134	bpm	oneshot	Snare	snare.wav
```

### Pad numbering

This project uses the **TAR** convention (bottom-up), matching the files inside
the backup:

| pad | label | pad | label | pad | label | pad | label |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `.` | 4 | `1` | 7 | `4` | 10 | `7` |
| 2 | `0` | 5 | `2` | 8 | `5` | 11 | `8` |
| 3 | `ENT` | 6 | `3` | 9 | `6` | 12 | `9` |

## Configuration

All settings live in `config.json` (every key is optional and falls back to a
built-in default). Values can also be overridden on the command line.

| Key | Meaning |
| --- | --- |
| `samples_dir` | Main folder of input sample WAVs. |
| `ep133_samples_dir` | Folder holding the EP-133 default/factory samples. |
| `ep1320_samples_dir` | Folder holding the EP-1320 default/factory samples. |
| `ep40_samples_dir` | Folder holding the EP-40 default/factory samples. |
| `library_dir` | Sample folder that `scan` / `manifest` index. |
| `sample_index` | Flat-file cache of the scan (JSON). |
| `deepseek_api_key` | DeepSeek API key (or set `DEEPSEEK_API_KEY`). |
| `deepseek_model` | DeepSeek model name (default `deepseek-chat`). |
| `deepseek_base_url` | DeepSeek API endpoint. |
| `manifest_file` | The sample list. |
| `out_dir` | Where output files go. |
| `pak_file_name` | Output `.pak` name template; supports `__PROJECT__`, `__DEVICE__`, `__DATE__` (`YYYY-MM-DD`), `__TIME__` (`HHMMSS`), `__DATETIME__`. |
| `project` | Which project (1..99) the backup carries. |
| `mode` | `scratch` (build from the format) or `base` (patch a real backup). |
| `base_pak` | A real Sample Tool backup, used when `mode = "base"`. |
| `device_sku` / `base_sku` | `TE032AS001` for EP-133 / EP-1320, `TE032AS006` for EP-40. |
| `device_version` | Your device's OS version (shown in Sample Tool). |
| `audio_tool` | `ffmpeg` or `sox`. |
| `ffmpeg_extra_args` | Extra converter args, e.g. `["-af", "loudnorm"]`. |

## Auto-building the manifest

Instead of hand-writing `manifest.txt`, scan a folder of samples and let the
tool generate it:

```bash
ep-sampler scan                     # scan library_dir and cache the result
ep-sampler manifest --guide techno  # build a .pak (8 programmes by default)
ep-sampler manifest --programmes 1  # write manifest.txt only
ep-sampler manifest --rescan        # rescan first, then build
ep-sampler manifest --samples 384   # ~384 samples, split evenly across 8 kits
ep-sampler manifest --folder Drums --folder Bass   # only use these sub-folders
```

- `scan` walks `library_dir` recursively, classifies every file, and writes a
  flat JSON index to `sample_index` (no database). Re-running `scan` only
  classifies new files - everything already indexed is reused.
- `manifest` reads that index by default, writes `manifest.txt` (the first
  kit, for reference) and builds a `.pak` with **8 programmes** — each a full
  kit: drums on group A, bass on B, chords/melody on C, vocals/fx on D, with a
  different random selection per programme. Pass `--programmes 1` to write
  only `manifest.txt`, or `--programmes N` for a different count.
- `--samples N` sets the total number of samples to load, split evenly across
  the programmes (each programme fills up to 48 pads).
- `--folder NAME` (repeatable) restricts the selection to samples under the
  given sub-folders of `library_dir`.

### Sample classification (DeepSeek)

Classification uses the **DeepSeek API** when a key is present, and falls back
to filename keywords otherwise. Only filenames are sent to the API — never
audio.

```bash
export DEEPSEEK_API_KEY=sk-...
ep-sampler scan --ai      # force DeepSeek classification
ep-sampler scan --no-ai   # force filename keywords
```

### The 16 guides

A guide is a **genre-based full kit** — every one pulls drums, bass, melodic
and fx/vocals, just weighted toward its genre. Randomisation picks *which*
samples, while the output stays sensibly ordered (drums first, then bass, then
chords/melody, then vocals/fx).

| # | Guide | # | Guide |
| --- | --- | --- | --- |
| 1 | HOUSE | 9 | REGGAE |
| 2 | TECHNO | 10 | FUNK |
| 3 | DUB | 11 | SOUL |
| 4 | HIP-HOP | 12 | UK GARAGE |
| 5 | HYPERPOP | 13 | JUNGLE |
| 6 | D&B | 14 | BREAKS |
| 7 | LO-FI | 15 | SYNTHWAVE |
| 8 | AMBIENT | 16 | CHAOS |

```bash
ep-sampler manifest --guide techno --randomize --seed 7
ep-sampler manifest --randomize       # random guide + random selection
ep-sampler manifest --list-guides     # full list with descriptions
```

## Factory backups (EP-133 / EP-1320 / EP-40)

`build-factory` rebuilds the device's **factory sound set** from your own
copies of the samples. It knows the factory slot of every sample — 308 for the
EP-133, 220 for the EP-1320 — and puts each back in its original slot with the
right device identity.

```bash
ep-sampler build-factory ep133
ep-sampler build-factory ep1320
ep-sampler build-factory ep40        # discovers the set from slot-numbered files
```

The EP-133 / EP-1320 sets ship as bundled name/slot lists. The EP-40 has no
bundled list, so `build-factory ep40` derives the factory set from the
slot-numbered filenames in `ep40_samples_dir` (e.g. `025_kick sub.wav` → slot
25, name `KICK SUB`).

It finds each factory sample by its **slot number** in the filename first (e.g.
`025_kick sub.wav` → slot 25), falling back to a name match. It searches
anywhere under the configured folders, including sub-folders. Search order:

1. the device's own folder (`ep133_samples_dir` / `ep1320_samples_dir` /
   `ep40_samples_dir`)
2. the main folder (`samples_dir`) — only for devices with a bundled list

Missing samples are listed and the build continues with the rest; pass
`--strict` to abort instead:

```bash
ep-sampler build-factory ep1320 --strict
```

Factory builds restore the sample library into the factory slots. Devices with
bundled project data (EP-133, EP-40) also restore the factory projects — pad
assignments, patterns, scenes and FX settings. The EP-1320 has no bundled
project data yet, so `build-factory ep1320` automatically assigns hand-made
factory programmes instead — 5 programmes, 48 pads each, following the EP-40
group layout (drums on A, bass on B, chords/melody on C, vocals/fx on D) —
until the real assignments are found. The assignments live in
`ep_sampler/factory_programmes.py`; edit the `FACTORY_PROGRAMMES` table and
rebuild to retune.

### Re-tagging a factory pak (preferred)

The closest way to put a device back to factory — even a different model — is
to start from a **real factory-content pak** and `retag` it, rather than build
one from scratch. `retag` rewrites the pak's device identity in `meta.json`
(`device_name`, `device_sku`, `base_sku`, `device_version`) and copies every
other entry byte-for-byte, so a factory pak built for one device loads on
another:

```bash
ep-sampler retag /path/to/factory-content.pak --as ep40
```

Output defaults to `<name>-<device>.pak` (override with `--out`). `--pak-type`
and `--pak-release` override the metadata fields rather than keeping the
source's values. This does **not** convert the samples or project data — it
only changes which device the pak claims to be, so use it between devices
whose slot layout you know to be compatible.

## Ting (EP-2350 FX mic)

The Ting is a handheld FX microphone, not a sampler. It mounts a tiny disk and
reads a single `config.json` defining the four FX buttons as effect chains plus
optional handle / shake / lfo / trigger modulation.

```bash
ep-sampler ting                       # factory-style presets (ECHO/SPRING/PIXIE/ROBOT)
ep-sampler ting --randomise          # 4 random FX styles
ep-sampler ting --fx 1,3,5,7          # pick specific styles, rest filled randomly
ep-sampler ting --samples             # include a samples section (1.wav..4.wav)
ep-sampler ting --list-fx             # list the styles
```

### The 8 FX styles

Each style is a fixed effect chain (its character) with every parameter
randomised inside its own ranges — the FX is always pushed in its direction,
but each pack is different:

| # | Style | Essence |
| --- | --- | --- |
| 1 | ECHO | dub tape echo — repeats, feedback, space |
| 2 | SPRING | spring reverb — boingy metallic space |
| 3 | PIXIE | pitch-up harmony — chipmunk pixie voice |
| 4 | ROBOT | ring modulation — metallic robotic voice |
| 5 | GRIT | distortion / fuzz — drive and saturation |
| 6 | WOBBLE | filter wobble — tremolo / wub-wub |
| 7 | RADIO | broken radio — bandpassed lo-fi static |
| 8 | GLITCH | glitch / stutter — atonal chaos |

Output goes to `out/ting/config.json` (override with `--out`), plus a
timestamped `config.json.<timestamp>` copy so every pack is kept; copy the main
file onto the `tingdisk` volume and restart the mic.

## Build modes

- **`scratch`** (default) builds the `.pak` entirely from the documented
  format. Self-contained, but the Sample Tool parser is strict — **verify the
  result on your device** before relying on it.
- **`base`** starts from a real `.pak` you export once from the Sample Tool,
  patches only the bytes that need to change, and re-zips. This is the most
  compatibility-safe path. Set `"mode": "base"` and
  `"base_pak": "/path/to/backup.pak"` in `config.json`.

Either way, check free space on the device first — a restore that doesn't fit
fails with `ERR SYSTEM_MODEL`.

## Notes

- The `.pak` format was reverse-engineered by the community, primarily in
  [`ZacharySBrown/ep133-ppak`](https://github.com/ZacharySBrown/ep133-ppak)
  (its `PROTOCOL.md` is the reference), building on `phones24`'s parser,
  `ep133-krate` and `garrettjwilke`'s SysEx work. Not affiliated with Teenage
  Engineering.
- The EP-40 (TE032AS006) uses **29-byte** pad records, not the EP-133's
  26-byte form. `build-factory … --as ep40` emits the EP-40-sized records, but
  the 3-byte pad tail is still unverified — see `docs/ep40-format.md` for the
  full reverse-engineering notes and test on hardware.
- The factory sample lists (`ep_sampler/data/*.txt`) are name/slot lists only —
  no audio is bundled. Sources: [`codejunkee1/ep133-sounds`](https://github.com/codejunkee1/ep133-sounds)
  (EP-133) and [`jpopesculian/ep1320`](https://github.com/jpopesculian/ep1320)
  (EP-1320).

## License

MIT. Provided as-is; restoring a malformed `.pak` can wipe or corrupt a
device's sample memory, so always keep a real Sample Tool backup first.
