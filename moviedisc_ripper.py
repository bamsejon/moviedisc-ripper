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
    print("❌ OMDB_API_KEY not set (check .env)")
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

        upper = name.upper()
        if upper.startswith(("BACKUP", "TIME MACHINE")):
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
        imdb_id = best["imdbID"]
        movie = omdb_by_imdb(imdb_id)
        if not movie:
            continue

        print("\n🔍 IMDb match:")
        print(f"   Title: {movie['Title']} ({movie['Year']})")
        print(f"   IMDb:  https://www.imdb.com/title/{imdb_id}/")

        confirm = input("👉 Is this the correct movie? [Y/n]: ").strip().lower()
        if confirm in ("", "y", "yes"):
            return movie

# ==========================================================
# DISC FINDER API
# ==========================================================

def discfinder_lookup(disc_label, checksum):
    r = requests.get(
        f"{DISCFINDER_API}/lookup",
        params={"disc_label": disc_label, "checksum": checksum},
        timeout=5
    )
    return r.json() if r.status_code == 200 else None

def discfinder_post(disc_label, disc_type, checksum, movie):
    payload = {
        "disc_label": disc_label,
        "disc_type": disc_type,
        "checksum": checksum,
        "imdb_id": movie["imdbID"],
        "title": movie["Title"],
        "year": movie["Year"]
    }
    requests.post(f"{DISCFINDER_API}/discs", json=payload, timeout=5)

def discfinder_feedback(disc_label, disc_type, checksum, movie, comment):
    payload = {
        "disc_label": disc_label,
        "disc_type": disc_type,
        "checksum": checksum,
        "new_imdb_id": movie["imdbID"],
        "new_title": movie["Title"],
        "new_year": movie["Year"],
        "comment": comment,
        "source": "dvd-rip-script"
    }
    requests.post(f"{DISCFINDER_API}/correct", json=payload, timeout=5)

# ==========================================================
# MAKEMKV
# ==========================================================

def rip_with_makemkv():
    os.makedirs(TEMP_DIR, exist_ok=True)

    for f in os.listdir(TEMP_DIR):
        p = os.path.join(TEMP_DIR, f)
        if os.path.isfile(p):
            os.remove(p)

    run([
        MAKE_MKV_PATH,
        "mkv",
        "disc:0",
        "0",
        TEMP_DIR
    ])

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
# EJECT
# ==========================================================

def eject(volume):
    time.sleep(10)
    subprocess.run(["diskutil", "eject", f"/Volumes/{volume}"], check=False)

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
    api_hit = discfinder_lookup(volume, checksum)

    if api_hit:
        movie = omdb_by_imdb(api_hit["imdb_id"])
        if movie:
            print("\n✅ Found in Disc Finder API")
            print(f"   Title: {movie['Title']} ({movie['Year']})")
            print(f"   IMDb:  https://www.imdb.com/title/{movie['imdbID']}/")
            print("⏱ Press SPACE and ENTER within 10 seconds if this is WRONG")

            r, _, _ = select.select([sys.stdin], [], [], 10)
            if r:
                sys.stdin.readline()
                print("\n✏️ Manual correction requested")
                movie = interactive_imdb_search()
                if movie:
                    discfinder_feedback(
                        volume, disc_type, checksum, movie,
                        comment="User corrected API match"
                    )

    if not movie:
        movie = omdb_by_title(normalize_title(volume))
        if movie:
            print("\n🔍 Found via OMDb title search")
            print(f"   {movie['Title']} ({movie['Year']})")
            print(f"   IMDb:  https://www.imdb.com/title/{movie['imdbID']}/")
            confirm = input("👉 Is this correct? [Y/n]: ").strip().lower()
            if confirm not in ("", "y", "yes"):
                movie = interactive_imdb_search()
        else:
            movie = interactive_imdb_search()

        if not movie:
            sys.exit(1)

        discfinder_post(volume, disc_type, checksum, movie)

    title = sanitize_filename(movie["Title"])
    year = movie["Year"]

    print(f"\n▶️ Identified: {title} ({year})")

    os.makedirs(MOVIES_DIR, exist_ok=True)
    movie_dir = os.path.join(MOVIES_DIR, f"{title} ({year})")
    os.makedirs(movie_dir, exist_ok=True)

    output = os.path.join(movie_dir, f"{title} ({year}).mkv")

    raw = rip_with_makemkv()
    preset = HANDBRAKE_PRESET_BD if disc_type == "BLURAY" else HANDBRAKE_PRESET_DVD
    transcode(raw, output, preset, disc_type)

    os.remove(raw)
    eject(volume)

    print(f"\n🎉 DONE → {movie_dir}")

# ==========================================================
# ENTRY
# ==========================================================

if __name__ == "__main__":
    main()