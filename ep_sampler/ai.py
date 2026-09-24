#!/usr/bin/env python3
"""DeepSeek chat client (OpenAI-compatible REST) for classifying sample files.

Only filenames are sent - never audio - so a whole library can be described in
a single cheap request. The model name is configurable; DeepSeek's API uses
model strings like "deepseek-chat" (a "flash"/fast/cheap variant, if DeepSeek
releases one, can be set via `deepseek_model`).
"""

import json
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

# The only categories the classifier may return.
CATEGORIES = ("kick", "snare", "clap", "hat", "perc", "tom",
              "bass", "chord", "melody", "vocal", "fx")

_PROMPT = (
    "You are classifying short sample audio files for a hardware sampler. "
    "For each file name, decide what the sound is.\n"
    "Categories (one of): kick, snare, clap, hat, perc, tom, bass, chord, "
    "melody, vocal, fx.\n"
    "Also give:\n"
    "- name: a clean display name (max 20 chars, keep spaces).\n"
    "- bpm: an approximate tempo as a number ONLY for obvious loop-type "
    "samples (chords, melodic loops); otherwise null.\n"
    "Return ONLY valid JSON, no commentary, shaped exactly like:\n"
    '{"samples":[{"file":"<exact file>","category":"kick","name":"Kick 01",'
    '"bpm":null}]}\n\nFiles:\n{files}'
)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t


def classify_filenames(files: list[str], api_key: str,
                       model: str = DEFAULT_MODEL,
                       base_url: str = DEFAULT_BASE_URL,
                       timeout: int = 120) -> dict[str, dict]:
    """Return {file: {"category", "name", "bpm"}} by asking DeepSeek."""
    if not api_key:
        raise ValueError("no DeepSeek API key set")

    file_list = "\n".join(f"{i + 1}. {f}" for i, f in enumerate(files))
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": _PROMPT.replace("{files}", file_list)},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"DeepSeek API error {exc.code}: {detail}") from exc

    content = body["choices"][0]["message"]["content"]
    data = json.loads(_strip_fences(content))
    samples = data.get("samples") if isinstance(data, dict) else data
    if not isinstance(samples, list):
        raise RuntimeError("unexpected DeepSeek response shape")

    result: dict[str, dict] = {}
    for item in samples:
        f = item.get("file")
        if not isinstance(f, str) or not f:
            continue
        cat = str(item.get("category", "fx")).strip().lower()
        if cat not in CATEGORIES:
            cat = "fx"
        bpm = item.get("bpm")
        if not isinstance(bpm, (int, float)):
            bpm = None
        name = str(item.get("name") or "").strip()[:20]
        result[f] = {"category": cat, "name": name, "bpm": bpm}
    return result
