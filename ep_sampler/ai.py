#!/usr/bin/env python3
"""DeepSeek chat client (OpenAI-compatible REST) for classifying sample files.

Only filenames are sent - never audio - so a whole library can be described in
a single cheap request. The model name is configurable; DeepSeek's API uses
model strings like "deepseek-chat" (a "flash"/fast/cheap variant, if DeepSeek
releases one, can be set via `deepseek_model`).
"""

import json
import time
import urllib.error
import urllib.request
from typing import Callable

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


# Keep a single request comfortably inside the model's context window. We
# bound both the number of files (the reply JSON is large too) and the input
# token estimate.
MAX_CHUNK_FILES = 5_000
MAX_CHUNK_TOKENS = 250_000

# Transient failures get a few retries before the batch is skipped.
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds, doubles each attempt


class DeepSeekError(RuntimeError):
    """A classification request failed.

    `retryable` is True for transient problems (rate limits, network blips,
    truncated/malformed replies) where retrying may help, and False for hard
    failures (bad request, auth) that would fail the same way again.
    """

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def _estimate_tokens(text: str) -> int:
    # Rough but conservative: ~3 chars per token for typical file paths.
    return len(text) // 3 + 1


def _chunk_files(files: list[str]) -> list[list[str]]:
    """Split `files` into batches that fit the model's context window."""
    chunks: list[list[str]] = []
    cur: list[str] = []
    cur_tokens = 0
    for f in files:
        tokens = _estimate_tokens(f) + 3  # the "N. " prefix + newline
        if cur and (len(cur) >= MAX_CHUNK_FILES or
                    cur_tokens + tokens > MAX_CHUNK_TOKENS):
            chunks.append(cur)
            cur = []
            cur_tokens = 0
        cur.append(f)
        cur_tokens += tokens
    if cur:
        chunks.append(cur)
    return chunks


def _request_classification(file_list: str, api_key: str, model: str,
                            base_url: str, timeout: int) -> dict[str, dict]:
    """Ask DeepSeek to classify one batch; return {file: {...}}.

    Raises DeepSeekError on failure; `retryable` is set for transient
    problems (rate limits, network errors, truncated/malformed replies).
    """
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": _PROMPT.replace("{files}", file_list)},
        ],
        "temperature": 0.2,
        # Disable chain-of-thought: thinking mode is on by default, and for
        # these huge JSON replies the reasoning can eat the output budget and
        # leave `content` empty ("bad JSON: line 1 column 1").
        "thinking": {"type": "disabled"},
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
        retryable = exc.code in (429, 500, 502, 503, 504)
        raise DeepSeekError(f"DeepSeek API error {exc.code}: {detail}",
                            retryable=retryable) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DeepSeekError(f"network error: {exc}", retryable=True) from exc
    except ValueError as exc:
        raise DeepSeekError(f"bad API response: {exc}", retryable=True) from exc

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekError(f"unexpected response shape: {exc}",
                            retryable=True) from exc
    if not isinstance(content, str):
        raise DeepSeekError("unexpected response shape (no text content)",
                            retryable=True)

    try:
        data = json.loads(_strip_fences(content))
    except ValueError as exc:
        raise DeepSeekError(f"deepseek replied with bad JSON: {exc}",
                            retryable=True) from exc

    samples = data.get("samples") if isinstance(data, dict) else data
    if not isinstance(samples, list):
        raise DeepSeekError("unexpected DeepSeek response shape",
                            retryable=True)

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


def _classify_with_retries(file_list: str, api_key: str, model: str,
                           base_url: str, timeout: int) -> dict[str, dict]:
    """Classify one batch, retrying transient failures with backoff."""
    delay = RETRY_BASE_DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _request_classification(file_list, api_key, model,
                                           base_url, timeout)
        except DeepSeekError as exc:
            if not exc.retryable or attempt == MAX_RETRIES:
                raise
            print(f"  ! deepseek hiccup - retrying {attempt}/{MAX_RETRIES - 1}")
            time.sleep(delay)
            delay *= 2
    raise DeepSeekError("classification failed", retryable=False)  # unreachable


def classify_filenames(files: list[str], api_key: str,
                       model: str = DEFAULT_MODEL,
                       base_url: str = DEFAULT_BASE_URL,
                       timeout: int = 300,
                       on_progress: Callable[[int, int], None] | None = None,
                       ) -> dict[str, dict]:
    """Return {file: {"category", "name", "bpm"}} by asking DeepSeek.

    Large libraries are sent in chunks so no single request exceeds the
    model's context window. A chunk that keeps failing is skipped (its files
    fall back to filename heuristics in the caller) instead of aborting the
    whole scan. `on_progress(done, total)` is called after each chunk.
    """
    if not api_key:
        raise ValueError("no DeepSeek API key set")

    result: dict[str, dict] = {}
    total = len(files)
    done = 0
    for chunk in _chunk_files(files):
        file_list = "\n".join(f"{i + 1}. {f}" for i, f in enumerate(chunk))
        try:
            result.update(_classify_with_retries(file_list, api_key, model,
                                                 base_url, timeout))
        except DeepSeekError as exc:
            msg = str(exc).split("\n")[0]
            if len(msg) > 120:
                msg = msg[:117] + "..."
            print(f"  ! skipped {len(chunk)} sounds ({msg})")
        done += len(chunk)
        if on_progress is not None:
            on_progress(done, total)
    return result
