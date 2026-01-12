#!/usr/bin/env python3

import os
import subprocess
import sys

# ========= PATHS =========

MAKE_MKV_PATH = "/Applications/MakeMKV.app/Contents/MacOS/makemkvcon"
HANDBRAKE_CLI_PATH = "/opt/homebrew/bin/HandBrakeCLI"

# Base output directory (temporary MKV + final files)
OUTPUT_BASE_DIR = "/Volumes/nfs-share/media/rippat"

# HandBrake preset (Apple Silicon-friendly)
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


# ========= MAKEMKV =========

def rip_title_with_makemkv(title_id, output_dir, disc_index=0):
    print(f"\n🎬 Ripping title #{title_id} with MakeMKV...")

    cmd = [
        MAKE_MKV_PATH,
        "mkv",
        f"disc:{disc_index}",
        str(title_id),
        output_dir
    ]

    run_command(cmd)
    print("✅ MakeMKV ripping completed")


# ========= HANDBRAKE =========

def compress_with_handbrake(input_file, output_file):
    print(f"\n🎞 Compressing with HandBrake: {input_file}")

    cmd = [
        HANDBRAKE_CLI_PATH,
        "-i", input_file,
        "-o", output_file,
        "--preset", HANDBRAKE_PRESET,

        # ✅ SUBTITLES
        "--all-subtitles",
        "--subtitle-burned=0",

        # ✅ Rekommenderat för Jellyfin
        "--format", "mkv"
    ]

    run_command(cmd)
    print("✅ HandBrake compression completed")


# ========= MAIN =========

def main():
    # Ensure output directory exists
    os.makedirs(OUTPUT_BASE_DIR, exist_ok=True)

    # Always use title 0 (main movie in almost all cases)
    title_id = 0

    # Step 1: Rip DVD / Blu-ray
    rip_title_with_makemkv(
        title_id=title_id,
        output_dir=OUTPUT_BASE_DIR
    )

    # Step 2: Find ripped MKV(s)
    ripped_files = [
        f for f in os.listdir(OUTPUT_BASE_DIR)
        if f.lower().endswith(".mkv")
    ]

    if not ripped_files:
        print("❌ No MKV files found after ripping")
        sys.exit(1)

    # Step 3: Compress each MKV
    for mkv in ripped_files:
        input_path = os.path.join(OUTPUT_BASE_DIR, mkv)
        output_path = os.path.join(
            OUTPUT_BASE_DIR,
            mkv.replace(".mkv", ".compressed.mkv")
        )

        compress_with_handbrake(input_path, output_path)

    print("\n🎉 ALL DONE")


# ========= ENTRY POINT =========

if __name__ == "__main__":
    main()