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
   - Add your OMDB API key
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

- **macOS** (tested on Ventura/Sonoma)
- **Git** - `xcode-select --install`
- **Python 3.8+** - `brew install python`
- **MakeMKV** - Download from [makemkv.com](https://www.makemkv.com/download/)
- **HandBrakeCLI** - `brew install handbrake`
- **OMDB API Key** - Get one at [omdbapi.com](https://www.omdbapi.com/apikey.aspx)

> **Note:** Only the Patreon tier OMDB API key (1000 req/day) is tested and confirmed working.

### Installation

```bash
# Clone the repository
git clone https://github.com/bamsejon/DVD-Rip-Automation-Script.git
cd DVD-Rip-Automation-Script

# Install Python dependencies
pip3 install python-dotenv requests

# Create .env file
cp .env.example .env
nano .env  # Add your OMDB_API_KEY
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
2. **Identification** - Checks DiscFinder API, then OMDB
3. **Ripping** - MakeMKV extracts all titles
4. **Title Selection** - Picks the main movie (≥45 minutes)
5. **Transcoding** - HandBrake compresses with quality presets
6. **Organization** - Creates Jellyfin-compatible folder structure
7. **Cleanup** - Removes temp files, ejects disc

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
| `OMDB_API_KEY` | Your OMDB API key | Required |
| `USER_TOKEN` | Keepedia API token | Optional |
| `OUTPUT_PATH` | Final movie location | `/Volumes/Media/Movies` |
| `TEMP_PATH` | Temp rip location | `/tmp/rip` |
| `MAKEMKV_PATH` | Path to makemkvcon | `/Applications/MakeMKV.app/Contents/MacOS/makemkvcon` |
| `HANDBRAKE_PATH` | Path to HandBrakeCLI | `/opt/homebrew/bin/HandBrakeCLI` |
| `HANDBRAKE_PRESET_DVD` | DVD transcode preset | `HQ 720p30 Surround` |
| `HANDBRAKE_PRESET_BLURAY` | Blu-ray transcode preset | `HQ 1080p30 Surround` |

---

## 🆘 Troubleshooting

### "OMDB_API_KEY not set"
Create a `.env` file with your API key, or configure it at keepedia.org/settings

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
- OMDb-powered title detection
- DiscFinder API for community disc database
- Intelligent disc fingerprinting
- Cover art download
- Jellyfin-compatible output structure

---

## ⚖️ Legal Notice

This script is intended only for personal backups of media you legally own.
Always comply with your local copyright laws.
