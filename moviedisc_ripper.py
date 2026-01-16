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
    requests.post(f"{DISCFINDER_API}/discs", json=payload, timeout=5)

def check_missing_assets(checksum):
    r = requests.get(f"{DISCFINDER_API}/assets/status/{checksum}", timeout=5)
    if r.status_code != 200:
        return

    status = r.json()
    missing = [k for k in ("poster", "back", "banner") if not status.get(k)]

    if missing:
        print("\n🖼️  Cover art missing!")
        print("   Missing:", ", ".join(missing))
        print("💡 Upload while ripping:")
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

    check_missing_assets(checksum)

    os.makedirs(MOVIES_DIR, exist_ok=True)
    movie_dir = os.path.join(MOVIES_DIR, f"{title} ({year})")
    os.makedirs(movie_dir, exist_ok=True)

    output = os.path.join(movie_dir, f"{title} ({year}).mkv")

    raw = rip_with_makemkv()
    preset = HANDBRAKE_PRESET_BD if disc_type == "BLURAY" else HANDBRAKE_PRESET_DVD
    transcode(raw, output, preset, disc_type)

    os.remove(raw)
    print(f"\n🎉 DONE → {movie_dir}")

# ==========================================================
# ENTRY
# ==========================================================

if __name__ == "__main__":
    main()