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

# Pattern to detect angle announcements: "Angle #2 was added for title #3"
_ANGLE_RE = re.compile(r"Angle #(\d+) was added for title #(\d+)", re.IGNORECASE)

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
# NOTE: These codes differ between DVD and Blu-ray!
#   DVD:     6206=Video, 6201=Audio, 6202=Subtitles
#   Blu-ray: 6201=Video, 6202=Audio, 6203=Subtitles
# The detection logic uses string matching ("video"/"audio"/"subtitles") instead
# of these numeric codes to work with both formats.
STREAM_TYPE_VIDEO_DVD = 6206
STREAM_TYPE_AUDIO_DVD = 6201
STREAM_TYPE_SUBTITLES_DVD = 6202
STREAM_TYPE_VIDEO_BLURAY = 6201
STREAM_TYPE_AUDIO_BLURAY = 6202
STREAM_TYPE_SUBTITLES_BLURAY = 6203

# Legacy aliases (kept for backward compatibility)
STREAM_TYPE_VIDEO = 6206
STREAM_TYPE_AUDIO = 6201
STREAM_TYPE_SUBTITLES = 6202

# SINFO attribute IDs (from MakeMKV source/output analysis)
SINFO_TYPE = 1          # Stream type code in attr_type position, type name in value
SINFO_TYPE_NAME = 2     # Channel info for audio (e.g., "Surround 5.1")
SINFO_LANG_CODE = 3     # Language code (eng, spa, fra, etc.)
SINFO_LANG_NAME = 4     # Language name (English, Spanish, French, etc.)
SINFO_CODEC_ID = 5      # Codec ID (A_AC3, A_DTS, S_HDMV/PGS, etc.)
SINFO_CODEC_SHORT = 6   # Codec short name
SINFO_BITRATE = 8       # Bitrate info
SINFO_CHANNELS = 13     # Channel/stream info ("Surround 5.1", "448 Kb/s", etc.)
SINFO_SAMPLE_RATE = 14  # Sample rate
SINFO_BITS = 17         # Bit depth
SINFO_NAME = 30         # Stream name/title (e.g., "Director's Commentary")
SINFO_EXTRA = 31        # Extra info

# ISO 639-2 language code to name mapping (common languages)
LANG_CODE_TO_NAME = {
    "eng": "English",
    "spa": "Spanish",
    "fra": "French",
    "fre": "French",
    "deu": "German",
    "ger": "German",
    "ita": "Italian",
    "por": "Portuguese",
    "rus": "Russian",
    "jpn": "Japanese",
    "zho": "Chinese",
    "chi": "Chinese",
    "kor": "Korean",
    "ara": "Arabic",
    "hin": "Hindi",
    "tha": "Thai",
    "vie": "Vietnamese",
    "pol": "Polish",
    "nld": "Dutch",
    "dut": "Dutch",
    "swe": "Swedish",
    "nor": "Norwegian",
    "dan": "Danish",
    "fin": "Finnish",
    "ice": "Icelandic",
    "isl": "Icelandic",
    "ces": "Czech",
    "cze": "Czech",
    "hun": "Hungarian",
    "tur": "Turkish",
    "heb": "Hebrew",
    "gre": "Greek",
    "ell": "Greek",
    "ron": "Romanian",
    "rum": "Romanian",
    "bul": "Bulgarian",
    "hrv": "Croatian",
    "slv": "Slovenian",
    "srp": "Serbian",
    "ukr": "Ukrainian",
    "und": "Unknown",
}

# Audio codec ID to human-readable name mapping
AUDIO_CODEC_NAMES = {
    "A_AC3": "Dolby Digital",
    "A_EAC3": "Dolby Digital Plus",
    "A_TRUEHD": "Dolby TrueHD",
    "A_DTS": "DTS",
    "A_DTS-HD": "DTS-HD",
    "A_DTS-HD.MA": "DTS-HD Master Audio",
    "A_DTS-HD.HRA": "DTS-HD High Resolution",
    "A_DTS:X": "DTS:X",
    "A_AAC": "AAC",
    "A_FLAC": "FLAC",
    "A_PCM": "PCM",
    "A_LPCM": "LPCM",
    "A_MP3": "MP3",
    "A_VORBIS": "Vorbis",
    "A_OPUS": "Opus",
    "A_MPEG/L2": "MP2",
    "A_MPEG/L3": "MP3",
}

# Keywords that indicate Atmos (object-based audio)
ATMOS_KEYWORDS = ("atmos", "truehd atmos", "dd+ atmos", "dolby atmos")


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
    lang_name = stream_info.get(SINFO_LANG_NAME, "")
    codec_id = stream_info.get(SINFO_CODEC_ID, "")
    codec_short = stream_info.get(SINFO_CODEC_SHORT, "")
    channels = stream_info.get(SINFO_CHANNELS, "")
    name = stream_info.get(SINFO_NAME, "")

    # Lookup language name from code if not provided
    if not lang_name or lang_name == "Unknown":
        lang_name = LANG_CODE_TO_NAME.get(lang_code.lower(), lang_code.upper() if lang_code else "Unknown")

    # Get human-readable codec name
    codec_readable = AUDIO_CODEC_NAMES.get(codec_id.upper(), "")
    if not codec_readable:
        # Try partial match for variants like A_DTS-HD.MA
        for key, val in AUDIO_CODEC_NAMES.items():
            if codec_id.upper().startswith(key):
                codec_readable = val
                break
    if not codec_readable:
        codec_readable = codec_id or "Unknown"

    # Parse channel layout from channels field or name
    # Look for patterns like "5.1", "7.1", "2.0", "Surround 5.1"
    channel_layout = ""
    all_info = f"{channels} {name} {codec_short}"

    # Try to find channel layout - be specific to avoid matching bitrates like "1.5 Mb/s"
    # Valid channel layouts: 1.0, 2.0, 2.1, 5.1, 6.1, 7.1, 7.2, etc.
    m = re.search(r"\b([12567]\.[012])\b", all_info)
    if m:
        channel_layout = m.group(1)
    elif "stereo" in all_info.lower():
        channel_layout = "2.0"
    elif "mono" in all_info.lower():
        channel_layout = "1.0"
    elif "surround" in all_info.lower() and not channel_layout:
        channel_layout = "5.1"  # Default surround assumption

    # Format channel info nicely
    if channel_layout:
        if channel_layout in ("5.1", "6.1", "7.1"):
            channel_format = f"{channel_layout} Surround"
        elif channel_layout == "2.0":
            channel_format = "Stereo"
        elif channel_layout == "1.0":
            channel_format = "Mono"
        else:
            channel_format = channel_layout
    else:
        channel_format = channels or ""

    # Extract bitrate if available
    bitrate = ""
    m = re.search(r"(\d+(?:\.\d+)?\s*[KkMm]b/s)", all_info)
    if m:
        bitrate = m.group(1)

    # Detect Atmos
    is_atmos = any(kw in all_info.lower() for kw in ATMOS_KEYWORDS)

    # Build codec format string: "Dolby TrueHD Atmos 7.1" or "DTS-HD MA 7.1"
    codec_format = codec_readable
    if is_atmos and "atmos" not in codec_format.lower():
        codec_format = f"{codec_readable} Atmos"
    if channel_layout and channel_layout not in codec_format:
        codec_format = f"{codec_format} {channel_layout}"

    # Keep bitrate separate but available
    # channel_format will show the surround info
    if not channel_format and bitrate:
        channel_format = bitrate

    flags = _detect_track_flags(stream_info)

    return {
        "stream_index": stream_index,
        "type": "audio",
        "language_code": lang_code,
        "language_name": lang_name,
        "codec_name": codec_format,  # Human readable format
        "codec_format": codec_id,    # Raw codec ID for reference
        "channel_format": channel_format,
        "name": name,
        "is_atmos": is_atmos,
        "is_commentary": flags["commentary"],
        "is_default": flags["default"],
        "enabled": True,  # Default to enabled
    }


def _parse_subtitle_track(stream_index: int, stream_info: Dict[int, str]) -> Dict[str, Any]:
    """
    Parse subtitle track info from SINFO attributes.
    """
    lang_code = stream_info.get(SINFO_LANG_CODE, "und")
    lang_name = stream_info.get(SINFO_LANG_NAME, "")
    codec_id = stream_info.get(SINFO_CODEC_ID, "")
    codec_short = stream_info.get(SINFO_CODEC_SHORT, "")
    name = stream_info.get(SINFO_NAME, "")

    # Lookup language name from code if not provided
    if not lang_name or lang_name == "Unknown":
        lang_name = LANG_CODE_TO_NAME.get(lang_code.lower(), lang_code.upper() if lang_code else "Unknown")

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
        "stream_index": stream_index,
        "type": "subtitle",
        "language_code": lang_code,
        "language_name": lang_name,
        "codec_name": codec_id,
        "codec_format": codec_format,
        "name": name,
        "is_forced": flags["forced"],
        "is_sdh": flags["sdh"],
        "is_commentary": flags["commentary"],
        "is_default": flags["default"],
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

    # Track if angles were detected (indicates some titles may be duplicates)
    angles_detected = False

    for line in output_lines:
        line = line.strip()
        if not line:
            continue

        # Check for angle announcement (e.g., "Angle #2 was added for title #3")
        if _ANGLE_RE.search(line):
            angles_detected = True
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

            # Get stream type from attribute 1 (SINFO_TYPE)
            # The value is always a string like "Audio", "Video", "Subtitles"
            # This works for both DVD and Blu-ray formats
            type_value = stream_info.get(SINFO_TYPE, "")
            type_str = type_value.lower() if isinstance(type_value, str) else ""

            # Detect stream type using string matching (works for DVD + Blu-ray)
            is_audio = "audio" in type_str
            is_subtitle = "subtitle" in type_str

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

    # Filter out angle duplicates if angles were detected
    # Angles are alternate camera views of the same content - same duration, different title_index
    # MakeMKV only rips the first angle, so we should only report one title per unique duration
    if angles_detected and len(results) > 1:
        print("\n⚠️  Multiple angles detected - filtering duplicates...")

        # Group by duration (angles have identical duration)
        seen_durations: Dict[Optional[int], int] = {}  # duration -> first title_index
        filtered_results: List[Dict[str, Any]] = []
        skipped_angles: List[int] = []

        for item in results:
            duration = item.get("duration_seconds")
            title_idx = item.get("title_index")

            if duration in seen_durations:
                # This is likely an angle duplicate - skip it
                skipped_angles.append(title_idx)
            else:
                seen_durations[duration] = title_idx
                filtered_results.append(item)

        if skipped_angles:
            print(f"   Skipped angle duplicates: title_index {skipped_angles}")
            print(f"   Keeping {len(filtered_results)} unique title(s)")

        return filtered_results

    return results
