#!/usr/bin/env python3

import os
import sys
import json
import time
import hashlib
import subprocess
import shutil
import urllib.parse
import urllib.request
import urllib.error
import requests
import select
import argparse
import re
from includes.makemkv_titles import scan_titles_with_makemkv
from dotenv import load_dotenv
from includes.metadata_layout import (
    ensure_metadata_layout,
    wait_for_metadata_layout_ready,
)

# ==========================================================
# ARGS
# ==========================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="DVD / Blu-ray ripping automation"
    )

    parser.add_argument(
        "--coverart",
        action="store_true",
        help="Only download cover art, do not rip or transcode"
    )

    parser.add_argument(
        "--lang",
        type=str,
        help="Language code for cover art (e.g. sv, en, de)"
    )

    return parser.parse_args()

# ==========================================================
# ENV
# ==========================================================

load_dotenv()

OMDB_API_KEY = os.getenv("OMDB_API_KEY")
if not OMDB_API_KEY:
    print("❌ OMDB_API_KEY not set")
    sys.exit(1)

# Optional: User token for linking rips to your Keepedia account
USER_TOKEN = os.getenv("USER_TOKEN")

DISCFINDER_API = "https://discfinder-api.bylund.cloud"

# ==========================================================
# CONFIG
# ==========================================================

MAKE_MKV_PATH = "/Applications/MakeMKV.app/Contents/MacOS/makemkvcon"
HANDBRAKE_CLI_PATH = "/opt/homebrew/bin/HandBrakeCLI"

TEMP_DIR = "/Volumes/Jonte/rip/tmp"
PREVIEW_PORT = 8765
MOVIES_DIR = "/Volumes/nfs-share/media/rippat/movies"

# ==========================================================
# SMB SHARE (macOS, Keychain)
# Fill in yourself:
# - SMB_SHARE:   SMB URL used by mount_smbfs
# - SMB_MOUNT_PATH: local mountpoint (should match the /Volumes/... used by MOVIES_DIR)
# ==========================================================

SMB_SHARE = "//delis.bylund.cloud/nfs-share"
SMB_MOUNT_PATH = "/Volumes/nfs-share"

HANDBRAKE_PRESET_DVD = "HQ 720p30 Surround"
HANDBRAKE_PRESET_BD  = "HQ 1080p30 Surround"

HANDBRAKE_AUDIO_PASSTHROUGH = [
    "--audio-copy-mask", "truehd,eac3,ac3,dts,dtshd",
    "--audio-fallback", "ac3"
]

ASSET_KINDS = ("wrap", "poster", "banner")

# OMDb timeout (seconds). Keeps the script from "hanging" too long.
OMDB_TIMEOUT = 12

MIN_MAIN_MOVIE_SECONDS = 45 * 60  # 45 minutes

def get_duration_seconds(path: str) -> float:
    """
    Uses ffprobe to return duration in seconds for an MKV.
    Requires ffprobe (ffmpeg) installed and in PATH.
    """
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                path
            ],
            text=True
        )
        data = json.loads(out)
        return float(data["format"]["duration"])
    except Exception:
        return 0.0

# ==========================================================
# AUDIO ANALYSIS (Commentary Detection)
# ==========================================================

def analyze_audio_track(mkv_path: str, track_index: int, sample_duration: int = 120, skip_seconds: int = 600) -> dict:
    """
    Analyze an audio track using ffmpeg volumedetect.

    Returns dict with:
        - mean_volume: average volume in dB
        - max_volume: peak volume in dB
        - dynamic_range: difference between max and mean
        - is_likely_commentary: True if dynamic range suggests commentary
    """
    try:
        cmd = [
            "ffmpeg",
            "-ss", str(skip_seconds),  # Skip intro/credits
            "-i", mkv_path,
            "-map", f"0:{track_index}",
            "-t", str(sample_duration),
            "-af", "volumedetect",
            "-f", "null",
            "-"
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )

        # Parse output
        output = result.stderr
        mean_match = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", output)
        max_match = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", output)

        if not mean_match or not max_match:
            return None

        mean_volume = float(mean_match.group(1))
        max_volume = float(max_match.group(1))
        dynamic_range = max_volume - mean_volume

        # Commentary typically has dynamic range < 20 dB
        # Movie audio typically has dynamic range > 25 dB
        is_likely_commentary = dynamic_range < 20

        return {
            "mean_volume": mean_volume,
            "max_volume": max_volume,
            "dynamic_range": round(dynamic_range, 1),
            "is_likely_commentary": is_likely_commentary
        }

    except subprocess.TimeoutExpired:
        print(f"   ⚠️ Audio analysis timed out for track {track_index}")
        return None
    except Exception as e:
        print(f"   ⚠️ Audio analysis failed for track {track_index}: {e}")
        return None


def get_audio_track_score(track: dict) -> int:
    """
    Score an audio track for quality comparison.
    Higher score = better quality.
    """
    score = 0

    # Channel format scoring (surround > stereo > mono)
    channel_format = (track.get("channel_format") or "").lower()
    if "7.1" in channel_format:
        score += 400
    elif "5.1" in channel_format:
        score += 300
    elif "stereo" in channel_format or "2.0" in channel_format:
        score += 200
    elif "mono" in channel_format or "1.0" in channel_format:
        score += 100

    # Codec scoring (lossless > lossy)
    codec_name = (track.get("codec_name") or "").lower()
    codec_format = (track.get("codec_format") or "").lower()

    # Lossless codecs
    if any(x in codec_name or x in codec_format for x in ["truehd", "dts-hd", "dts:x", "flac", "pcm", "lpcm"]):
        score += 50
    # Atmos adds bonus
    if track.get("is_atmos"):
        score += 25

    return score


def apply_audio_track_preferences(audio_tracks: list, settings: dict) -> list:
    """
    Apply user preferences to select which audio tracks should be enabled.

    - Disables commentary tracks unless include_commentary is True
    - Selects the best audio track based on audio_quality_preference
    """
    if not audio_tracks:
        return audio_tracks

    include_commentary = settings.get("include_commentary", False)
    audio_quality = settings.get("audio_quality_preference", "best")

    # First pass: mark commentary tracks
    main_tracks = []
    commentary_tracks = []

    for track in audio_tracks:
        if track.get("is_commentary"):
            commentary_tracks.append(track)
        else:
            main_tracks.append(track)

    # Disable all tracks first
    for track in audio_tracks:
        track["enabled"] = False

    # Enable best main track
    if main_tracks:
        if audio_quality == "best":
            # Sort by score (highest first) and enable the best one
            main_tracks_sorted = sorted(main_tracks, key=get_audio_track_score, reverse=True)
            best_track = main_tracks_sorted[0]
            best_track["enabled"] = True
            print(f"   🎧 Selected best audio: {best_track.get('channel_format', 'Unknown')} {best_track.get('codec_name', '')}")
        elif audio_quality == "lossless":
            # Enable only lossless tracks
            for track in main_tracks:
                codec = (track.get("codec_name") or "").lower()
                if any(x in codec for x in ["truehd", "dts-hd", "flac", "pcm", "lpcm"]):
                    track["enabled"] = True
        elif audio_quality == "lossy":
            # Enable only lossy tracks (smaller files)
            for track in main_tracks:
                codec = (track.get("codec_name") or "").lower()
                if not any(x in codec for x in ["truehd", "dts-hd", "flac", "pcm", "lpcm"]):
                    track["enabled"] = True

    # Enable commentary if user wants it
    if include_commentary:
        for track in commentary_tracks:
            track["enabled"] = True

    return audio_tracks


def analyze_audio_tracks_for_title(mkv_path: str, audio_tracks: list) -> list:
    """
    Analyze all audio tracks in an MKV file and update is_commentary flag.

    Returns updated audio_tracks list with analysis results.
    """
    if not audio_tracks:
        return audio_tracks

    print(f"\n🔊 Analyzing audio tracks for commentary detection...")

    updated_tracks = []
    for track in audio_tracks:
        stream_index = track.get("stream_index")
        if stream_index is None:
            updated_tracks.append(track)
            continue

        analysis = analyze_audio_track(mkv_path, stream_index)

        if analysis:
            # Update the track with analysis results
            track_copy = track.copy()
            track_copy["dynamic_range"] = analysis["dynamic_range"]

            # Only flag as commentary if not already detected and analysis suggests it
            if not track_copy.get("is_commentary") and analysis["is_likely_commentary"]:
                track_copy["is_commentary"] = True
                print(f"   🎤 Track {stream_index}: Likely COMMENTARY (dynamic range: {analysis['dynamic_range']} dB)")
            else:
                print(f"   🎵 Track {stream_index}: Main audio (dynamic range: {analysis['dynamic_range']} dB)")

            updated_tracks.append(track_copy)
        else:
            updated_tracks.append(track)

    return updated_tracks


def analyze_and_update_metadata(checksum: str, temp_dir: str):
    """
    Analyze all ripped MKV files and update the API with commentary detection results.
    Also applies user preferences for audio track selection.
    """
    print("\n" + "=" * 50)
    print("🔬 AUDIO ANALYSIS PHASE")
    print("=" * 50)

    # Get user settings for audio preferences
    settings = get_user_settings()

    # Get current metadata items from API
    try:
        r = requests.get(
            f"{DISCFINDER_API}/metadata-layout/{checksum}/items",
            timeout=(5, 30)
        )
        if r.status_code != 200:
            print("⚠️ Could not fetch metadata items for analysis")
            return

        items = r.json()
    except Exception as e:
        print(f"⚠️ Failed to fetch metadata items: {e}")
        return

    # Analyze each item's MKV file
    for item in items:
        title_index = item.get("title_index")
        source_file = item.get("source_file")
        audio_tracks = item.get("audio_tracks", [])

        if not audio_tracks:
            continue

        # Find the MKV file
        pattern = f"_t{title_index:02d}.mkv"
        matches = [f for f in os.listdir(temp_dir) if f.endswith(pattern)]

        if not matches:
            continue

        mkv_path = os.path.join(temp_dir, matches[0])
        print(f"\n📀 Analyzing: {matches[0]}")

        # Analyze audio tracks for commentary detection
        updated_tracks = analyze_audio_tracks_for_title(mkv_path, audio_tracks)

        # Apply user preferences for track selection
        updated_tracks = apply_audio_track_preferences(updated_tracks, settings)

        # Update API with analysis results
        try:
            r = requests.patch(
                f"{DISCFINDER_API}/metadata-layout/items/{item['id']}",
                json={"audio_tracks": updated_tracks},
                timeout=10
            )
            if r.status_code == 200:
                print(f"   ✅ Updated metadata with analysis results")
            else:
                print(f"   ⚠️ Failed to update metadata: {r.status_code}")
        except Exception as e:
            print(f"   ⚠️ Failed to update metadata: {e}")

    print("\n" + "=" * 50)


# ==========================================================
# HELPERS
# ==========================================================

def ensure_preview_server():
    """
    Starts local preview server if not already running.
    """
    import socket

    def is_port_open(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("127.0.0.1", port)) == 0

    if is_port_open(PREVIEW_PORT):
        return  # already running

    print("▶️ Starting local preview server…")

    env = os.environ.copy()
    env["DISC_PREVIEW_DIR"] = TEMP_DIR
    env["DISC_PREVIEW_PORT"] = str(PREVIEW_PORT)

    subprocess.Popen(
        [
            sys.executable,
            os.path.join(os.path.dirname(__file__), "includes", "preview_server.py")
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(0.5)


def legacy_checksum_exists(legacy_checksum: str) -> bool:
    # 1️⃣ Finns i DiscFinder API / DB?
    try:
        r = requests.get(
            f"{DISCFINDER_API}/lookup",
            params={"checksum": legacy_checksum},
            timeout=3
        )
        if r.status_code == 200:
            return True
    except Exception:
        pass

 
    return False

def run(cmd):
    print("\n>>>", " ".join(cmd))
    subprocess.run(cmd, check=True)
    

def run_makemkv(cmd):
    """
    Runs MakeMKV and aborts immediately if disc read errors are detected.
    """
    print("\n>>>", " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace"
    )

    for line in proc.stdout:
        print(line, end="")

        l = line.lower()
        if (
            "medium error" in l
            or "uncorrectable error" in l
            or "scsi error" in l
        ):
            print("\n❌ DISC READ ERROR DETECTED")
            print("💿 The disc appears to be scratched or unreadable.")
            print("🛑 Aborting rip before transcoding.")
            print("💡 Tip: Clean the disc or try another drive.")
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            sys.exit(1)

    proc.wait()

    if proc.returncode != 0:
        print("❌ MakeMKV failed with a non-zero exit code.")
        sys.exit(1)



def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def sanitize_filename(name: str) -> str:
    bad = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for b in bad:
        name = name.replace(b, '')
    return name.strip()

def wait_space_enter(seconds: int) -> bool:
    """
    Returns True if user pressed SPACE+ENTER (any line) within timeout.
    """
    r, _, _ = select.select([sys.stdin], [], [], seconds)
    if r:
        sys.stdin.readline()
        return True
    return False

def eject_disc(volume_name: str):
    """
    Eject disc on macOS using diskutil.
    """
    print(f"\n⏏️  Ejecting disc: {volume_name}")
    try:
        subprocess.run(
            ["diskutil", "eject", f"/Volumes/{volume_name}"],
            check=True
        )
    except subprocess.CalledProcessError:
        print("⚠️  Failed to eject disc (continuing anyway)")

def ensure_mount_or_die():
    """
    macOS-only: Ensure SMB share is mounted.

    Uses Keychain credentials automatically via mount_smbfs.
    - Checks SMB_MOUNT_PATH is mounted
    - If not, tries to mount SMB_SHARE at SMB_MOUNT_PATH
    - If mount fails, exits script with clear error
    """
    # Important: MOVIES_DIR lives under SMB_MOUNT_PATH, so we must ensure
    # the mount exists before using MOVIES_DIR.
    if os.path.ismount(SMB_MOUNT_PATH):
        return

    # Create mount point if it doesn't exist
    try:
        os.makedirs(SMB_MOUNT_PATH, exist_ok=True)
    except Exception as e:
        print("❌ Could not create mount path")
        print(f"   Mount path: {SMB_MOUNT_PATH}")
        print(f"   Error: {e}")
        sys.exit(1)

    print(f"🔌 SMB mount missing: {SMB_MOUNT_PATH}")
    print(f"➡️  Attempting to mount: {SMB_SHARE} → {SMB_MOUNT_PATH}")

    try:
        p = subprocess.run(
            ["mount_smbfs", SMB_SHARE, SMB_MOUNT_PATH],
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        print("\n❌ FAILED TO MOUNT SMB SHARE")
        print(f"   Share: {SMB_SHARE}")
        print(f"   Mount: {SMB_MOUNT_PATH}")
        if e.stdout:
            print("\nstdout:")
            print(e.stdout)
        if e.stderr:
            print("\nstderr:")
            print(e.stderr)
        sys.exit(1)

    # Verify mount
    if not os.path.ismount(SMB_MOUNT_PATH):
        print("\n❌ Mount command executed but share is still not mounted.")
        print(f"   Share: {SMB_SHARE}")
        print(f"   Mount: {SMB_MOUNT_PATH}")
        sys.exit(1)

    print(f"✅ Mounted SMB share: {SMB_MOUNT_PATH}")

    

# ==========================================================
# DISC DETECTION
# ==========================================================

def detect_disc():
    for name in os.listdir("/Volumes"):
        path = os.path.join("/Volumes", name)
        if not os.path.ismount(path):
            continue

        try:
            contents = os.listdir(path)
        except PermissionError:
            continue

        if "BDMV" in contents:
            return name, "BLURAY"
        if "VIDEO_TS" in contents:
            return name, "DVD"

    return None, None

def normalize_title(volume):
    title = volume.replace("_", " ").replace("-", " ").title()
    for t in [" Disc 1", " Disc 2", " Disc 3", " Blu Ray", " Dvd"]:
        title = title.replace(t, "")
    return title.strip()

# ==========================================================
# OMDB (robust wrappers)
# ==========================================================

def _omdb_get(url: str):
    """
    Returns parsed JSON dict on success, None on any OMDb/network failure.
    Never raises (so script doesn't crash if OMDb is down).
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "DVD-Rip-Automation-Script/1.0"}
        )
        with urllib.request.urlopen(req, timeout=OMDB_TIMEOUT) as r:
            data = json.loads(r.read().decode())
        return data
    except urllib.error.HTTPError as e:
        # 503 etc
        print(f"⚠️  OMDb error: HTTP {e.code} ({e.reason})")
        return None
    except urllib.error.URLError as e:
        print(f"⚠️  OMDb network error: {e.reason}")
        return None
    except Exception as e:
        print(f"⚠️  OMDb error: {e}")
        return None

def omdb_by_title(title):
    q = urllib.parse.quote(title)
    url = f"https://www.omdbapi.com/?t={q}&type=movie&apikey={OMDB_API_KEY}"
    data = _omdb_get(url)
    if not data:
        return None
    return data if data.get("Response") == "True" else None

def omdb_by_imdb(imdb_id):
    if not imdb_id:
        return None
    url = f"https://www.omdbapi.com/?i={imdb_id}&apikey={OMDB_API_KEY}"
    data = _omdb_get(url)
    if not data:
        return None
    return data if data.get("Response") == "True" else None

def omdb_search(query):
    q = urllib.parse.quote(query)
    url = f"https://www.omdbapi.com/?s={q}&type=movie&apikey={OMDB_API_KEY}"
    data = _omdb_get(url)
    if not data:
        return None  # important: distinguish "no results" vs "OMDb down"
    return data.get("Search", []) if data.get("Response") == "True" else []

# ==========================================================
# INTERACTIVE SEARCH
# ==========================================================



def extract_imdb_id(text: str):
    """
    Extract tt1234567 from either:
      - 'tt1234567'
      - 'https://www.imdb.com/title/tt1234567/'
      - any text containing tt+
    """
    if not text:
        return None
    m = re.search(r"(tt\d{7,8})", text.strip())
    return m.group(1) if m else None


def interactive_imdb_search():
    while True:
        query = input("\n🎬 Enter movie title OR IMDb ID/URL (ENTER to abort): ").strip()
        if not query:
            return None

        # 1) IMDb ID path (tt.... or URL containing it)
        imdb_id = extract_imdb_id(query)
        if imdb_id:
            movie = omdb_by_imdb(imdb_id)
            if movie is None:
                print("⚠️  OMDb is unavailable right now (or lookup failed).")
                print("💡 Tip: Try again, or use manual mode in the next step.")
                continue

            print("\n🔍 IMDb match (by ID):")
            print(f"   Title: {movie['Title']} ({movie['Year']})")
            print(f"   IMDb:  https://www.imdb.com/title/{movie['imdbID']}/")

            confirm = input("👉 Is this the correct movie? [Y/n]: ").strip().lower()
            if confirm in ("", "y", "yes"):
                return movie
            else:
                continue

        # 2) Free-text search path
        results = omdb_search(query)


        if results is None:
            print("⚠️  OMDb is unavailable right now.")
            print("💡 Tip: You can paste an IMDb ID like tt2188010 instead.")
            continue

        if not results:
            print("❌ No results found")
            continue

        # Show a small menu instead of auto-picking results[0]
        print("\n🔎 Search results:")
        top = results[:10]
        for i, item in enumerate(top, start=1):
            imdb_id = item.get("imdbID")
            imdb_url = f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else ""
            print(f"   [{i}] {item.get('Title')} ({item.get('Year')}) – {imdb_url}")

        choice = input("👉 Pick a number (ENTER = 1, 's' = search again): ").strip().lower()
        if choice == "s":
            continue

        if not choice:
            pick = top[0]
        else:
            try:
                idx = int(choice)
                if idx < 1 or idx > len(top):
                    print("❌ Invalid choice")
                    continue
                pick = top[idx - 1]
            except ValueError:
                print("❌ Invalid choice")
                continue

        movie = omdb_by_imdb(pick["imdbID"])
        if movie is None:
            print("⚠️  OMDb became unavailable while fetching details.")
            continue

        print("\n🔍 IMDb match:")
        print(f"   Title: {movie['Title']} ({movie['Year']})")
        print(f"   IMDb:  https://www.imdb.com/title/{movie['imdbID']}/")

        confirm = input("👉 Is this the correct movie? [Y/n]: ").strip().lower()
        if confirm in ("", "y", "yes"):
            return movie

# ==========================================================
# UNRESOLVED FALLBACK (true manual mode)
# ==========================================================

def unresolved_menu():
    print("\n❌ Could not reliably identify this movie (or OMDb is down).")
    print("Choose how to continue:")
    print("[I] Enter IMDb ID manually (recommended)")
    print("[M] Enter title/year manually (no IMDb)")
    print("[E] Exit")

    choice = input("👉 Choice: ").strip().lower()

    if choice == "i":
        imdb_raw = input("🎬 Enter IMDb ID or URL (e.g. tt0358273 or https://www.imdb.com/title/tt0358273/): ").strip()
        imdb = extract_imdb_id(imdb_raw)
        if not imdb:
            print("❌ Invalid IMDb ID format. It must look like tt1234567 (or a URL containing it).")
            return unresolved_menu()

        title = input("✏️ Enter movie title (as on IMDb): ").strip()
        if not title:
            print("❌ Title is required in manual IMDb mode.")
            return unresolved_menu()

        year = input("✏️ Enter year (optional): ").strip()
        return {
            "Title": title,
            "Year": year or "Unknown",
            "imdbID": imdb
        }

    if choice == "m":
        title = input("✏️ Enter movie title: ").strip()
        if not title:
            print("❌ Title is required.")
            return unresolved_menu()

        year = input("✏️ Enter year (optional): ").strip()
        return {
            "Title": title,
            "Year": year or "Unknown",
            "imdbID": None
        }

    return None

# ==========================================================
# DISC FINDER API
# ==========================================================

def metadata_items_exist(checksum: str) -> bool:
    """
    Returns True if metadata layout already has items for this checksum.
    Used to avoid reposting MakeMKV titles when layout already exists.
    """
    try:
        r = requests.get(
            f"{DISCFINDER_API}/metadata-layout/{checksum}/items",
            timeout=10
        )
        if r.status_code != 200:
            return False

        items = r.json()
        return isinstance(items, list) and len(items) > 0

    except Exception:
        return False

def get_enabled_metadata_items(checksum: str) -> list[dict]:
    try:
        r = requests.get(
            f"{DISCFINDER_API}/metadata-layout/{checksum}/items",
            timeout=(5, 30)
        )
    except requests.exceptions.RequestException as e:
        print("❌ Failed to fetch metadata layout items")
        print(e)
        sys.exit(1)

    items = r.json()
    return [i for i in items if i.get("enabled")]


def build_output_path(movie_dir: str, item: dict) -> str:
    filename = item.get("output_filename")
    if not filename:
        print("❌ Enabled item missing output_filename")
        print(item)
        sys.exit(1)

    out = os.path.join(movie_dir, filename)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    return out

def discfinder_lookup(checksum):
    r = requests.get(
        f"{DISCFINDER_API}/lookup",
        params={"checksum": checksum},
        timeout=5
    )
    return r.json() if r.status_code == 200 else None

def discfinder_post(disc_label, disc_type, checksum, movie):
    """
    Posts a new disc to the API. Returns the disc ID if successful.
    """
    payload = {
        "disc_label": disc_label,
        "disc_type": disc_type,
        "checksum": checksum,
        "imdb_id": movie.get("imdbID"),
        "title": movie["Title"],
        "year": movie["Year"]
    }

    headers = {}
    if USER_TOKEN:
        headers["Authorization"] = f"Bearer {USER_TOKEN}"

    try:
        r = requests.post(
            f"{DISCFINDER_API}/discs",
            json=payload,
            headers=headers,
            timeout=5
        )

        print(f"📡 POST /discs → HTTP {r.status_code}")
        if r.text:
            print(f"📡 Response: {r.text}")

        if r.status_code not in (200, 201, 409):
            print("❌ DiscFinder API returned unexpected status!")
            return None

        # If disc already existed (409), lookup to get the ID
        if r.status_code == 409:
            lookup = discfinder_lookup(checksum)
            return lookup.get("id") if lookup else None

        # For new disc, lookup to get the ID
        lookup = discfinder_lookup(checksum)
        return lookup.get("id") if lookup else None

    except Exception as e:
        print("❌ FAILED to post to DiscFinder API")
        print(e)
        return None

def link_disc_to_user(checksum: str):
    """
    Links an existing disc to the current user's account.
    Called after disc identification to ensure the disc appears
    in the user's collection even if it was already in the database.
    """
    if not USER_TOKEN:
        return  # No token, no linking

    headers = {"Authorization": f"Bearer {USER_TOKEN}"}

    try:
        r = requests.post(
            f"{DISCFINDER_API}/users/me/discs/{checksum}",
            headers=headers,
            timeout=5
        )

        if r.status_code == 200:
            print("📎 Disc linked to your account")
        elif r.status_code == 404:
            pass  # Disc doesn't exist yet, will be created by discfinder_post
        else:
            print(f"⚠️ Link disc returned HTTP {r.status_code}")

    except Exception as e:
        print(f"⚠️ Failed to link disc to account: {e}")


def get_user_settings() -> dict:
    """
    Fetch user settings from the API.
    Returns empty dict if no token or request fails.
    """
    if not USER_TOKEN:
        return {}

    headers = {"Authorization": f"Bearer {USER_TOKEN}"}

    try:
        r = requests.get(
            f"{DISCFINDER_API}/users/me/settings",
            headers=headers,
            timeout=5
        )
        if r.status_code == 200:
            return r.json()
        return {}
    except Exception:
        return {}


def asset_status_all(checksum):
    """
    Returns dict:
      {
        "sv": {"language":"Swedish", "wrap":true/false, "poster":..., ...},
        ...
      }
    or {} if nothing exists.
    """
    try:
        r = requests.get(f"{DISCFINDER_API}/assets/status/{checksum}", timeout=5)
        if r.status_code != 200:
            return {}
        data = r.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def languages_with_any_assets(status: dict):
    """
    Keep only languages where at least one of ASSET_KINDS is True.
    """
    langs = []
    for code, info in status.items():
        if not isinstance(info, dict):
            continue
        if any(bool(info.get(k)) for k in ASSET_KINDS):
            langs.append(code)
    return langs

def lang_name(status: dict, code: str) -> str:
    info = status.get(code) or {}
    n = info.get("language")
    return n if n else code

def choose_language_for_download(status: dict, disc_id: int):
    """
    Returns selected lang_code (or None if no assets at all).
    Selection rule:
      - If 0 languages => None
      - If 1 language => that language (with friendly message)
      - If >1 => use user's preferred language if available, otherwise first alphabetically
                 Allow 10s SPACE+ENTER to choose other
    """
    # ISO 639-2 (3-letter) to ISO 639-1 (2-letter) mapping
    iso639_2_to_1 = {
        "eng": "en", "swe": "sv", "nor": "no", "dan": "da", "fin": "fi",
        "deu": "de", "fra": "fr", "spa": "es", "ita": "it", "por": "pt",
        "nld": "nl", "pol": "pl", "rus": "ru", "jpn": "ja", "kor": "ko",
        "zho": "zh", "hin": "hi", "ara": "ar"
    }

    langs = languages_with_any_assets(status)
    if not langs:
        return None

    # default = first by human name (stable), or user's preferred language if available
    langs_sorted = sorted(langs, key=lambda c: lang_name(status, c).lower())
    default = langs_sorted[0]

    # Check user's preferred cover art language
    settings = get_user_settings()
    preferred_3letter = settings.get("preferred_cover_art_language")
    if preferred_3letter:
        preferred_2letter = iso639_2_to_1.get(preferred_3letter, preferred_3letter)
        if preferred_2letter in langs:
            default = preferred_2letter

    if len(langs_sorted) == 1:
        only_name = lang_name(status, default)
        print("\n🖼️  Cover art found!")
        print(f"   {only_name} will be downloaded as cover art (only available language).")
        print("💡 Want to add another language? Upload here while ripping:")
        print(f"   https://keepedia.org/upload/{disc_id}")
        return default

    default_name = lang_name(status, default)
    print("\n🖼️  Cover art found in multiple languages!")
    print(f"   Default: {default_name} (will be downloaded)")
    print("⏱ Press SPACE and ENTER within 10 seconds to choose another language")
    if not wait_space_enter(10):
        return default

    print("\n🌍 Select language to use for cover art:")
    for i, code in enumerate(langs_sorted, start=1):
        print(f"   [{i}] {lang_name(status, code)} ({code})")

    choice = input("👉 Choice (number, ENTER = default): ").strip()
    if not choice:
        return default
    try:
        idx = int(choice)
        if 1 <= idx <= len(langs_sorted):
            return langs_sorted[idx - 1]
    except ValueError:
        pass
    return default

def raw_asset_url(checksum: str, lang_code: str, kind: str) -> str:
    # server serves /assets/raw/<checksum>/<lang>/<kind>.jpg
    return f"{DISCFINDER_API}/assets/raw/{checksum}/{lang_code}/{kind}.jpg"

def download_file(url: str, dest_path: str) -> bool:
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return False
        with open(dest_path, "wb") as f:
            f.write(r.content)
        return True
    except Exception:
        return False

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def download_assets_for_language(status: dict, checksum: str, lang_code: str, movie_dir: str):
    """
    Downloads cover art for the SELECTED language only.
    Files are saved using canonical names (no language suffixes).
    """
    info = status.get(lang_code) or {}
    language = lang_name(status, lang_code)

    existing_kinds = [k for k in ASSET_KINDS if info.get(k)]
    if not existing_kinds:
        return []

    ensure_dir(movie_dir)
    downloaded = []

    print(f"\n⬇️ Downloading cover art for {language} ({lang_code})...")

    # Canonical Jellyfin-style filenames
    canonical_map = {
        "poster": "poster.jpg",
        "banner": "banner.jpg",
        "wrap": "backdrop.jpg",
    }

    for kind in existing_kinds:
        if kind not in canonical_map:
            continue

        url = raw_asset_url(checksum, lang_code, kind)
        dest = os.path.join(movie_dir, canonical_map[kind])

        if download_file(url, dest):
            downloaded.append((language, canonical_map[kind]))

    return downloaded

def diff_new_assets(initial: dict, final: dict):
    """
    Return list of tuples (lang_code, kind) that are new in final compared to initial.
    New means: final[lang][kind] True and initial missing or False.
    """
    new_items = []
    for lang_code, finfo in final.items():
        if not isinstance(finfo, dict):
            continue
        iinfo = initial.get(lang_code) if isinstance(initial.get(lang_code), dict) else {}
        for kind in ASSET_KINDS:
            fin = bool(finfo.get(kind))
            ini = bool(iinfo.get(kind)) if isinstance(iinfo, dict) else False
            if fin and not ini:
                new_items.append((lang_code, kind))
    return new_items

def download_new_assets(final_status: dict, checksum: str, movie_dir: str, new_items: list):
    ensure_dir(movie_dir)
    downloaded = []

    canonical_map = {
        "poster": "poster.jpg",
        "banner": "banner.jpg",
        "wrap": "backdrop.jpg",
    }

    for lang_code, kind in new_items:
        if kind not in canonical_map:
            continue

        url = raw_asset_url(checksum, lang_code, kind)
        dest = os.path.join(movie_dir, canonical_map[kind])

        if download_file(url, dest):
            downloaded.append((lang_name(final_status, lang_code), canonical_map[kind]))

    return downloaded

def show_missing_assets_prompt_if_none(status: dict, disc_id: int):
    """
    If no assets exist for this disc, prompt user to upload cover art.
    Uses disc_id for cleaner URLs.
    """
    langs = languages_with_any_assets(status)
    if not langs:
        print("\n🖼️  No cover art found for this disc yet.")
        print("💡 Why not scan/photo the cover while ripping and upload it?")
        print(f"   https://keepedia.org/upload/{disc_id}")


# ==========================================================
# MAKEMKV
# ==========================================================

def rip_with_makemkv():
    os.makedirs(TEMP_DIR, exist_ok=True)
    for f in os.listdir(TEMP_DIR):
        p = os.path.join(TEMP_DIR, f)
        if os.path.isfile(p):
            os.remove(p)

    # Dump ALL titles instead of just title 0
    run_makemkv([MAKE_MKV_PATH, "mkv", "disc:0", "all", TEMP_DIR])

    mkvs = [
        os.path.join(TEMP_DIR, f)
        for f in os.listdir(TEMP_DIR)
        if f.lower().endswith(".mkv")
    ]

    if not mkvs:
        print("❌ No MKV produced")
        sys.exit(1)

    # Pick the best candidate by duration (to avoid trailers/bonus)
    candidates = []
    for p in mkvs:
        dur = get_duration_seconds(p)
        print(f"⏱  Title candidate: {os.path.basename(p)} – {int(dur // 60)} min")
        if dur >= MIN_MAIN_MOVIE_SECONDS:
            candidates.append((p, dur))

    if not candidates:
        # Fallback: if nothing >= 45 min, pick longest anyway (still better than random)
        print("⚠️  No title >= 45 minutes found. Falling back to longest title on disc.")
        candidates = [(p, get_duration_seconds(p)) for p in mkvs]

    candidates.sort(key=lambda x: x[1], reverse=True)
    main_mkv = candidates[0][0]

    print(f"🎬 Selected main title: {os.path.basename(main_mkv)}")
    return main_mkv

# ==========================================================
# HANDBRAKE
# ==========================================================

def transcode(input_file, output_file, preset, disc_type):
    cmd = [
        HANDBRAKE_CLI_PATH,
        "-i", input_file,
        "-o", output_file,
        "--preset", preset,

        "--all-audio",
        "--audio-lang-list", "eng",

        "--all-subtitles",
        "--subtitle-burned=0",

        "--format", "mkv"
    ]

    # Blu-ray: allow passthrough where it exists
    if disc_type == "BLURAY":
        cmd.extend(HANDBRAKE_AUDIO_PASSTHROUGH)

    run(cmd)


def apply_track_metadata(output_file: str, audio_tracks: list, subtitle_tracks: list):
    """
    Use mkvpropedit to set track language and names in the final MKV.
    This ensures media players show correct language and "Commentary" labels.
    """
    # Check if mkvpropedit is available
    mkvpropedit = shutil.which("mkvpropedit")
    if not mkvpropedit:
        print("⚠️ mkvpropedit not found - skipping track metadata")
        return

    cmd = [mkvpropedit, output_file]

    # ISO 639-2 to ISO 639-2/B mapping for mkvpropedit (it uses 3-letter codes)
    # Most codes are the same, but some need mapping
    lang_map = {
        "und": "und",
        "eng": "eng", "en": "eng",
        "swe": "swe", "sv": "swe",
        "nor": "nor", "no": "nor",
        "dan": "dan", "da": "dan",
        "fin": "fin", "fi": "fin",
        "deu": "ger", "de": "ger",  # German uses "ger" in ISO 639-2/B
        "fra": "fre", "fr": "fre",  # French uses "fre" in ISO 639-2/B
        "spa": "spa", "es": "spa",
        "ita": "ita", "it": "ita",
        "por": "por", "pt": "por",
        "nld": "dut", "nl": "dut",  # Dutch uses "dut" in ISO 639-2/B
        "pol": "pol", "pl": "pol",
        "rus": "rus", "ru": "rus",
        "jpn": "jpn", "ja": "jpn",
        "kor": "kor", "ko": "kor",
        "zho": "chi", "zh": "chi",  # Chinese uses "chi" in ISO 639-2/B
    }

    # Apply audio track metadata
    audio_index = 0
    for track in (audio_tracks or []):
        if not track.get("enabled", True):
            continue
        audio_index += 1

        lang_code = track.get("language_code", "und")
        lang_code = lang_map.get(lang_code, lang_code)

        # Build track name
        track_name_parts = []
        if track.get("language_name") and track["language_name"] != "Unknown":
            track_name_parts.append(track["language_name"])
        if track.get("channel_format"):
            track_name_parts.append(track["channel_format"])
        if track.get("is_commentary"):
            track_name_parts.append("(Commentary)")

        track_name = " ".join(track_name_parts) if track_name_parts else None

        cmd.extend(["--edit", f"track:a{audio_index}"])
        cmd.extend(["--set", f"language={lang_code}"])
        if track_name:
            cmd.extend(["--set", f"name={track_name}"])

    # Apply subtitle track metadata
    sub_index = 0
    for track in (subtitle_tracks or []):
        if not track.get("enabled", True):
            continue
        sub_index += 1

        lang_code = track.get("language_code", "und")
        lang_code = lang_map.get(lang_code, lang_code)

        cmd.extend(["--edit", f"track:s{sub_index}"])
        cmd.extend(["--set", f"language={lang_code}"])
        if track.get("language_name"):
            cmd.extend(["--set", f"name={track['language_name']}"])

    if len(cmd) > 2:  # Only run if we have edits to make
        print(f"\n📝 Applying track metadata...")
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"   ✅ Track metadata applied")
        except subprocess.CalledProcessError as e:
            print(f"   ⚠️ mkvpropedit failed: {e.stderr.decode() if e.stderr else str(e)}")
        except Exception as e:
            print(f"   ⚠️ Failed to apply track metadata: {e}")


# ==========================================================
# CALCULATE CHECKSUM FOR UNIQUE DISC
# ==========================================================

def disc_fingerprint(volume: str, disc_type: str) -> str:
    base = f"/Volumes/{volume}"

    files = []
    total_size = 0

    for root, dirs, filenames in os.walk(base, onerror=lambda e: None):
        for f in filenames:
            path = os.path.join(root, f)
            try:
                st = os.stat(path)
            except FileNotFoundError:
                continue

            rel = os.path.relpath(path, base)
            files.append(rel)
            total_size += st.st_size

    files.sort()

    fingerprint = {
        "disc_type": disc_type,
        "file_count": len(files),
        "total_size": total_size,
        "files": files[:200]  # safety cap
    }

    return sha256(json.dumps(fingerprint, separators=(",", ":"), sort_keys=True))



# ==========================================================
# MAIN
# ==========================================================

def main():
    args = parse_args()
    movie = None
    volume, disc_type = detect_disc()
    if not volume:
        print("❌ No disc detected")
        sys.exit(1)

    print(f"\n🎞 Disc: {volume}")

    legacy_checksum = sha256(volume)
    new_checksum = disc_fingerprint(volume, disc_type)

    print(f"🔐 Checksum: {new_checksum}")

    legacy_exists = legacy_checksum_exists(legacy_checksum)
    if legacy_exists:
        print(f"🧓 Legacy checksum detected: {legacy_checksum}")

    api = discfinder_lookup(new_checksum)

    # ♻️ migrate old checksum → new checksum
    if not api and legacy_exists:
        legacy = discfinder_lookup(legacy_checksum)
        if legacy:
            print("♻️ Legacy checksum detected – upgrading in place")

            r = requests.put(
                f"{DISCFINDER_API}/discs/{legacy_checksum}/checksum",
                json={"new_checksum": new_checksum},
                timeout=5
            )

            if r.status_code != 200:
                print("❌ Failed to upgrade checksum")
                print(r.text)
                sys.exit(1)

            print("✅ Checksum upgraded")
            api = discfinder_lookup(new_checksum)

    checksum = new_checksum

  

 

    # ==========================================
    # COVERART-ONLY MODE
    # ==========================================
    if args.coverart:
        print("\n🖼️ Cover art only mode enabled")

        if not args.lang:
            print("❌ --coverart requires --lang <code>")
            sys.exit(1)

        status = asset_status_all(checksum)

        langs = languages_with_any_assets(status)
        if not langs:
            print("❌ No cover art found for this disc")
            sys.exit(1)

        if args.lang not in status:
            print(f"❌ No assets found for language: {args.lang}")
            print("Available languages:")
            for code in status.keys():
                print(f"  • {code} ({lang_name(status, code)})")
            sys.exit(1)

        ensure_mount_or_die()

        title = sanitize_filename(
            api["title"] if api else normalize_title(volume)
        )
        year = api["year"] if api else "Unknown"

        movie_dir = os.path.join(MOVIES_DIR, f"{title} ({year})")
        os.makedirs(movie_dir, exist_ok=True)

        downloaded = download_assets_for_language(
            status,
            checksum,
            args.lang,
            movie_dir
        )

        if downloaded:
            print("\n✅ Downloaded:")
            for language, fname in downloaded:
                print(f"   • {language} – {fname}")
        else:
            print("⚠️ No assets downloaded")

        print("\n🏁 Cover art download complete")
        sys.exit(0)

    # ✅ FIX: remember whether this disc was missing in API initially
    needs_post = (api is None)

    # -------------------------------
    # DO NOT CHANGE THIS LOGIC:
    # - If API hit -> show title + 10s "wrong" window
    # -------------------------------
    if api:
        print("✅ Found in Disc Finder API")
        print(f"   Title: {api['title']} ({api['year']})")
        if api.get("imdb_id"):
            print(f"   IMDb:  https://www.imdb.com/title/{api['imdb_id']}/")

        print("⏱ Press SPACE and ENTER within 10 seconds if this is WRONG")
        r, _, _ = select.select([sys.stdin], [], [], 10)
        if r:
            sys.stdin.readline()
            api = None
            # ✅ FIX: user said it's wrong -> treat as missing -> should post when identified
            needs_post = True
        else:
            # OMDb might be down; if so we still continue to manual later
            movie = omdb_by_imdb(api.get("imdb_id"))

    if not movie:
        print("❌ Disc not found in Disc Finder API")

        guess = normalize_title(volume)
        print(f"\n🔎 Trying disc name: {guess}")
        movie = omdb_by_title(guess)

        if movie:
            print("\n🔍 Found via disc name:")
            print(f"   Title: {movie['Title']} ({movie['Year']})")
            print(f"   IMDb:  https://www.imdb.com/title/{movie['imdbID']}/")
            resp = input("👉 Is this correct? [Y/n]: ").strip().lower()
            if resp not in ("", "y", "yes"):
                movie = interactive_imdb_search()
        else:
            # OMDb may be down -> interactive_imdb_search will detect and return None
            movie = interactive_imdb_search()

        if not movie:
            movie = unresolved_menu()
            if not movie:
                sys.exit(1)

    # ✅ FIX: post if (and only if) it was missing initially OR user marked API hit as wrong
    disc_id = None
    if needs_post:
        print("📤 Posting disc to DiscFinder API...")
        disc_id = discfinder_post(volume, disc_type, checksum, movie)
    else:
        # Disc already existed - still link it to the user's account
        link_disc_to_user(checksum)
        # Get disc ID from the API lookup
        if api:
            disc_id = api.get("id")

    title = sanitize_filename(movie["Title"])
    year = movie["Year"]

    print(f"\n▶️ Identified: {title} ({year})")

    # ======================================================
    # INIT METADATA LAYOUT (IDEMPOTENT)
    # ======================================================

    ensure_metadata_layout(
        checksum=checksum,
        disc_type="movie",   # senare: tv / mixed
        movie=movie
    )

    # ======================================================
    # SCAN DISC TITLES (MakeMKV)
    # ======================================================

    if metadata_items_exist(checksum):
        print("ℹ️ Metadata items already exist – skipping MakeMKV scan & POST")
    else:
        titles = scan_titles_with_makemkv(make_mkv_path=MAKE_MKV_PATH)

        # Build auth headers for metadata items (needed for user preferences)
        metadata_headers = {}
        if USER_TOKEN:
            metadata_headers["Authorization"] = f"Bearer {USER_TOKEN}"

        for t in titles:
            try:
                r = requests.post(
                    f"{DISCFINDER_API}/metadata-layout/{checksum}/items",
                    json=t,
                    headers=metadata_headers,
                    timeout=(5, 60)
                )
                if r.status_code not in (200, 201, 409):
                    print(f"⚠️ Metadata POST returned {r.status_code}")
            except requests.exceptions.ReadTimeout:
                print("⚠️ Metadata POST timed out – continuing")
            except requests.exceptions.RequestException as e:
                print(f"⚠️ Metadata POST failed: {e}")


    # ======================================================
    # CONTINUE NORMAL FLOW
    # ======================================================

    # Ensure SMB mount before touching MOVIES_DIR
    ensure_mount_or_die()

    # Create destination dir early (needed for cover downloads BEFORE ripping)
    os.makedirs(MOVIES_DIR, exist_ok=True)
    movie_dir = os.path.join(MOVIES_DIR, f"{title} ({year})")
    os.makedirs(movie_dir, exist_ok=True)

    output = os.path.join(movie_dir, f"{title} ({year}).mkv")

    # ======================================================
    # COVER ART PHASE 1 (BEFORE RIP)
    # ======================================================

    status_before = asset_status_all(checksum)
    if disc_id:
        show_missing_assets_prompt_if_none(status_before, disc_id)

    selected_lang = choose_language_for_download(status_before, disc_id) if disc_id else None
    if selected_lang:
        download_assets_for_language(status_before, checksum, selected_lang, movie_dir)

    # Snapshot AFTER we did pre-rip downloads
    initial_asset_state = asset_status_all(checksum)


    # ======================================================
    # RIP + TRANSCODE
    # ======================================================

    # ======================================================
    # RIP ALL TITLES (ONCE)
    # ======================================================

    os.makedirs(TEMP_DIR, exist_ok=True)
    for f in os.listdir(TEMP_DIR):
        p = os.path.join(TEMP_DIR, f)
        if os.path.isfile(p):
            os.remove(p)

    run_makemkv([MAKE_MKV_PATH, "mkv", "disc:0", "all", TEMP_DIR])
    eject_disc(volume)

    # ======================================================
    # AUDIO ANALYSIS (Commentary Detection)
    # ======================================================
    analyze_and_update_metadata(checksum, TEMP_DIR)

    ensure_preview_server()
    print("🛠 Metadata ready to edit:")
    print(f"   https://keepedia.org/metadata/{disc_id}")
    print("⏳ Waiting for metadata to be marked READY…")
    wait_for_metadata_layout_ready(checksum)
    # ======================================================
    # TRANSCODE ACCORDING TO METADATA LAYOUT
    # ======================================================

    enabled_items = get_enabled_metadata_items(checksum)
    if not enabled_items:
        print("❌ No enabled metadata items – cannot continue")
        sys.exit(1)

    preset = HANDBRAKE_PRESET_BD if disc_type == "BLURAY" else HANDBRAKE_PRESET_DVD

    for item in enabled_items:
        title_index = item["title_index"]

        # Find MKV file matching this title_index (MakeMKV names files *_tXX.mkv)
        pattern = f"_t{title_index:02d}.mkv"
        matches = [
            f for f in os.listdir(TEMP_DIR)
            if f.endswith(pattern)
        ]

        if not matches:
            print(f"❌ No MKV found for title_index {title_index:02d}")
            print("   Available files:")
            for f in os.listdir(TEMP_DIR):
                print(f"   - {f}")
            sys.exit(1)

        raw_path = os.path.join(TEMP_DIR, matches[0])

        out_path = build_output_path(movie_dir, item)

        print(f"\n🎬 Transcoding: {os.path.basename(raw_path)}")
        print(f"   → {out_path}")

        transcode(raw_path, out_path, preset, disc_type)

        # Apply track metadata (language, commentary labels) to final MKV
        apply_track_metadata(
            out_path,
            item.get("audio_tracks", []),
            item.get("subtitle_tracks", [])
        )

        try:
            os.remove(raw_path)
        except FileNotFoundError:
            pass

    # ======================================================
    # COVER ART PHASE 2 (AFTER ENCODE)
    # ======================================================

    final_asset_state = asset_status_all(checksum)
    new_items = diff_new_assets(initial_asset_state, final_asset_state)

    if new_items:
        downloaded_new = download_new_assets(final_asset_state, checksum, movie_dir, new_items)
        if downloaded_new:
            print("\n💚 I noticed that new cover art was added during the ripping.")
            print("\n⬇️ Downloaded:")
            for language, fname in downloaded_new:
                print(f"   • {language} – {fname}")
            print("\n🙏 Was it you? If so – thank you so much for contributing to the community!")

    print(f"\n🎉 DONE → {movie_dir}")

# ==========================================================
# ENTRY
# ==========================================================

if __name__ == "__main__":
    main()