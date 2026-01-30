# MovieDisc Ripper

A fully automated DVD and Blu-ray ripping and transcoding workflow for macOS, designed to produce Jellyfin-ready movie libraries with correct titles, metadata, subtitles, and folder structure.

Insert a DVD or Blu-ray → run the script → wait → disc ejects → movie appears in Jellyfin.

---

## 🌐 Keepedia Integration (Recommended)

**Keepedia** is a companion web service that makes setup easier and tracks your ripped collection.

### Why use Keepedia?

- **Easy configuration** - Set all paths and settings via web interface
- **Track your collection** - See all discs you've ripped in one place
- **Pre-configured installer** - Download a ZIP with your settings already applied
- **Community disc database** - Help identify discs faster

### Quick Start with Keepedia

1. **Create an account** at [https://keepedia.org](https://keepedia.org)
2. **Configure your settings** at [https://keepedia.org/settings](https://keepedia.org/settings)
   - Set your output path (where movies go)
   - Set your temp path (needs ~50GB free)
   - Configure HandBrake presets and paths
3. **Download the installer** from [https://keepedia.org/download](https://keepedia.org/download)
4. **Run the installer:**
   ```bash
   cd keepedia-ripper
   bash install.sh
   ```
5. **Start ripping:**
   ```bash
   cd ripper
   source venv/bin/activate
   python moviedisc_ripper.py
   ```

Your ripped discs will automatically appear in your Keepedia dashboard!

---

## 🔧 Manual Setup (Without Keepedia)

If you prefer not to use Keepedia, follow the traditional setup below.

### Prerequisites

- **macOS, Linux, or Windows**
- **Python 3.8+**
- **MakeMKV** - Download from [makemkv.com](https://www.makemkv.com/download/)
- **HandBrakeCLI** - Command-line version of HandBrake
- **MKVToolNix** - For setting track metadata (language, commentary labels)

### Platform-Specific Installation

#### macOS (Homebrew)
```bash
# Install Homebrew if not installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install dependencies
brew install python handbrake mkvtoolnix

# Install MakeMKV manually from https://www.makemkv.com/download/
```

#### Linux (Debian/Ubuntu)
```bash
# Install dependencies
sudo apt update
sudo apt install python3 python3-pip python3-venv handbrake-cli mkvtoolnix

# Install MakeMKV (manual installation)
# Download from https://www.makemkv.com/download/ and follow instructions
# Or use the snap: sudo snap install makemkv
```

#### Linux (Fedora/RHEL)
```bash
# Install dependencies
sudo dnf install python3 python3-pip HandBrake-cli mkvtoolnix

# Install MakeMKV from https://www.makemkv.com/download/
```

#### Windows
1. **Python**: Download from [python.org](https://www.python.org/downloads/) (check "Add to PATH")
2. **MakeMKV**: Download from [makemkv.com](https://www.makemkv.com/download/)
3. **HandBrakeCLI**: Download from [handbrake.fr](https://handbrake.fr/downloads2.php)
4. **MKVToolNix**: Download from [mkvtoolnix.download](https://mkvtoolnix.download/downloads.html)

> **Windows Note:** Add HandBrakeCLI and mkvpropedit to your PATH, or set full paths in your settings.

### Installation

```bash
# Clone the repository
git clone https://github.com/bamsejon/DVD-Rip-Automation-Script.git
cd DVD-Rip-Automation-Script

# Install Python dependencies
pip3 install python-dotenv requests

# Create .env file
cp .env.example .env
nano .env  # Configure your paths
```

### Configuration

Edit `moviedisc_ripper.py` to set your paths:

```python
TEMP_DIR = "/path/to/temp"      # Needs ~50GB free space
MOVIES_DIR = "/path/to/movies"  # Your Jellyfin library
```

### Usage

```bash
# Insert a disc, then run:
python3 moviedisc_ripper.py
```

---

## 🔄 How It Works

1. **Disc Detection** - Automatically detects DVD or Blu-ray
2. **Identification** - Checks DiscFinder API, then TMDB for movie details
3. **Ripping** - MakeMKV extracts all titles
4. **Audio Analysis** - Detects commentary tracks by analyzing dynamic range
5. **Smart Track Selection** - Auto-selects best audio (5.1 > stereo), respects your preferences
6. **Title Selection** - Picks the main movie (≥45 minutes)
7. **Transcoding** - HandBrake compresses with quality presets
8. **Track Metadata** - mkvpropedit sets language and "Commentary" labels in final MKV
9. **Cover Art** - Downloads poster/backdrop in your preferred language
10. **Organization** - Creates Jellyfin/Plex-compatible folder structure
11. **Cleanup** - Removes temp files, ejects disc

---

## 📁 Output Structure

```
Movies/
└── Alien Resurrection (1997)/
    ├── Alien Resurrection (1997).mkv
    ├── poster.jpg
    ├── backdrop.jpg
    └── banner.jpg
```

---

## ⚙️ Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `USER_TOKEN` | Keepedia API token | Optional |
| `DISCFINDER_API` | API URL (usually not needed) | `https://disc-api.bylund.cloud` |
| `KEEPEDIA_WEB` | Web URL (usually not needed) | `https://keepedia.org` |
| `OUTPUT_PATH` | Final movie location | `/Volumes/Media/Movies` |
| `TEMP_PATH` | Temp rip location | `/tmp/rip` |
| `MAKEMKV_PATH` | Path to makemkvcon | `/Applications/MakeMKV.app/Contents/MacOS/makemkvcon` |
| `HANDBRAKE_PATH` | Path to HandBrakeCLI | `/opt/homebrew/bin/HandBrakeCLI` |
| `HANDBRAKE_PRESET_DVD` | DVD transcode preset | `HQ 720p30 Surround` |
| `HANDBRAKE_PRESET_BLURAY` | Blu-ray transcode preset | `HQ 1080p30 Surround` |

---

## 🆘 Troubleshooting

### "No disc detected"
Make sure your disc is mounted in Finder. Check `/Volumes/` for the disc.

### "MakeMKV failed"
- Is MakeMKV installed and licensed?
- Is the disc scratched or copy-protected?

### "ModuleNotFoundError"
Run: `pip3 install python-dotenv requests`

---

## 🙏 Credits

This project is a fork of [SMUELDigital/DVD-Rip-Automation-Script](https://github.com/SMUELDigital/DVD-Rip-Automation-Script).

Extended with:
- Keepedia integration for collection tracking
- TMDB-powered title detection (no API key needed)
- DiscFinder API for community disc database
- Intelligent disc fingerprinting
- Cover art download
- Jellyfin-compatible output structure

---

## ⚖️ Legal Notice

This script is intended only for personal backups of media you legally own.
Always comply with your local copyright laws.
