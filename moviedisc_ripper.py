#!/usr/bin/env python3

import os
import sys
import json
import time
import hashlib
import subprocess
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

    except Exception as e:
        print("❌ FAILED to post to DiscFinder API")
        print(e)

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

def choose_language_for_download(status: dict, checksum: str):
    """
    Returns selected lang_code (or None if no assets at all).
    Selection rule:
      - If 0 languages => None
      - If 1 language => that language (with friendly message)
      - If >1 => pick first (sorted by language name), allow 10s SPACE+ENTER to choose other
    """
    langs = languages_with_any_assets(status)
    if not langs:
        return None

    # default = first by human name (stable)
    langs_sorted = sorted(langs, key=lambda c: lang_name(status, c).lower())
    default = langs_sorted[0]

    if len(langs_sorted) == 1:
        only_name = lang_name(status, default)
        print("\n🖼️  Cover art found!")
        print(f"   {only_name} will be downloaded as cover art (only available language).")
        print("💡 Want to add another language? Upload here while ripping:")
        print(f"   {DISCFINDER_API}/assets/upload/{checksum}")
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

def show_missing_assets_prompt_if_none(status: dict, checksum: str):
    """
    If checksum dir missing OR lang dir missing OR lang dirs exist but contain no supported images
    => status will be {} or no langs with any assets. Treat as no images.
    """
    langs = languages_with_any_assets(status)
    if not langs:
        print("\n🖼️  No cover art found for this disc yet.")
        print("💡 Why not scan/photo the cover while ripping and upload it?")
        print(f"   {DISCFINDER_API}/assets/upload/{checksum}")


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
    if needs_post:
        print("📤 Posting disc to DiscFinder API...")
        discfinder_post(volume, disc_type, checksum, movie)
    else:
        # Disc already existed - still link it to the user's account
        link_disc_to_user(checksum)

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

        for t in titles:
            try:
                r = requests.post(
                    f"{DISCFINDER_API}/metadata-layout/{checksum}/items",
                    json=t,
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
    show_missing_assets_prompt_if_none(status_before, checksum)

    selected_lang = choose_language_for_download(status_before, checksum)
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
    ensure_preview_server()
    print("🛠 Metadata ready to edit:")
    print(f"   https://keepedia.org/metadata/{checksum}")
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