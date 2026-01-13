#!/usr/bin/env python3

import os
import subprocess
import sys
import json
import urllib.parse
import urllib.request

from dotenv import load_dotenv

# ========= ENV =========

load_dotenv()

OMDB_API_KEY = os.getenv("OMDB_API_KEY")
if not OMDB_API_KEY:
    print("❌ OMDB_API_KEY not set (check .env)")
    sys.exit(1)

# ========= CONFIG =========

MAKE_MKV_PATH = "/Applications/MakeMKV.app/Contents/MacOS/makemkvcon"
HANDBRAKE_CLI_PATH = "/opt/homebrew/bin/HandBrakeCLI"

TEMP_DIR = "/Volumes/Jonte/rip/tmp"
MOVIES_DIR = "/Volumes/Jonte/rip/movies"

HANDBRAKE_PRESET = "HQ 1080p30 Surround"

# ========= HELPERS =========

def run_command(cmd, capture_output=False):
    print("\n>>>", " ".join(cmd))
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.STDOUT
    )

# ========= DVD DETECTION =========

def get_dvd_volume_label():
    volumes_path = "/Volumes"
    for name in os.listdir(volumes_path):
        path = os.path.join(volumes_path, name)
        if os.path.ismount(path):
            upper = name.upper()
            if "DISC" in upper or "DVD" in upper:
                return name
    return None

def normalize_title(volume_label):
    title = volume_label.replace("_", " ").title()
    for token in [" Disc 1", " Disc 2", " Disc 3"]:
        title = title.replace(token, "")
    return title.strip()

# ========= OMDB =========

def omdb_lookup(title):
    print(f"\n🔎 OMDb lookup: {title}")
    query = urllib.parse.quote(title)
    url = f"https://www.omdbapi.com/?t={query}&apikey={OMDB_API_KEY}"

    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read().decode())

    if data.get("Response") != "True":
        print(f"❌ OMDb lookup failed for '{title}'")
        sys.exit(1)

    return {
        "title": data["Title"],
        "year": data["Year"]
    }

# ========= MAKEMKV =========

def rip_with_makemkv(title_id=0):
    print("\n🎬 Ripping disc...")
    os.makedirs(TEMP_DIR, exist_ok=True)

    cmd = [
        MAKE_MKV_PATH,
        "mkv",
        "disc:0",
        str(title_id),
        TEMP_DIR
    ]

    run_command(cmd)

    mkvs = [
        f for f in os.listdir(TEMP_DIR)
        if f.lower().endswith(".mkv")
    ]

    if not mkvs:
        print("❌ No MKV produced by MakeMKV")
        sys.exit(1)

    return os.path.join(TEMP_DIR, mkvs[0])

# ========= HANDBRAKE =========

def compress_with_handbrake(input_file, output_file):
    print(f"\n🎞 Compressing: {input_file}")

    cmd = [
        HANDBRAKE_CLI_PATH,
        "-i", input_file,
        "-o", output_file,
        "--preset", HANDBRAKE_PRESET,
        "--all-subtitles",
        "--subtitle-burned=0",
        "--format", "mkv"
    ]

    run_command(cmd)

# ========= MAIN =========

def main():
    os.makedirs(MOVIES_DIR, exist_ok=True)

    # 1️⃣ Detect DVD volume
    dvd_label = get_dvd_volume_label()
    if not dvd_label:
        print("❌ Could not detect DVD volume label")
        sys.exit(1)

    query_title = normalize_title(dvd_label)
    print(f"🎞 Detected DVD title: {query_title}")

    # 2️⃣ OMDb lookup
    movie = omdb_lookup(query_title)
    title = movie["title"]
    year = movie["year"]

    print(f"✅ Identified: {title} ({year})")

    # 3️⃣ Jellyfin movie folder
    movie_folder = f"{title} ({year})"
    movie_path = os.path.join(MOVIES_DIR, movie_folder)
    os.makedirs(movie_path, exist_ok=True)

    output_file = os.path.join(
        movie_path,
        f"{title} ({year}).mkv"
    )

    # 4️⃣ Rip
    ripped_mkv = rip_with_makemkv()

    # 5️⃣ Compress
    compress_with_handbrake(ripped_mkv, output_file)

    print("\n🎉 DONE")
    print(f"📁 Jellyfin-ready at: {movie_path}")

# ========= ENTRY =========

if __name__ == "__main__":
    main()