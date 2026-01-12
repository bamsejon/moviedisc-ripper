import os
import re
import shutil
import subprocess
from pathlib import Path

# Paths to tools (adjust these to match your system)
MAKE_MKV_PATH = "/Applications/MakeMKV.app/Contents/MacOS/makemkvcon"
HANDBRAKE_CLI_PATH = "/opt/homebrew/bin/HandBrakeCLI"  # OBS: brukar heta HandBrakeCLI (caps)

# Output directory (final destination)
OUTPUT_DIR = "/Volumes/nfs-share/media/rippat"

# Work directory (local temp is much faster than encoding from NFS)
WORK_DIR = "/tmp/makemkv_rips"


def run(cmd, check=True):
    """Run a command and return stdout (text)."""
    print("\n>>>", " ".join(cmd))
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if check and p.returncode != 0:
        print(p.stdout)
        raise RuntimeError(f"Command failed with exit code {p.returncode}")
    return p.stdout


def parse_makemkv_info_for_longest_title(info_text: str) -> str:
    """
    Parse MakeMKV 'info disc:X' output and return the title id of the longest title.
    MakeMKV has lines like:
      TINFO:0,9,0,"7345"
    where the second field '9' is duration in seconds.
    """
    # Map title_id -> length_seconds
    lengths = {}

    for line in info_text.splitlines():
        # Example: TINFO:0,9,0,"7345"
        if line.startswith("TINFO:"):
            # Extract title_id and field_id and value
            m = re.match(r'TINFO:(\d+),(\d+),\d+,"([^"]*)"', line)
            if not m:
                continue
            title_id = m.group(1)
            field_id = m.group(2)
            value = m.group(3)

            # field 9 = length in seconds (for DVD/BD usually)
            if field_id == "9":
                try:
                    lengths[title_id] = int(value)
                except ValueError:
                    pass

    if not lengths:
        raise RuntimeError("Could not find any title lengths in MakeMKV output.")

    longest = max(lengths, key=lengths.get)
    print(f"\nSelected longest title: {longest} ({lengths[longest]} seconds)")
    return longest


def get_longest_title(disc_index=0) -> str:
    print("Fetching disc info from MakeMKV...")
    info_command = [MAKE_MKV_PATH, "info", f"disc:{disc_index}"]
    output = run(info_command, check=True)
    return parse_makemkv_info_for_longest_title(output)


def rip_title_to_workdir(title_id: str, disc_index=0) -> Path:
    """
    Rip a specific title to WORK_DIR using MakeMKV.
    Returns path to the ripped MKV file.
    """
    work = Path(WORK_DIR)
    work.mkdir(parents=True, exist_ok=True)

    print(f"\nRipping title {title_id} to {work} ...")
    cmd = [MAKE_MKV_PATH, "mkv", f"disc:{disc_index}", title_id, str(work)]
    run(cmd, check=True)

    # MakeMKV usually outputs into a subfolder like WORK_DIR/title00/...
    # We'll just find the newest mkv under WORK_DIR.
    mkvs = sorted(work.rglob("*.mkv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not mkvs:
        raise RuntimeError("No MKV files found after ripping. MakeMKV may have failed.")
    ripped = mkvs[0]
    print(f"Ripped file: {ripped}")
    return ripped


def transcode_with_handbrake(input_file: Path, output_file: Path):
    """
    Transcode using Apple VideoToolbox (M2) and keep audio/subtitles properly.
    - All audio tracks
    - All subtitles as softsubs
    - No burn-in
    """
    output_file.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        HANDBRAKE_CLI_PATH,
        "-i", str(input_file),
        "-o", str(output_file),

        # Container: mkv is fine (HandBrake will choose based on extension)
        "--format", "av_mkv",

        # Video: HEVC via VideoToolbox (Apple Silicon)
        "--encoder", "vt_h265",
        "--quality", "22",

        # Keep DVD-ish geometry sane (don’t force silly upscale rules)
        "--loose-anamorphic",

        # Audio: include all tracks, prefer passthrough when possible
        "--all-audio",
        "--audio-copy-mask", "aac,ac3,eac3,dts,truehd,dtshd",
        "--audio-fallback", "aac",

        # Subtitles: include all as softsubs, never burn
        "--all-subtitles",
        "--subtitle-burned", "none",

        # Chapters
        "--markers",
    ]

    print(f"\nTranscoding to: {output_file}")
    run(cmd, check=True)


def cleanup_workdir():
    work = Path(WORK_DIR)
    if work.exists():
        print(f"\nCleaning up work dir: {work}")
        shutil.rmtree(work, ignore_errors=True)


def main():
    # Ensure output dir exists
    outdir = Path(OUTPUT_DIR)
    outdir.mkdir(parents=True, exist_ok=True)

    disc_index = 0

    try:
        title_id = get_longest_title(disc_index=disc_index)

        ripped_file = rip_title_to_workdir(title_id, disc_index=disc_index)

        # Final output name (based on ripped filename, without “compressed_” prefix)
        final_name = ripped_file.stem + ".mkv"
        final_output = outdir / final_name

        transcode_with_handbrake(ripped_file, final_output)

        print(f"\n✅ Done! Final file: {final_output}")

    finally:
        cleanup_workdir()


if __name__ == "__main__":
    main()