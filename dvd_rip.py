#!/usr/bin/env python3

import os
import subprocess
import sys
import json
import urllib.parse
import urllib.request
import time
import hashlib
import requests
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

DISCFINDER_API = "https://discfinder-api.bylund.cloud"

# Blu-ray audio passthrough (Atmos / DTS-HD / TrueHD)
HANDBRAKE_AUDIO_PASSTHROUGH = [
    "--audio-copy-mask", "truehd,eac3,ac3,dts,dtshd",
    "--audio-fallback", "ac3"
]

# ==========================================================
# HELPERS
# ==========================================================

def run_command(cmd):
    print("\n>>>", " ".join(cmd))
    subprocess.run(cmd, check=True)

def sha256_of_files(file_paths):
    h = hashlib.sha256()
    for path in sorted(file_paths):
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
    return h.hexdigest()

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

        if os.path.isdir(os.path.join(path, "BDMV")):
            return name, "BLURAY"

        if os.path.isdir(os.path.join(path, "VIDEO_TS")):
            return name, "DVD"

    return None, None

def normalize_title(volume_name):
    title = volume_name.replace("_", " ").replace("-", " ").title()
    for token in [" Disc 1", " Disc 2", " Disc 3", " Blu Ray", " Dvd"]:
        title = title.replace(token, "")
    return title.strip()

# ==========================================================
# CHECKSUM
# ==========================================================

def generate_disc_checksum(volume, disc_type):
    base = f"/Volumes/{volume}"

    if disc_type == "DVD":
        vt = os.path.join(base, "VIDEO_TS")
        files = [
            os.path.join(vt, f)
            for f in os.listdir(vt)
            if f.endswith((".IFO", ".BUP"))
        ]
    else:
        files = [
            os.path.join(base, "BDMV", "index.bdmv"),
            os.path.join(base, "BDMV", "MovieObject.bdmv"),
        ]

    return sha256_of_files(files)

# ==========================================================
# DISCFINDER API
# ==========================================================

def lookup_disc_api(checksum):
    try:
        r = requests.get(
            f"{DISCFINDER_API}/lookup",
            params={"checksum": checksum},
            timeout=5,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def create_disc_api(payload):
    try:
        r = requests.post(
            f"{DISCFINDER_API}/discs",
            json=payload,
            timeout=5,
        )
        return r.status_code in (200, 201)
    except Exception:
        return False

# ==========================================================
# OMDB
# ==========================================================

def omdb_lookup_by_title(title):
    print(f"\n🔎 OMDb lookup: {title}")
    query = urllib.parse.quote(title)
    url = f"https://www.omdbapi.com/?t={query}&apikey={OMDB_API_KEY}"

    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read().decode())

    return data if data.get("Response") == "True" else None

def omdb_lookup_by_imdb(imdb_id):
    print(f"\n🔎 OMDb lookup by IMDb ID: {imdb_id}")
    url = f"https://www.omdbapi.com/?i={imdb_id}&apikey={OMDB_API_KEY}"

    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read().decode())

    return data if data.get("Response") == "True" else None

# ==========================================================
# MAKEMKV
# ==========================================================

def rip_with_makemkv():
    print("\n🎬 Ripping disc...")

    os.makedirs(TEMP_DIR, exist_ok=True)
    for f in os.listdir(TEMP_DIR):
        p = os.path.join(TEMP_DIR, f)
        if os.path.isfile(p):
            os.remove(p)

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

def transcode(input_file, output_file, preset, disc_type):
    print(f"\n🎞 Transcoding with HandBrake ({preset})")

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
        print("🔊 Preserving lossless audio (Atmos / DTS:X)")
        cmd.extend(HANDBRAKE_AUDIO_PASSTHROUGH)

    run_command(cmd)

# ==========================================================
# EJECT
# ==========================================================

def eject_disc(volume_name):
    print("⏏️ Preparing to eject disc")
    time.sleep(10)

    volume_path = f"/Volumes/{volume_name}"
    result = subprocess.run(
        ["diskutil", "eject", volume_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        subprocess.run(["diskutil", "eject", "force", volume_path], check=False)

# ==========================================================
# MAIN
# ==========================================================

def main():
    os.makedirs(MOVIES_DIR, exist_ok=True)

    volume, disc_type = detect_disc()
    if not volume:
        print("❌ No DVD or Blu-ray detected")
        sys.exit(1)

    print(f"🎞 Detected disc volume: {volume}")
    print(f"💿 Disc type: {disc_type}")

    checksum = generate_disc_checksum(volume, disc_type)
    print(f"🔐 Disc checksum: {checksum}")

    disc = lookup_disc_api(checksum)

    if disc:
        print("🌍 Found disc in DiscFinder API")
        title = disc["title"]
        year = disc["year"]
        imdb_id = disc["imdb_id"]
    else:
        print("🌍 Disc not found in API – using OMDb")
        normalized = normalize_title(volume)

        movie = omdb_lookup_by_title(normalized)
        if not movie:
            imdb_id = input("👉 Enter IMDb ID: ").strip()
            movie = omdb_lookup_by_imdb(imdb_id)
            if not movie:
                sys.exit("❌ Invalid IMDb ID")

        title = movie["Title"]
        year = movie["Year"]
        imdb_id = movie["imdbID"]

        payload = {
            "disc_label": volume,
            "disc_type": disc_type,
            "checksum": checksum,
            "imdb_id": imdb_id,
            "title": title,
            "year": year,
        }

        if create_disc_api(payload):
            print("💾 Disc added to DiscFinder API")

    movie_folder = f"{title} ({year})"
    movie_path = os.path.join(MOVIES_DIR, movie_folder)
    os.makedirs(movie_path, exist_ok=True)

    output_file = os.path.join(movie_path, f"{title} ({year}).mkv")

    raw_mkv = rip_with_makemkv()
    preset = HANDBRAKE_PRESET_BD if disc_type == "BLURAY" else HANDBRAKE_PRESET_DVD
    transcode(raw_mkv, output_file, preset, disc_type)

    os.remove(raw_mkv)
    eject_disc(volume)

    print("\n🎉 DONE")
    print(f"📁 Jellyfin-ready at: {movie_path}")

# ==========================================================
# ENTRY
# ==========================================================

if __name__ == "__main__":
    main()