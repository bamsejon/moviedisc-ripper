# Keepedia / DVD-Rip-Automation Project Status

Last updated: 2026-01-26

## Project Overview

A DVD/Blu-ray ripping automation system with:
- **moviedisc_ripper.py** - Local ripping script (macOS)
- **Keepedia** (keepedia.org) - Web UI for managing disc collection and metadata
- **disc-api** - Backend API for disc lookup and metadata

## Infrastructure

| Service | Location | Access |
|---------|----------|--------|
| Keepedia web | CT 125 on proxmox02 | via `ssh proxmox01 "ssh root@10.10.10.2 'pct exec 125 -- ...'"` |
| disc-api | CT 122 on proxmox04 | via `ssh proxmox04 "pct exec 122 -- ..."` |
| PostgreSQL (discfinder) | CT 126 on proxmox01 | via `ssh proxmox01 "pct exec 126 -- sudo -u postgres psql -d discfinder"` |

Note: proxmox02 (192.168.4.11) is not directly reachable - use cluster network (10.10.10.2) via proxmox01.

## Recent Completed Work

### Script Features (moviedisc_ripper.py)
- **Health check** (`--check` flag) - Verifies all dependencies
- **Push notifications** - Pushover, Telegram, Discord when rip completes
- **OMDB API key from settings** - No need for .env if set in keepedia.org/settings
- **MakeMKV auto-registration** - Applies key from settings automatically
- **Parallel rip + encode** - Disc-specific temp directories (`/Volumes/Jonte/rip/tmp/{checksum[:16]}/`)
- **Track selection fix** - HandBrake now respects audio/subtitle track selections from metadata page
- **Audio analysis** - Commentary detection via dynamic range analysis
- **Track metadata** - mkvpropedit applies language and commentary labels

### Keepedia Web (CT 125)
- **Settings page** - Track preferences, OMDB key, MakeMKV key, HandBrake presets
- **Metadata admin** - Edit tracks, filenames, enable/disable titles
- **Info notes added** - Settings page and metadata page now explain that settings apply to future scans only

Templates location: `/opt/keepedia/templates/`
Static files: `/opt/keepedia/static/admin-ui/admin.js`

### Database Schema (discfinder)
Tables include:
- `discs` - Disc metadata (checksum, title, year, imdb_id)
- `metadata_layout_items` - Per-title track/filename info
- `user_settings` - User preferences including:
  - `omdb_api_key`, `makemkv_key`
  - `notification_service`, `pushover_*`, `telegram_*`, `discord_webhook_url`
  - `preferred_audio_languages`, `preferred_subtitle_languages`
  - `include_commentary`, `include_forced_subs`, `include_sdh_subs`
  - `audio_quality_preference`, `preferred_cover_art_language`

## Key Files

### Local (macOS)
- `/Users/jonbylund/DVD-Rip-Automation-Script/moviedisc_ripper.py` - Main script
- `/Users/jonbylund/DVD-Rip-Automation-Script/includes/makemkv_titles.py` - MakeMKV title scanning
- `/Users/jonbylund/DVD-Rip-Automation-Script/includes/metadata_layout.py` - Metadata API helpers

### Servers
- `/opt/keepedia/templates/settings.html` - Settings page template
- `/opt/keepedia/templates/metadata_admin/index.html` - Metadata editor template
- `/opt/keepedia/static/admin-ui/admin.js` - Metadata page JavaScript
- `/opt/disc-api/templates/admin/admin.js` - disc-api admin JavaScript (similar to keepedia)

## Pending / Future Work

1. **TV Series Support** - Separate output paths for movies vs series, episode naming
2. **Streaming Platform Integration** - Notify Jellyfin/Plex to scan new content
3. **Server-side notification settings** - Database columns exist, API endpoints may need work

## Common Commands

```bash
# Update script
cd /Users/jonbylund/DVD-Rip-Automation-Script && git pull

# Run health check
python3 moviedisc_ripper.py --check

# Access keepedia container
ssh proxmox01 "ssh -o StrictHostKeyChecking=no root@10.10.10.2 'pct exec 125 -- <command>'"

# Restart keepedia
ssh proxmox01 "ssh root@10.10.10.2 'pct exec 125 -- systemctl restart keepedia'"

# Access disc-api container
ssh proxmox04 "pct exec 122 -- <command>"

# Database queries
ssh proxmox01 "pct exec 126 -- sudo -u postgres psql -d discfinder -c '<SQL>'"
```

## Git Repository

- GitHub: https://github.com/bamsejon/moviedisc-ripper.git (was DVD-Rip-Automation-Script)
- Local: /Users/jonbylund/DVD-Rip-Automation-Script

## Configuration

Script uses:
- `TEMP_BASE_DIR = "/Volumes/Jonte/rip/tmp"` - Temp storage for rips
- `MOVIES_DIR = "/Volumes/nfs-share/media/rippat/movies"` - Final output
- `SMB_SHARE = "//delis.bylund.cloud/nfs-share"` - NFS mount for output
- `DISCFINDER_API = "https://discfinder-api.bylund.cloud"` - API endpoint
