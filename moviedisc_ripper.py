#!/usr/bin/env python3

import os
import sys
import json
import time
import hashlib
import subprocess
import urllib.parse
import urllib.request
import requests
import select
from dotenv import load_dotenv

# ==========================================================
# ENV
# ==========================================================

load_dotenv()

OMDB_API_KEY = os.getenv("OMDB_API_KEY")
if not OMDB_API_KEY:
    print("❌ OMDB_API_KEY not set")
    sys.exit(1)

DISCFINDER_API = "https://discfinder-api.bylund.cloud"

# ==========================================================
# CONFIG
# ==========================================================

MAKE_MKV_PATH = "/Applications/MakeMKV.app/Contents/MacOS/makemkvcon"
HANDBRAKE_CLI_PATH = "/opt/homebrew/bin/HandBrakeCLI"

TEMP_DIR = "/Volumes/Jonte/rip/tmp"
MOVIES_DIR = "/Volumes/nfs-share/media/rippat/movies"

HANDBRAKE_PRESET_DVD = "HQ 720p30 Surround"
HANDBRAKE_PRESET_BD  = "HQ 1080p30 Surround"

HANDBRAKE_AUDIO_PASSTHROUGH = [
    "--audio-copy-mask", "truehd,eac3,ac3,dts,dtshd",
    "--audio-fallback", "ac3"
]

ASSET_KINDS = ("wrap", "poster", "back", "banner")

# ==========================================================
# HELPERS
# ==========================================================

def run(cmd):
    print("\n>>>", " ".join(cmd))
    subprocess.run(cmd, check=True)

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
# OMDB
# ==========================================================

def omdb_by_title(title):
    q = urllib.parse.quote(title)
    url = f"https://www.omdbapi.com/?t={q}&type=movie&apikey={OMDB_API_KEY}"
    with urllib.request.urlopen(url) as r:
        data = json.loads(r.read().decode())
    return data if data.get("Response") == "True" else None

def omdb_by_imdb(imdb_id):
    if not imdb_id:
        return None
    url = f"https://www.omdbapi.com/?i={imdb_id}&apikey={OMDB_API_KEY}"
    with urllib.request.urlopen(url) as r:
        data = json.loads(r.read().decode())
    return data if data.get("Response") == "True" else None

def omdb_search(query):
    q = urllib.parse.quote(query)
    url = f"https://www.omdbapi.com/?s={q}&type=movie&apikey={OMDB_API_KEY}"
    with urllib.request.urlopen(url) as r:
        data = json.loads(r.read().decode())
    return data.get("Search", []) if data.get("Response") == "True" else []

# ==========================================================
# INTERACTIVE SEARCH
# ==========================================================

def interactive_imdb_search():
    while True:
        query = input("\n🎬 Enter movie title to search IMDb (ENTER to abort): ").strip()
        if not query:
            return None

        results = omdb_search(query)
        if not results:
            print("❌ No results found")
            continue

        best = results[0]
        movie = omdb_by_imdb(best["imdbID"])
        if not movie:
            continue

        print("\n🔍 IMDb match:")
        print(f"   Title: {movie['Title']} ({movie['Year']})")
        print(f"   IMDb:  https://www.imdb.com/title/{movie['imdbID']}/")

        confirm = input("👉 Is this the correct movie? [Y/n]: ").strip().lower()
        if confirm in ("", "y", "yes"):
            return movie

# ==========================================================
# UNRESOLVED FALLBACK
# ==========================================================

def unresolved_menu():
    print("\n❌ Could not reliably identify this movie.")
    print("Do you want to search again or enter name manually?")
    print("[S] Search IMDb again")
    print("[M] Enter name manually")
    print("[E] Exit")

    choice = input("👉 Choice: ").strip().lower()

    if choice == "s":
        return interactive_imdb_search()

    if choice == "m":
        title = input("✏️ Enter movie title: ").strip()
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
    # best-effort; API may reply 409 if already exists
    try:
        requests.post(f"{DISCFINDER_API}/discs", json=payload, timeout=5)
    except Exception:
        pass

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
    Downloads whatever exists for that language into movie_dir.
    Also creates Jellyfin-friendly duplicates:
      - poster.jpg
      - back.jpg + backdrop.jpg (if back exists)
      - banner.jpg
      - wrap.jpg (not Jellyfin, but kept)
    Returns list of (language_name, filename) downloaded.
    """
    info = status.get(lang_code) or {}
    language = lang_name(status, lang_code)

    existing_kinds = [k for k in ASSET_KINDS if info.get(k)]
    if not existing_kinds:
        return []

    ensure_dir(movie_dir)
    downloaded = []

    # Friendly "missing" message for this language
    missing = [k for k in ASSET_KINDS if not info.get(k)]
    print(f"\n⬇️ Downloading cover art for {language} ({lang_code})...")
    if missing:
        # Keep this short and useful
        have = [k for k in ASSET_KINDS if info.get(k)]
        print(f"   Found:   {', '.join(have)}")
        print(f"   Missing: {', '.join(missing)}")
        print("💡 You can add more while ripping:")
        print(f"   {DISCFINDER_API}/assets/upload/{checksum}")

    # Download each available kind
    for kind in existing_kinds:
        url = raw_asset_url(checksum, lang_code, kind)
        # always save a language-suffixed copy
        fname_lang = f"{kind}.{lang_code}.jpg"
        dest_lang = os.path.join(movie_dir, fname_lang)
        if download_file(url, dest_lang):
            downloaded.append((language, fname_lang))

        # Jellyfin-friendly canonical filenames (for selected language)
        # (We overwrite to keep in sync with "selected language")
        canonical_map = {
            "poster": "poster.jpg",
            "banner": "banner.jpg",
            "wrap": "wrap.jpg",
            "back": "back.jpg",
        }
        if kind in canonical_map:
            dest_can = os.path.join(movie_dir, canonical_map[kind])
            download_file(url, dest_can)
            # and special: back -> backdrop.jpg too
            if kind == "back":
                dest_backdrop = os.path.join(movie_dir, "backdrop.jpg")
                download_file(url, dest_backdrop)

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
    """
    Download new assets (added during ripping) into movie_dir as <kind>.<lang>.jpg.
    Also add the "backdrop.<lang>.jpg" copy when kind == back.
    Returns list of (language_name, filename) downloaded.
    """
    ensure_dir(movie_dir)
    downloaded = []
    for lang_code, kind in new_items:
        language = lang_name(final_status, lang_code)
        url = raw_asset_url(checksum, lang_code, kind)

        fname = f"{kind}.{lang_code}.jpg"
        dest = os.path.join(movie_dir, fname)
        if download_file(url, dest):
            downloaded.append((language, fname))

        if kind == "back":
            fname2 = f"backdrop.{lang_code}.jpg"
            dest2 = os.path.join(movie_dir, fname2)
            if download_file(url, dest2):
                downloaded.append((language, fname2))

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

    run([MAKE_MKV_PATH, "mkv", "disc:0", "0", TEMP_DIR])

    mkvs = [f for f in os.listdir(TEMP_DIR) if f.lower().endswith(".mkv")]
    if not mkvs:
        print("❌ No MKV produced")
        sys.exit(1)

    return os.path.join(TEMP_DIR, mkvs[0])

# ==========================================================
# HANDBRAKE
# ==========================================================

def transcode(input_file, output_file, preset, disc_type):
    cmd = [
        HANDBRAKE_CLI_PATH,
        "-i", input_file,
        "-o", output_file,
        "--preset", preset,
        "--all-subtitles",
        "--subtitle-burned=0",
        "--subtitle-default=none",
        "--format", "mkv"
    ]

    if disc_type == "BLURAY":
        cmd.extend(HANDBRAKE_AUDIO_PASSTHROUGH)

    run(cmd)

# ==========================================================
# MAIN
# ==========================================================

def main():
    volume, disc_type = detect_disc()
    if not volume:
        print("❌ No disc detected")
        sys.exit(1)

    print(f"\n🎞 Disc: {volume}")
    checksum = sha256(volume)
    print(f"🔐 Checksum: {checksum}")

    movie = None

    api = discfinder_lookup(checksum)

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
        else:
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
            if input("👉 Is this correct? [Y/n]: ").strip().lower() not in ("", "y", "yes"):
                movie = interactive_imdb_search()
        else:
            movie = interactive_imdb_search()

        if not movie:
            movie = unresolved_menu()
            if not movie:
                sys.exit(1)

        discfinder_post(volume, disc_type, checksum, movie)

    title = sanitize_filename(movie["Title"])
    year = movie["Year"]

    print(f"\n▶️ Identified: {title} ({year})")

    # Create destination dir early (needed for cover downloads BEFORE ripping)
    os.makedirs(MOVIES_DIR, exist_ok=True)
    movie_dir = os.path.join(MOVIES_DIR, f"{title} ({year})")
    os.makedirs(movie_dir, exist_ok=True)

    output = os.path.join(movie_dir, f"{title} ({year}).mkv")

    # ======================================================
    # COVER ART PHASE 1 (BEFORE RIP)
    # - If none => prompt upload link
    # - If some => select language (or only language) and download what exists
    # - Snapshot initial status for end-of-rip diff
    # ======================================================

    status_before = asset_status_all(checksum)

    # Treat all "missing folder / missing lang / empty lang" as "no images"
    show_missing_assets_prompt_if_none(status_before, checksum)

    selected_lang = choose_language_for_download(status_before, checksum)
    if selected_lang:
        download_assets_for_language(status_before, checksum, selected_lang, movie_dir)

    # Snapshot AFTER we did pre-rip downloads (still the API state before ripping starts)
    initial_asset_state = asset_status_all(checksum)

    # ======================================================
    # RIP + TRANSCODE
    # ======================================================

    raw = rip_with_makemkv()
    preset = HANDBRAKE_PRESET_BD if disc_type == "BLURAY" else HANDBRAKE_PRESET_DVD
    transcode(raw, output, preset, disc_type)

    try:
        os.remove(raw)
    except FileNotFoundError:
        pass

    # ======================================================
    # COVER ART PHASE 2 (AFTER ENCODE)
    # - If new assets appeared during ripping => download them
    # - Print a single friendly “thank you” message
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