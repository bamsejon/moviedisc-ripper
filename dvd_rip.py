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
MOVIES_DIR = "/Volumes/nfs-share/media/rippat/movies"

# DVD optimal preset
HANDBRAKE_PRESET = "HQ 720p30 Surround"

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

def get_dvd_volume():
    for name in os.listdir("/Volumes"):
        path = os.path.join("/Volumes", name)
        if not os.path.ismount(path):
            continue

        upper = name.upper()

        # Skip obvious non-discs
        if upper.startswith(("BACKUP", "TIME MACHINE", "MACINTOSH")):
            continue

        # VIDEO_TS is the most reliable DVD indicator
        if os.path.isdir(os.path.join(path, "VIDEO_TS")):
            return name

    return None

def normalize_title(volume_label):
    title = volume_label.replace("_", " ").replace("-", " ").lower()

    # remove disc markers
    for token in ["disc", "disk", "d1", "d2", "part", "vol"]:
        title = title.replace(token, "")

    # collapse whitespace
    title = " ".join(title.split())
    return title

# ========= OMDB (FUZZY SEARCH) =========

def omdb_lookup_fuzzy(raw_title):
    print(f"\n🔎 OMDb fuzzy search: {raw_title}")

    words = [
        w for w in raw_title.split()
        if len(w) > 2
    ]

    search_query = urllib.parse.quote(" ".join(words))
    search_url = (
        f"https://www.omdbapi.com/"
        f"?s={search_query}&type=movie&apikey={OMDB_API_KEY}"
    )

    with urllib.request.urlopen(search_url) as response:
        data = json.loads(response.read().decode())

    if data.get("Response") != "True":
        print("❌ OMDb search returned no results")
        sys.exit(1)

    best_match = None
    best_score = 0

    for item in data["Search"]:
        title = item["Title"].lower()
        score = sum(1 for w in words if w in title)

        if score > best_score:
            best_score = score
            best_match = item

    if not best_match:
        print("❌ No suitable OMDb match found")
        sys.exit(1)

    imdb_id = best_match["imdbID"]
    detail_url = f"https://www.omdbapi.com/?i={imdb_id}&apikey={OMDB_API_KEY}"

    with urllib.request.urlopen(detail_url) as response:
        movie = json.loads(response.read().decode())

    print(f"✅ Best match: {movie['Title']} ({movie['Year']})")
    return {
        "title": movie["Title"],
        "year": movie["Year"]
    }

# ========= MAKEMKV =========

def rip_with_makemkv(title_id=0):
    print("\n🎬 Ripping disc...")

    # Clean temp dir first
    if os.path.exists(TEMP_DIR):
        for f in os.listdir(TEMP_DIR):
            path = os.path.join(TEMP_DIR, f)
            if os.path.isfile(path):
                os.remove(path)
    else:
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

# ========= EJECT =========

def eject_dvd(volume_name):
    print(f"\n⏏️ Ejecting DVD: {volume_name}")
    run_command(["diskutil", "eject", f"/Volumes/{volume_name}"])

# ========= MAIN =========

def main():
    os.makedirs(MOVIES_DIR, exist_ok=True)

    # 1️⃣ Detect DVD
    dvd_volume = get_dvd_volume()
    if not dvd_volume:
        print("❌ Could not detect DVD volume")
        sys.exit(1)

    print(f"🎞 Detected DVD volume: {dvd_volume}")

    normalized = normalize_title(dvd_volume)
    print(f"🎬 Normalized title: {normalized}")

    # 2️⃣ OMDb fuzzy lookup
    movie = omdb_lookup_fuzzy(normalized)
    title = movie["title"]
    year = movie["year"]

    # 3️⃣ Jellyfin structure
    movie_folder = f"{title} ({year})"
    movie_path = os.path.join(MOVIES_DIR, movie_folder)
    os.makedirs(movie_path, exist_ok=True)

    output_file = os.path.join(
        movie_path,
        f"{title} ({year}).mkv"
    )

    # 4️⃣ Rip
    ripped_mkv = rip_with_makemkv()

    # 5️⃣ Transcode
    compress_with_handbrake(ripped_mkv, output_file)

    # 6️⃣ Cleanup temp
    if os.path.exists(ripped_mkv):
        print(f"🧹 Removing raw MKV: {ripped_mkv}")
        os.remove(ripped_mkv)

    # 7️⃣ Eject disc
    eject_dvd(dvd_volume)

    print("\n🎉 DONE")
    print(f"📁 Jellyfin-ready at: {movie_path}")

# ========= ENTRY =========

if __name__ == "__main__":
    main()