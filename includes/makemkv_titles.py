# includes/makemkv_titles.py

from __future__ import annotations

import re
import sys
import subprocess
from typing import Dict, Any, List, Optional


# MakeMKV error signatures we treat as "disc is scratched/unreadable"
_DISC_ERROR_SUBSTRINGS = (
    "medium error",
    "uncorrectable error",
    "scsi error",
    "lec uncorrectable",
)

# Typical MakeMKV output patterns
# Example lines:
#   TINFO:0,9,0,"01:46:20"
#   TINFO:0,10,0,"4.3 GB"
#   TINFO:0,27,0,"00001.mpls"   (bluray playlists)
#   TINFO:0,2,0,"Main Title"
_TINFO_RE = re.compile(r"^TINFO:(\d+),(\d+),(\d+),\"(.*)\"$")

# Some builds also emit:
#   SINFO:0,0,0,"title"
_SINFO_RE = re.compile(r"^SINFO:(\d+),(\d+),(\d+),\"(.*)\"$")


def _parse_duration_to_seconds(s: str) -> Optional[int]:
    """
    Parse durations like:
      - "01:46:20"
      - "00:42:15"
      - sometimes "1:46:20" (rare)
    Returns seconds or None.
    """
    s = (s or "").strip()
    m = re.match(r"^(\d+):(\d{2}):(\d{2})$", s)
    if not m:
        return None
    h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return h * 3600 + mi * 60 + se


def _parse_size_to_bytes(s: str) -> Optional[int]:
    """
    Parse sizes like "4.3 GB", "812.0 MB", "12.5 GiB" etc.
    Returns bytes or None.
    """
    s = (s or "").strip()
    m = re.match(r"^([\d.]+)\s*([KMGTP]i?B)$", s, re.IGNORECASE)
    if not m:
        return None

    value = float(m.group(1))
    unit = m.group(2).upper()

    # SI vs IEC
    if unit.endswith("IB"):  # KiB/MiB/GiB...
        base = 1024.0
        unit = unit.replace("IB", "B")  # KIB -> KB for multiplier mapping
    else:
        base = 1000.0

    multipliers = {
        "KB": base ** 1,
        "MB": base ** 2,
        "GB": base ** 3,
        "TB": base ** 4,
        "PB": base ** 5,
    }
    mult = multipliers.get(unit)
    if not mult:
        return None

    return int(value * mult)


def _run_makemkv_info(make_mkv_path: str, disc_spec: str = "disc:0", timeout: int = 180) -> List[str]:
    """
    Runs:
      makemkvcon -r info disc:0
    Returns output lines.
    Aborts on disc read errors.
    """
    cmd = [make_mkv_path, "-r", "info", disc_spec]
    print("\n>>>", " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )

    lines: List[str] = []

    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="")
        lines.append(line.rstrip("\n"))

        low = line.lower()
        if any(sub in low for sub in _DISC_ERROR_SUBSTRINGS):
            print("\n❌ DISC READ ERROR DETECTED")
            print("💿 The disc appears to be scratched or unreadable.")
            print("🛑 Aborting before ripping/transcoding.")
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            sys.exit(1)

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("\n❌ MakeMKV info timed out.")
        sys.exit(1)

    if proc.returncode != 0:
        print("\n❌ MakeMKV info failed with a non-zero exit code.")
        sys.exit(1)

    return lines


def scan_titles_with_makemkv(make_mkv_path: str) -> List[Dict[str, Any]]:
    """
    Scan titles on the disc without ripping.

    Returns list of dicts like:
      [
        {
          "title_index": 0,
          "length": "01:46:20",
          "duration_seconds": 6380,
          "size": "4.3 GB",
          "size_bytes": 4300000000,
          "name": "Main Title",
          "source_file": "00001.mpls",
          "raw": { ... all collected TINFO fields ... }
        },
        ...
      ]

    You can store this directly in DB as JSON, or normalize further.
    """
    output_lines = _run_makemkv_info(make_mkv_path)

    # We will aggregate all TINFO values by title_index and "tinfo_id".
    # Also optionally keep SINFO if you want.
    titles_raw: Dict[int, Dict[str, Any]] = {}

    for line in output_lines:
        line = line.strip()
        if not line:
            continue

        m = _TINFO_RE.match(line)
        if m:
            title_index = int(m.group(1))
            tinfo_id = int(m.group(2))
            # m.group(3) is "type" / locale index (often 0)
            value = m.group(4)

            t = titles_raw.setdefault(title_index, {"tinfo": {}, "sinfo": {}})
            # keep the latest value; often fine
            t["tinfo"][tinfo_id] = value
            continue

        m = _SINFO_RE.match(line)
        if m:
            stream_index = int(m.group(1))
            sinfo_id = int(m.group(2))
            value = m.group(4)

            # Some discs emit SINFO for titles/streams; keep it anyway.
            # We store it per stream_index to not confuse with title_index.
            # If you don’t need it, you can remove SINFO parsing.
            t = titles_raw.setdefault(-1, {"tinfo": {}, "sinfo": {}})
            t["sinfo"].setdefault(stream_index, {})[sinfo_id] = value
            continue

    # Now map well-known TINFO keys into friendly fields.
    # These IDs are common in MakeMKV:
    #   2  = title name ("Main Title")
    #   9  = length ("01:46:20")
    #   10 = size ("4.3 GB")
    #   27 = source/playlist/file ("00001.mpls") (more Blu-ray)
    #
    # If some discs differ, you’ll still have raw["tinfo"] to inspect.
    results: List[Dict[str, Any]] = []

    for title_index, bucket in sorted(titles_raw.items(), key=lambda kv: kv[0]):
        if title_index < 0:
            continue  # skip the special SINFO bucket

        tinfo: Dict[int, str] = bucket.get("tinfo", {}) or {}

        name = tinfo.get(2) or None
        length = tinfo.get(9) or None
        size = tinfo.get(10) or None
        source_file = tinfo.get(27) or None

        duration_seconds = _parse_duration_to_seconds(length) if length else None
        size_bytes = _parse_size_to_bytes(size) if size else None

        results.append(
            {
                "title_index": title_index,
                "name": name,
                "length": length,
                "duration_seconds": duration_seconds,
                "size": size,
                "size_bytes": size_bytes,
                "source_file": source_file,
                "raw": {
                    "tinfo": tinfo,
                    # If you later want to capture more, keep this
                },
            }
        )

    return results