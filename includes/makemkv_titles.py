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
# TINFO: title_index, attribute_id, attribute_type, "value"
#   TINFO:0,9,0,"01:46:20"
#   TINFO:0,10,0,"4.3 GB"
#   TINFO:0,27,0,"00001.mpls"
#   TINFO:0,2,0,"Main Title"
_TINFO_RE = re.compile(r"^TINFO:(\d+),(\d+),(\d+),\"(.*)\"$")

# SINFO: title_index, stream_index, attribute_id, attribute_type, "value"
#   SINFO:0,0,1,6206,"Video"
#   SINFO:0,1,1,6201,"Audio"
#   SINFO:0,1,2,0,"eng"
#   SINFO:0,1,3,0,"English"
#   SINFO:0,1,5,0,"A_AC3"
#   SINFO:0,1,13,0,"AC3 5.1"
#   SINFO:0,2,1,6202,"Subtitles"
_SINFO_RE = re.compile(r"^SINFO:(\d+),(\d+),(\d+),(\d+),\"(.*)\"$")

# Stream type codes from MakeMKV
STREAM_TYPE_VIDEO = 6206
STREAM_TYPE_AUDIO = 6201
STREAM_TYPE_SUBTITLES = 6202

# SINFO attribute IDs
SINFO_TYPE = 1          # Stream type (6201=Audio, 6202=Subtitles, 6206=Video)
SINFO_LANG_CODE = 2     # Language code (eng, spa, fra, etc.)
SINFO_LANG_NAME = 3     # Language name (English, Spanish, French, etc.)
SINFO_CODEC_ID = 5      # Codec ID (A_AC3, A_DTS, S_HDMV/PGS, etc.)
SINFO_CODEC_SHORT = 13  # Codec short info ("AC3 5.1", "DTS-HD MA 7.1", etc.)
SINFO_CHANNELS = 19     # Channel layout description
SINFO_SAMPLE_RATE = 20  # Sample rate
SINFO_BITS = 21         # Bits per sample
SINFO_NAME = 22         # Stream name/title (e.g., "Director's Commentary")
SINFO_EXTRA = 30        # Extra info


def _parse_duration_to_seconds(s: str) -> Optional[int]:
    """
    Parse durations like "01:46:20" or "00:42:15".
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

    if unit.endswith("IB"):
        base = 1024.0
        unit = unit.replace("IB", "B")
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


def _detect_track_flags(stream_info: Dict[int, str]) -> Dict[str, bool]:
    """
    Detect special track flags from stream info.
    Returns dict with flags like commentary, forced, sdh, etc.
    """
    flags = {
        "commentary": False,
        "forced": False,
        "sdh": False,
        "default": False,
    }

    # Check stream name for commentary
    name = stream_info.get(SINFO_NAME, "").lower()
    extra = stream_info.get(SINFO_EXTRA, "").lower()
    codec_info = stream_info.get(SINFO_CODEC_SHORT, "").lower()

    combined = f"{name} {extra} {codec_info}"

    if "commentary" in combined or "comment" in combined:
        flags["commentary"] = True

    if "forced" in combined:
        flags["forced"] = True

    if "sdh" in combined or "hearing" in combined or "impaired" in combined:
        flags["sdh"] = True

    return flags


def _parse_audio_track(stream_index: int, stream_info: Dict[int, str]) -> Dict[str, Any]:
    """
    Parse audio track info from SINFO attributes.
    """
    lang_code = stream_info.get(SINFO_LANG_CODE, "und")
    lang_name = stream_info.get(SINFO_LANG_NAME, "Unknown")
    codec_id = stream_info.get(SINFO_CODEC_ID, "")
    codec_short = stream_info.get(SINFO_CODEC_SHORT, "")
    channels = stream_info.get(SINFO_CHANNELS, "")
    name = stream_info.get(SINFO_NAME, "")

    # Determine codec format
    codec_format = codec_short or codec_id
    if not codec_format:
        codec_format = "Unknown"

    # Parse channel info
    channel_info = channels or ""
    if not channel_info and codec_short:
        # Try to extract from codec_short like "AC3 5.1"
        m = re.search(r"(\d+\.\d+|\d+ch)", codec_short, re.IGNORECASE)
        if m:
            channel_info = m.group(1)

    flags = _detect_track_flags(stream_info)

    return {
        "index": stream_index,
        "type": "audio",
        "language_code": lang_code,
        "language": lang_name,
        "codec": codec_id,
        "format": codec_format,
        "channels": channel_info,
        "name": name,
        "commentary": flags["commentary"],
        "default": flags["default"],
        "enabled": True,  # Default to enabled
    }


def _parse_subtitle_track(stream_index: int, stream_info: Dict[int, str]) -> Dict[str, Any]:
    """
    Parse subtitle track info from SINFO attributes.
    """
    lang_code = stream_info.get(SINFO_LANG_CODE, "und")
    lang_name = stream_info.get(SINFO_LANG_NAME, "Unknown")
    codec_id = stream_info.get(SINFO_CODEC_ID, "")
    codec_short = stream_info.get(SINFO_CODEC_SHORT, "")
    name = stream_info.get(SINFO_NAME, "")

    # Determine format
    codec_format = ""
    codec_lower = codec_id.lower()
    if "pgs" in codec_lower or "hdmv" in codec_lower:
        codec_format = "PGS"
    elif "srt" in codec_lower or "subrip" in codec_lower:
        codec_format = "SRT"
    elif "ass" in codec_lower or "ssa" in codec_lower:
        codec_format = "ASS"
    elif "vobsub" in codec_lower or "dvd" in codec_lower:
        codec_format = "VobSub"
    elif "utf8" in codec_lower or "text" in codec_lower:
        codec_format = "Text"
    else:
        codec_format = codec_short or codec_id or "Unknown"

    flags = _detect_track_flags(stream_info)

    return {
        "index": stream_index,
        "type": "subtitle",
        "language_code": lang_code,
        "language": lang_name,
        "codec": codec_id,
        "format": codec_format,
        "name": name,
        "forced": flags["forced"],
        "sdh": flags["sdh"],
        "commentary": flags["commentary"],
        "default": flags["default"],
        "enabled": True,  # Default to enabled
    }


def _run_makemkv_info(make_mkv_path: str, disc_spec: str = "disc:0", timeout: int = 180) -> List[str]:
    """
    Runs: makemkvcon -r info disc:0
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
    Scan titles on the disc including audio and subtitle tracks.

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
          "audio_tracks": [
            {
              "index": 1,
              "type": "audio",
              "language_code": "eng",
              "language": "English",
              "codec": "A_TRUEHD",
              "format": "TrueHD Atmos 7.1",
              "channels": "7.1",
              "name": "",
              "commentary": false,
              "default": true,
              "enabled": true
            },
            ...
          ],
          "subtitle_tracks": [
            {
              "index": 5,
              "type": "subtitle",
              "language_code": "eng",
              "language": "English",
              "codec": "S_HDMV/PGS",
              "format": "PGS",
              "name": "",
              "forced": false,
              "sdh": false,
              "commentary": false,
              "default": false,
              "enabled": true
            },
            ...
          ],
          "raw": { ... }
        },
        ...
      ]
    """
    output_lines = _run_makemkv_info(make_mkv_path)

    # Aggregate TINFO by title_index
    titles_tinfo: Dict[int, Dict[int, str]] = {}

    # Aggregate SINFO by (title_index, stream_index)
    # Structure: {title_index: {stream_index: {attr_id: value}}}
    titles_sinfo: Dict[int, Dict[int, Dict[int, str]]] = {}

    for line in output_lines:
        line = line.strip()
        if not line:
            continue

        # Parse TINFO
        m = _TINFO_RE.match(line)
        if m:
            title_index = int(m.group(1))
            attr_id = int(m.group(2))
            value = m.group(4)

            titles_tinfo.setdefault(title_index, {})[attr_id] = value
            continue

        # Parse SINFO
        m = _SINFO_RE.match(line)
        if m:
            title_index = int(m.group(1))
            stream_index = int(m.group(2))
            attr_id = int(m.group(3))
            # attr_type = int(m.group(4))  # Usually type code, stored in value for type=1
            value = m.group(5)

            titles_sinfo.setdefault(title_index, {}).setdefault(stream_index, {})[attr_id] = value
            continue

    # Build results
    results: List[Dict[str, Any]] = []

    for title_index in sorted(titles_tinfo.keys()):
        tinfo = titles_tinfo.get(title_index, {})
        sinfo = titles_sinfo.get(title_index, {})

        # Extract title info from TINFO
        name = tinfo.get(2) or None
        length = tinfo.get(9) or None
        size = tinfo.get(10) or None
        source_file = tinfo.get(27) or None

        duration_seconds = _parse_duration_to_seconds(length) if length else None
        size_bytes = _parse_size_to_bytes(size) if size else None

        # Extract audio and subtitle tracks from SINFO
        audio_tracks: List[Dict[str, Any]] = []
        subtitle_tracks: List[Dict[str, Any]] = []

        for stream_index in sorted(sinfo.keys()):
            stream_info = sinfo[stream_index]

            # Get stream type from attribute 1
            type_value = stream_info.get(SINFO_TYPE, "")

            # Type can be the string "Audio"/"Video"/"Subtitles" or a code
            type_str = type_value.lower() if isinstance(type_value, str) else ""

            # Check for type codes or strings
            is_audio = (
                type_str in ("audio", "6201") or
                "audio" in type_str or
                type_value == str(STREAM_TYPE_AUDIO)
            )
            is_subtitle = (
                type_str in ("subtitles", "subtitle", "6202") or
                "subtitle" in type_str or
                type_value == str(STREAM_TYPE_SUBTITLES)
            )

            if is_audio:
                track = _parse_audio_track(stream_index, stream_info)
                audio_tracks.append(track)
            elif is_subtitle:
                track = _parse_subtitle_track(stream_index, stream_info)
                subtitle_tracks.append(track)
            # Skip video tracks

        results.append({
            "title_index": title_index,
            "name": name,
            "length": length,
            "duration_seconds": duration_seconds,
            "size": size,
            "size_bytes": size_bytes,
            "source_file": source_file,
            "audio_tracks": audio_tracks,
            "subtitle_tracks": subtitle_tracks,
            "raw": {
                "tinfo": tinfo,
                "sinfo": sinfo,
            },
        })

    return results
