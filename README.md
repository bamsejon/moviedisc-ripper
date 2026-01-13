# DVD Rip Automation Script

A fully automated DVD ripping and transcoding workflow for macOS, designed to produce Jellyfin-ready movie libraries with correct titles, metadata, subtitles, and folder structure.

Insert a DVD → run the script → wait → disc ejects → movie appears in Jellyfin.

---

## Project origin & credit

This project is a fork and extended rewrite of:

https://github.com/SMUELDigital/DVD-Rip-Automation-Script

All credit to SMUELDigital for the original idea and foundation.

This fork significantly expands the functionality with:
- OMDb-powered title detection
- Jellyfin-compatible folder structure (Movies/Title (Year)/Title (Year).mkv)
- Intelligent DVD volume name normalization
- Automatic cleanup of temporary files
- Subtitle preservation (no burn-in)
- macOS-specific DVD handling
- Automatic disc eject after completion

---

## Features

- DVD ripping via MakeMKV
- Transcoding via HandBrakeCLI
- Automatic movie identification via OMDb
- Jellyfin-compatible folder structure
- Keeps all subtitle tracks (DVDSUB, forced, multiple languages)
- Keeps surround audio tracks
- Cleans up raw ripped files after transcoding
- Automatically ejects DVD when finished
- Optimized for macOS (Apple Silicon and Intel)

---

## Requirements

Operating System:
- macOS (tested on Apple Silicon, works on Intel)

Hardware:
- DVD drive (USB or internal)

---

## Required software

1. MakeMKV

Used for ripping DVDs without quality loss.

Download:
https://www.makemkv.com/download/

Expected installation path:
/Applications/MakeMKV.app

Test:
/Applications/MakeMKV.app/Contents/MacOS/makemkvcon --version

---

2. HandBrakeCLI

Used for transcoding the ripped MKV into a Jellyfin-friendly format.

Install via Homebrew:
brew install handbrake

Verify:
HandBrakeCLI --version

Expected path on Apple Silicon:
/opt/homebrew/bin/HandBrakeCLI

---

3. Python

Python 3.10 or newer is recommended.

Install if needed:
brew install python

---

4. Python dependencies

Install required module:
pip3 install python-dotenv

---

## OMDb API Key (Required)

This script uses OMDb to automatically identify movies and generate correct folder names.

Important note:

Although OMDb offers a free API tier, all development and testing of this script has been done using a paid API key.

Free keys are rate-limited and unreliable. Correct behavior cannot be guaranteed with a free API key.

---

Support OMDb via Patreon (Recommended)

OMDb is maintained by a small team and relies on community support.

Patreon:
https://www.patreon.com/omdb

Cost: approximately 1–2 EUR per month  
Provides a stable API key  
Helps keep OMDb maintained

---

Create .env file

In the same directory as dvd_rip.py, create a file named:
.env

Add:
OMDB_API_KEY=your_api_key_here

Do not commit this file. Make sure .env is listed in .gitignore.

---

## Configuration

Edit paths in dvd_rip.py if needed:
TEMP_DIR = /Volumes/Jonte/rip/tmp  
MOVIES_DIR = /Volumes/nfs-share/media/rippat/movies

Recommended HandBrake preset for DVD:
HQ 720p30 Surround

This preserves:
- Native DVD resolution
- Correct aspect ratio
- Surround audio
- Reasonable file size

---

## Usage

1. Insert a DVD
2. Run:
python3 dvd_rip.py
3. Wait
4. DVD ejects automatically
5. Movie appears in Jellyfin-ready structure

---

## Scope and limitations

- Designed for DVD ripping
- Blu-ray support is experimental and future work
- No DRM removal beyond MakeMKV
- No TV series support yet

---

## Legal notice

This script is intended only for personal backups of media you legally own. Always comply with your local copyright laws.

---

## Why this exists

Most DVD ripping workflows are:
- overly manual
- poorly integrated with media servers
- fragile or outdated

This project aims to be:
- simple
- transparent
- reproducible
- Jellyfin-friendly
