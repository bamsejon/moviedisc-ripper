# Keepedia Release Plan

## Released

### v1.0 - Initial Release ✅
- Movie ripping with OMDB
- Metadata admin UI
- Track selection (audio/subtitles)
- Extras support with Plex naming
- Preview server for ripped files

### v1.1 - TMDB Migration ✅
- Replace OMDB with TMDB
- Proxy endpoints in disc-api (`/tmdb/find`, `/tmdb/movie`, `/tmdb/search`)
- No API key required for users
- Server-side TMDB API key

---

## Upcoming Releases

### v1.2 - Media Server Notifications
- Settings: Configure Jellyfin/Plex URL + API token
- After encode → trigger library refresh via API
- Targeted scan (specific folder only)
- Support for Jellyfin + Plex

### v1.3 - Multi-disc Support
- Prompt "Main disc / Secondary disc" after movie identification
- Link secondary disc to main disc via IMDB ID
- `parent_checksum` + `disc_number` in database
- Extras from disc 2 → same folder with `[Disc 2]` prefix

### v1.4 - TV Series Support
- Series mode in script (minimal input: series name + season)
- Metadata admin UI for episode mapping
- Auto-match on duration
- Plex naming: `Show - S01E01 - Title.mkv`
- TMDB integration for episode data

### v1.5 - Multi-language Support
- Multi-language support for keepedia.org
- Swedish, English, + more languages
- Language selection in settings
- Translation of metadata admin UI
- Localized error messages in ripper script

---

## Future Features (backlog)

### keepedia.org

**"My Discs" Redesign - Video Store Theme**
- Retro video store vibe
- Views: Shelf view, List view, Detail view
- Sorting: Genre, Year, Format, A-Z
- Filter by DVD/Blu-ray/4K
- "New Arrivals" and "Staff Picks" sections

**3D Cases**
- Cover wraps around front + spine
- Hover → rotate and show spine
- Click → open case (animation)
- Different thickness for DVD/Blu-ray/Box-set
- Glossy plastic effect

**Physical Shelf Organizer**
- Define your shelf (slots, shelves)
- Generate placement guide based on sorting
- Print labels for shelf slots
- "Where should I put this?" - suggestions for new disc
- Visualization of physical shelf with covers

---

### Jellyfin/Plex Plugin

**Keepedia Collection Plugin**
- Display ripped discs as physical cases
- DVD/Blu-ray/4K badges
- Multi-disc boxes as box-set
- Clear extras section with categories
- Show which disc each extra comes from
- Link to keepedia.org for more info
- Publish in plugin marketplace

---

### Raw Output / ISO Mode

**Rip Without Encoding**
- Settings option: Output format (Encoded / Raw MKV / ISO)
- Raw MKV: Direct output from MakeMKV without HandBrake
- ISO: Full disc backup as .iso file
- Useful for archival and original quality preservation
- Per-disc override in metadata admin UI
- Show estimated file sizes for each option

**ISO Output Features**
- Mount and play ISO files directly in media servers
- Preserve original menus and structure
- Option to keep both ISO and encoded version
- Compression options for ISO (none / gzip)

---

### Smart Metadata Detection

**OCR from Back Cover**
- Analyze scanned wrap/back cover with OCR
- Extract list of special features from text
- Match OCR text against title durations for auto-identification
- Suggest content_type (behind-the-scenes, deleted scenes, etc.)
- Multi-language support (Swedish, English, etc.)
- Use Claude Vision API or Tesseract for OCR

**DVD/Blu-ray Menu Parsing**
- Extract menu structure from IFO files (DVD) / index.bdmv (Blu-ray)
- Map menu options to VTS/playlist files
- Read menu text to identify content
- Auto-match "Play Movie", "Special Features", "Deleted Scenes" etc.
- Pre-fill metadata based on menu navigation
- Handle sub-menus (Extras → Behind The Scenes → Item 1, 2, 3)

**Combined Intelligence**
- Correlate OCR results with menu structure
- Match title durations to descriptions ("20 min documentary" → 22:28 title)
- Confidence score for each suggestion
- Manual override in admin UI

---

### Physical Media Scanning

**Disc Art Scanning**
- Scan the physical disc surface (disc art/label)
- Extract disc number from multi-disc sets
- OCR disc label text for title/edition info
- Store disc art images in asset library
- Display disc art in collection view

**Case Insert Scanning**
- Scan case inlets (inside cover art)
- Often contains chapter listings or credits
- Extract chapter names for auto-naming
- Store as additional asset type

**Back Cover Details**
- Scan back of sleeve/cover
- Extract runtime, audio formats, subtitle languages
- Parse special features list
- Cross-reference with disc content
- Multi-language back cover support

---

### Cross-Platform Testing

**Linux Test Environment**
- Docker container with MakeMKV + HandBrake
- CI/CD pipeline for running tests
- Test against ISO backups (no physical drive needed)
- Verify checksum consistency across platforms
- Test filesystem differences (ext4, NTFS, APFS)

**Windows Test Environment**
- PowerShell setup script
- GitHub Actions runner with Windows
- Test path normalization (backslash handling)
- Test Unicode filename handling
- Verify MakeMKV CLI compatibility

---

### Ripping Station

**Bootable USB Image**
- Minimal Linux (Debian/Ubuntu LTS)
- Pre-installed: MakeMKV, HandBrake, mkvtoolnix
- Sleek GUI (Electron/Qt/Web)
- Auto-detect DVD/Blu-ray drive
- WiFi setup wizard
- Download .iso from keepedia.org

**Media Server Auto-detect**
- Find Jellyfin/Plex on network automatically
- Suggest library paths
- One-click configuration
