# 💫 About Me:
🔭 I’m currently working on Visual Effects, Game & Video Production Tools<br>👯 I’m looking to collaborate on my repos<br>🤝 I’m looking for help with optimizing my code even more<br>🌱 I’m currently learning python, docker & ML/AI training<br>💬 Ask me about Visual Effects, 3D Asset Creation, Virtual Production & Video Production<br>


# 💻 Tech Stack:
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54) 


# 📊 GitHub Stats:
![](https://github-readme-stats.vercel.app/api?username=SMUELDigital&theme=dark&hide_border=false&include_all_commits=true&count_private=true)<br/>
![](https://github-readme-streak-stats.herokuapp.com/?user=SMUELDigital&theme=dark&hide_border=false)<br/>
![](https://github-readme-stats.vercel.app/api/top-langs/?username=SMUELDigital&theme=dark&hide_border=false&include_all_commits=true&count_private=true&layout=compact)

## 🏆 GitHub Trophies
![](https://github-profile-trophy.vercel.app/?username=SMUELDigital&theme=radical&no-frame=false&no-bg=true&margin-w=4)

---
[![](https://visitcount.itsvg.in/api?id=SMUELDigital&icon=0&color=0)](https://visitcount.itsvg.in)

<p><p>
<a href="https://www.buymeacoffee.com/https://buymeacoffee.com/smueldigital">
<img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" width="160" alt="buymeacoffee" />
</a>
</p>
</p>

---




# DVD Rip Automation Script

This repository contains a Python script to automate the process of ripping DVDs and compressing video files. It uses MakeMKV for extracting DVD content and HandBrakeCLI for compressing the ripped files into smaller sizes while retaining high quality. The script is designed for macOS systems, particularly M1/M2-based devices.

## Features
- Automatically detects available titles on the DVD.
- Rips selected titles using MakeMKV.
- Compresses ripped MKV files with HandBrakeCLI using customizable presets.
- Logs each step of the process for ease of use and debugging.

## Requirements

### System
- macOS (M1/M2 or Intel)
- A DVD drive with a DVD inserted.

### Software
- MakeMKV (for DVD ripping).
- HandBrakeCLI (for compressing MKV files).

### Python
- Python 3.6+ installed on your system.

## Setup

### Install the Required Tools:

- Install MakeMKV and ensure it’s licensed or in the trial period.
- Install HandBrakeCLI:

```bash
brew install handbrake
bash
Code kopieren
brew install handbrake
Clone the Repository:

bash
Code kopieren
git clone https://github.com/SMUELDigital/DVD-Rip-Automation-Script.git
cd dvd-rip-automation
Customize Paths:

## Update the paths for MakeMKV and HandBrakeCLI in dvd_rip.py if necessary:
python
Code kopieren
MAKE_MKV_PATH = "/Applications/MakeMKV.app/Contents/MacOS/makemkvcon"
HANDBRAKE_CLI_PATH = "/usr/local/bin/HandBrakeCLI"
Set Output Directory:

## Modify the OUTPUT_DIR variable to specify where the ripped and compressed files should be saved:
python
Code kopieren
OUTPUT_DIR = "/Users/your_user/Desktop/DVD_Output"

## Usage
Insert a DVD into your drive.
Run the script:
bash
Code kopieren
python3 dvd_rip.py
The script will:
Fetch available titles on the DVD.
Rip the first title (or another specified title).
Compress the ripped file using HandBrakeCLI.
Customization
Change Compression Preset:
Modify the preset in the compress_video() function to match your desired quality:
python
Code kopieren
compress_video(input_file, output_file, preset="Fast 1080p30")
Available presets include Fast 1080p30, H.265 1080p30, HQ 720p30, etc.

## Select a Specific Title:
The script automatically rips the first title found. You can customize this by manually specifying the desired title in the script.

## Example Output
Ripped files are saved in MKV format to the specified OUTPUT_DIR.
Compressed files are saved with the prefix compressed_ in the same directory.

## Troubleshooting
No titles found: Ensure the DVD is properly inserted and readable.
Command not found: Verify the paths for MakeMKV and HandBrakeCLI in the script.
Ripping fails: Ensure MakeMKV is licensed or in the trial period.

## License
This project is licensed under the MIT License. See the LICENSE file for details.
