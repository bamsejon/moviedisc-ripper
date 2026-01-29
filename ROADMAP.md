# Keepedia Release Plan

## Releases

### v1.0 - Initial Release
- Movie ripping med OMDB
- Metadata admin UI
- Track selection (audio/subtitles)
- Extras support med Plex-naming
- Preview server för rippade filer

### v1.1 - TMDB Migration
- Ersätt OMDB med TMDB
- Proxy endpoints i disc-api (`/search/movie`, `/search/tv`)
- Ingen API-nyckel för användare
- Ta bort OMDB-inställning från settings-sidan
- Ta bort `OMDB_API_KEY` från user-modellen

### v1.2 - Media Server Notifications
- Settings: Konfigurera Jellyfin/Plex URL + API token
- Efter encode → trigga library refresh via API
- Targeted scan (bara den mappen)
- Stöd för Jellyfin + Plex

### v1.3 - Multi-disc Support
- Fråga "Main disc / Secondary disc" efter filmidentifiering
- Länka sekundär disc till huvuddisc via IMDB-id
- `parent_checksum` + `disc_number` i databas
- Extras från disc 2 → samma mapp med `[Disc 2]` prefix

### v1.4 - TV Series Support
- Serie-läge i script (minimal input: serienamn + säsong)
- Metadata admin UI för episod-mappning
- Auto-match på duration
- Plex-naming: `Show - S01E01 - Title.mkv`
- TMDB integration för episoddata

### v1.5 - Multi-language Support
- Flerspråksstöd för keepedia.org
- Svenska, Engelska, + fler språk
- Språkval i settings
- Översättning av metadata admin UI
- Lokaliserade felmeddelanden i ripper script

---

## Framtida Features (backlog)

### keepedia.org

**"My Discs" Redesign - Video Store Theme**
- Retro videobutiks-känsla
- Vyer: Hyllvy, Listvy, Detaljvy
- Sortering: Genre, År, Format, A-Ö
- Filter på DVD/Blu-ray/4K
- "New Arrivals" och "Staff Picks" sektioner

**3D-fodral**
- Cover wrappas runt framsida + rygg
- Hover → rotera och visa ryggen
- Klick → öppna fodralet (animation)
- Olika tjocklek för DVD/Blu-ray/Box-set
- Glansig plasteffekt

**Physical Shelf Organizer**
- Definiera din hylla (fack, hyllplan)
- Generera placeringsguide baserat på sortering
- Skriv ut etiketter för hyllfack
- "Var ska jag ställa denna?" - förslag för ny disc
- Visualisering av fysiska hyllan med covers

---

### Jellyfin/Plex Plugin

**Keepedia Collection Plugin**
- Visa rippade discs som fysiska fodral
- DVD/Blu-ray/4K badges
- Multi-disc boxar som box-set
- Tydlig extras-sektion med kategorier
- Visa vilken disc varje extra kommer från
- Länk till keepedia.org för mer info
- Publicera i plugin marketplace

---

### Ripping Station

**Bootbar USB-image**
- Minimal Linux (Debian/Ubuntu LTS)
- Förinstallerat: MakeMKV, HandBrake, mkvtoolnix
- Snyggt GUI (Electron/Qt/Web)
- Auto-detect DVD/Blu-ray drive
- WiFi-setup wizard
- Ladda ner .iso från keepedia.org

**Media Server Auto-detect**
- Hitta Jellyfin/Plex på nätverket automatiskt
- Föreslå bibliotekssökvägar
- Ett-klicks-konfiguration
