#!/usr/bin/env python3

import os
import subprocess
import sys
import json
import urllib.parse
import urllib.request
import time
from dotenv import load_dotenv

# ==========================================================
# ENV
# ==========================================================

load_dotenv()

OMDB_API_KEY = os.getenv("OMDB_API_KEY")
if not OMDB_API_KEY:
    print("❌ OMDB_API_KEY not set (check .env)")
    sys.exit(1)

# ==========================================================
# CONFIG
# ==========================================================

MAKE_MKV_PATH = "/Applications/MakeMKV.app/Contents/MacOS/makemkvcon"
HANDBRAKE_CLI_PATH = "/opt/homebrew/bin/HandBrakeCLI"

TEMP_DIR = "/Volumes/Jonte/rip/tmp"
MOVIES_DIR = "/Volumes/nfs-share/media/rippat/movies"

HANDBRAKE_PRESET_DVD = "HQ 720p30 Surround"
HANDBRAKE_PRESET_BD  = "HQ 1080p30 Surround"

OVERRIDES_FILE = "title_overrides.json"

# ==========================================================
# HELPERS
# ==========================================================

def run_command(cmd):
    print("\n>>>", " ".join(cmd))
    subprocess.run(cmd, check=True)

def load_overrides():
    if not os.path.exists(OVERRIDES_FILE):
        return {}
    with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_overrides(overrides):
    with open(OVERRIDES_FILE, "w", encoding="utf-8") as f:
        json.dump(overrides, f, indent=2, ensure_ascii=False)

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

        if "BDMV" in os.listdir(path):
            return name, "BLURAY"

        if "VIDEO_TS" in os.listdir(path):
            return name, "DVD"

    return None, None

def normalize_title(volume_name):
    title = volume_name.replace("_", " ").replace("-", " ").title()
    for token in [" Disc 1", " Disc 2", " Disc 3", " Blu Ray", " Dvd"]:
        title = title.replace(token, "")
    return title.strip()

# ==========================================================
# OMDB
# ==========================================================

def omdb_lookup_by_title(title):
    print(f"\n🔎 OMDb fuzzy lookup: {title}")
    query = urllib.parse.quote(title)
    url = f"https://www.omdbapi.com/?t={query}&apikey={OMDB_API_KEY}"

    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read().decode())

    if data.get("Response") != "True":
        return None

    return data

def omdb_lookup_by_imdb(imdb_id):
    print(f"\n🔎 OMDb lookup by IMDb ID: {imdb_id}")
    url = f"https://www.omdbapi.com/?i={imdb_id}&apikey={OMDB_API_KEY}"

    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read().decode())

    if data.get("Response") != "True":
        return None

    return data

# ==========================================================
# MAKEMKV
# ==========================================================

def rip_with_makemkv():
    print("\n🎬 Ripping disc...")

    os.makedirs(TEMP_DIR, exist_ok=True)

    for f in os.listdir(TEMP_DIR):
        path = os.path.join(TEMP_DIR, f)
        if os.path.isfile(path):
            os.remove(path)

    cmd = [
        MAKE_MKV_PATH,
        "mkv",
        "disc:0",
        "0",
        TEMP_DIR
    ]

    run_command(cmd)

    mkvs = [f for f in os.listdir(TEMP_DIR) if f.lower().endswith(".mkv")]
    if not mkvs:
        print("❌ No MKV produced by MakeMKV")
        sys.exit(1)

    return os.path.join(TEMP_DIR, mkvs[0])

# ==========================================================
# HANDBRAKE
# ==========================================================

def transcode(input_file, output_file, preset):
    print(f"\n🎞 Transcoding with HandBrake ({preset})")

    cmd = [
        HANDBRAKE_CLI_PATH,
        "-i", input_file,
        "-o", output_file,
        "--preset", preset,
        "--all-subtitles",
        "--subtitle-burned=0",
        "--format", "mkv"
    ]

    run_command(cmd)

# ==========================================================
# EJECT (ROBUST)
# ==========================================================

def eject_disc(volume_name):
    print("⏏️ Preparing to eject disc")

    # Give macOS time to release the disc (loginwindow etc)
    time.sleep(10)

    volume_path = f"/Volumes/{volume_name}"

    print("⏏️ Attempting normal eject")
    result = subprocess.run(
        ["diskutil", "eject", volume_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode == 0:
        print("✅ Disc ejected successfully")
        return

    print("⚠️ Normal eject failed, trying force eject")
    subprocess.run(
        ["diskutil", "eject", "force", volume_path],
        check=False
    )

# ==========================================================
# MAIN
# ==========================================================

def main():
    os.makedirs(MOVIES_DIR, exist_ok=True)

    overrides = load_overrides()

    volume, disc_type = detect_disc()
    if not volume:
        print("❌ No DVD or Blu-ray detected")
        sys.exit(1)

    print(f"🎞 Detected disc volume: {volume}")
    print(f"💿 Disc type: {disc_type}")

    normalized = normalize_title(volume)
    print(f"🎬 Normalized title: {normalized}")

    movie_data = None

    if volume in overrides:
        imdb_id = overrides[volume]["imdb_id"]
        movie_data = omdb_lookup_by_imdb(imdb_id)
        if not movie_data:
            print("❌ IMDb override failed")
            sys.exit(1)
    else:
        movie_data = omdb_lookup_by_title(normalized)

        if not movie_data:
            print("\n❌ OMDb search failed")
            imdb_id = input("👉 Enter IMDb ID (example: tt0120737), or press ENTER to abort: ").strip()
            if not imdb_id:
                sys.exit(1)

            movie_data = omdb_lookup_by_imdb(imdb_id)
            if not movie_data:
                print("❌ Invalid IMDb ID")
                sys.exit(1)

            overrides[volume] = {"imdb_id": imdb_id}
            save_overrides(overrides)
            print("💾 Saved override to title_overrides.json")

    title = movie_data["Title"]
    year = movie_data["Year"]

    print(f"✅ Identified: {title} ({year})")

    movie_folder = f"{title} ({year})"
    movie_path = os.path.join(MOVIES_DIR, movie_folder)
    os.makedirs(movie_path, exist_ok=True)

    output_file = os.path.join(movie_path, f"{title} ({year}).mkv")

    raw_mkv = rip_with_makemkv()

    preset = HANDBRAKE_PRESET_BD if disc_type == "BLURAY" else HANDBRAKE_PRESET_DVD
    transcode(raw_mkv, output_file, preset)

    if os.path.exists(raw_mkv):
        os.remove(raw_mkv)

    eject_disc(volume)

    print("\n🎉 DONE")
    print(f"📁 Jellyfin-ready at: {movie_path}")

# ==========================================================
# ENTRY
# ==========================================================

if __name__ == "__main__":
    main()