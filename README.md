# DVD Rip Automation Script

A fully automated DVD ripping and transcoding workflow for macOS, designed to produce Jellyfin-ready movie libraries with correct titles, metadata, subtitles, and folder structure.

Insert a DVD → run the script → wait → disc ejects → movie appears in Jellyfin.

---

## 🚀 Quick start (assume you’ve never used Terminal before)

This section assumes **zero prior knowledge**.
Follow the steps exactly, in order.

---

## Step 1: Open Terminal

Terminal is a built-in macOS application that lets you type commands.

To open Terminal:
1. Press **⌘ Command + Space**
2. Type **Terminal**
3. Press **Enter**

A window will open where you can type text commands.

---

## Step 2: Install required software

### 2.1. Git (required to download this project)

Git is used to download the script from GitHub.

First, check if Git is already installed.

In **Terminal**, type the following and press **Enter**:

```git --version```

If you see something like:

```git version 2.xx.x```  

then Git is already installed and you can continue.

If you see a message saying Git is not installed, macOS will usually offer to install **Command Line Developer Tools**.
Accept that prompt and wait until installation finishes.

If nothing happens, install Git manually using Homebrew (next section).


### 2.2. Homebrew (package manager for macOS)

Homebrew is used to install other tools easily.

In **Terminal**, paste this line and press **Enter**:

```/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"```

Follow the on-screen instructions.
This may take a few minutes.

After installation, verify Homebrew by typing:

```brew --version```


### 2.3. MakeMKV (DVD & Blu Ray ripping)

MakeMKV is used to read DVDs and Blu rays without quality loss.

Download and install it from:
https://www.makemkv.com/download/

After installing, verify that macOS can find it.

In **Terminal**, type **exactly**:

```/Applications/MakeMKV.app/Contents/MacOS/makemkvcon --version```

If MakeMKV is installed correctly, version information will be printed.
If you see “No such file or directory”, MakeMKV is not installed correctly.


### 2.4. HandBrakeCLI (video transcoding)

HandBrakeCLI converts the ripped video into a Jellyfin-friendly format.

Install it using Homebrew.

In **Terminal**, type:

```brew install handbrake```

When installation finishes, verify it by typing:

```HandBrakeCLI --version```


### 2.5. Python

Python is required to run the script.

Check if Python is already installed:

```python3 --version```

If you see a version number (for example Python 3.12.x), you’re good.

If not, install Python using Homebrew:

```brew install python```

---

## Step 3: Download this project

Now we will download the script from GitHub.

In **Terminal**, type these commands one line at a time:

```git clone https://github.com/bamsejon/DVD-Rip-Automation-Script.git```

```cd DVD-Rip-Automation-Script```

You are now inside the project folder.

---

## Step 4: Install required Python dependency

This script needs one extra Python module.

In **Terminal**, type:

```pip3 install python-dotenv```

---

## Step 5: Get an OMDb API key (required)

This script uses OMDb to automatically identify movies and generate correct folder names.

Important note:

Although OMDb offers a free API tier, **all development and testing of this script has been done using a paid API key**.
Free keys are rate-limited and unreliable. Correct behavior cannot be guaranteed with a free key.

### Recommended: support OMDb via Patreon

OMDb is maintained by a small team and relies on community support.

Patreon:
https://www.patreon.com/omdb

Cost: approximately 1–2 EUR per month  
Provides a stable API key  
Helps keep OMDb maintained

After you have registered as a Patreon or requested a free API key you will recieve it to your registered email. 

---

## Step 6:  Edit the .env file (using Terminal)

You now need to edit the .env.example file, add your OMDb API key and save it as .env

Important:
	•	Files starting with a dot (.) are hidden in macOS Finder
	•	You should edit this file using Terminal

Make sure you are in the project directory

In Terminal, go to the project folder:

```cd DVD-Rip-Automation-Script```


Verify that the .env.example file exists:
```ls -a```

You should see .env.example in the list.


Open the .env.example file for editing

Open the file in a simple terminal editor:

```nano .env.example```
The screen will switch to a text editor.


Step 9: Add your OMDb API key

Inside the editor, add or update this line:
```OMDB_API_KEY=your_api_key_here````

Replace your_api_key_here with your actual OMDb API key.

Step 10: Save and exit

In nano:
	•	Press Ctrl + O → save
    •   Rename the file to .env
	•	Press Enter → confirm
	•	Press Ctrl + X → exit

You are now back in Terminal.

---

## Step 7: Edit the paths in the scropt (where files are stored)
Before running the script, you may need to adjust where temporary files and finished movies are stored.

This is done by editing the Python script directly.

### 7.1. Make sure you are in the project directory
In Terminal, go to the project folder:

```cd DVD-Rip-Automation-Script````

Verify that the script exists:

```ls````

You should see a file named:

```dvd_rip.py````


### 7.2. Open the script for editing
Open the script using a simple terminal editor:

```nano dvd_rip.py````

The screen will switch to a text editor.


### 7.3. Locate the path configuration section
Scroll down (use the arrow keys) until you find a section that looks like this:

```TEMP_DIR = "/Volumes/Jonte/rip/tmp"```
```MOVIES_DIR = "/Volumes/nfs-share/media/rippat/movies"````

These paths control where files are stored.


### 7.4. Understand what each path means
TEMP_DIR

```TEMP_DIR = "/Volumes/Jonte/rip/tmp"````

This directory is used for:
	•	Raw MKV files directly from MakeMKV
	•	Temporary files during ripping

Requirements:
	•	Must exist or be creatable by the script
	•	Must have enough free disk space (A Blu Ray could take up to 50-60 GB)
	•	Files here are automatically deleted after transcoding

Example alternatives: 

```TEMP_DIR = "/Users/yourname/Movies/rip_tmp"````

or

```TEMP_DIR = "/Volumes/ExternalSSD/rip_tmp"````


MOVIES_DIR

```MOVIES_DIR = "/Volumes/nfs-share/media/rippat/movies"````

This is the final output location, make sure that you have mounted your Jellyfin media folder to your mac.

The script will create a Jellyfin-compatible structure like:

```Movies/                       ```
```└── Movie Title (Year)/       ```
```    └── Movie Title (Year).mkv```

Requirements:
	•	Should be your Jellyfin movie library
	•	Must be writable
	•	Can be local or network storage (SMB/NFS/etc)

Example alternatives:

```MOVIES_DIR = "/Volumes/media-shared/Movies"````

or

```MOVIES_DIR = "/Volumes/MediaServer/Movies"```


### 7.5. Edit the paths
Using the keyboard:
	1.	Move the cursor to the path you want to change
	2.	Edit the text directly
	3.	Be careful to keep the quotes (")

Example:

```TEMP_DIR = "/Users/jon/Movies/dvd_tmp"```
```MOVIES_DIR = "/Volumes/Media/Movies"  ````


### 7.6 Save and exit
In nano:
	•	Press Ctrl + O → save
	•	Press Enter → confirm
	•	Press Ctrl + X → exit

You are now back in Terminal.


### 7.7 Verify paths exist (recommended)
Check that the directories exists:

```ls "/Users/jon/Movies"´´´

## Step 8: Run the script

1. Insert a DVD into your DVD drive
2. Go back to **Terminal**
3. Make sure you are inside the `DVD-Rip-Automation-Script` folder

Run the script by typing:

```python3 dvd_rip.py```

---

## What happens next

The script will automatically:

- Detect the disc
- Identify the movie via OMDb
- Rip the disc using MakeMKV
- Transcode with HandBrake
- Preserve all subtitles (no burn-in)
- Preserve surround audio
- Clean up temporary files
- Eject the disc automatically
- Create a Jellyfin-ready movie file

---

## 📁 Output structure (Jellyfin-compatible)

Movies/
└── Alien Resurrection (1997)/
    └── Alien Resurrection (1997).mkv

---

## Project origin & credit

This project is a fork and extended rewrite of:

https://github.com/SMUELDigital/DVD-Rip-Automation-Script

All credit to SMUELDigital for the original idea and foundation.

This fork significantly expands the functionality with:
- OMDb-powered title detection
- Jellyfin-compatible folder structure
- Intelligent disc volume name normalization
- Automatic cleanup of temporary files
- Subtitle preservation (no burn-in)
- macOS-specific disc handling
- Automatic disc eject after completion

---

## 🌀 Vibe-coded project (powered by long conversations with local LLMs and ChatGPT)

This project is unapologetically vibe-coded.

There were no strict specifications, no formal design documents, and no predefined architecture.

Instead, development happened through:
- Ripping real DVDs and Blu-rays
- Hitting real-world edge cases
- Iterating until things worked (and felt right)
- Long, exploratory discussions with local LLMs and ChatGPT
- Refactoring ideas mid-conversation when better approaches emerged

Local LLMs were used whenever possible, but ChatGPT played a crucial role simply because
there aren’t enough GPUs available locally to run everything at the scale and speed needed.

Sometimes the most pragmatic solution is to offload the thinking, not the compute.

No specs.  
No ceremony.  
No spare GPUs.  

Just vibes, local LLMs, ChatGPT, and working DVD rips.

---

## Legal notice

This script is intended only for personal backups of media you legally own.  
Always comply with your local copyright laws.