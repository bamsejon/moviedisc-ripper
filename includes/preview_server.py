from flask import Flask, request, abort
import subprocess
import os
import sys

TEMP_DIR = os.environ.get("DISC_PREVIEW_DIR")
PORT = int(os.environ.get("DISC_PREVIEW_PORT", "8765"))

if not TEMP_DIR:
    print("❌ DISC_PREVIEW_DIR not set")
    sys.exit(1)

app = Flask(__name__)

def find_file_in_subdirs(filename):
    """Search for file in TEMP_DIR and its immediate subdirectories."""
    # Check TEMP_DIR root first
    direct_path = os.path.join(TEMP_DIR, filename)
    if os.path.isfile(direct_path):
        return direct_path

    # Search in immediate subdirectories (checksum folders)
    try:
        for entry in os.listdir(TEMP_DIR):
            subdir = os.path.join(TEMP_DIR, entry)
            if os.path.isdir(subdir):
                candidate = os.path.join(subdir, filename)
                if os.path.isfile(candidate):
                    return candidate
    except OSError:
        pass

    return None


@app.route("/open")
def open_file():
    name = request.args.get("file")
    if not name:
        abort(400)

    # Skydda mot path traversal
    if "/" in name or ".." in name:
        abort(400)

    path = find_file_in_subdirs(name)

    if not path:
        abort(404)

    # macOS – öppna i standardspelare (VLC / IINA / QuickTime)
    subprocess.Popen(["open", path])

    # Returnera HTML som stänger fönstret automatiskt
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Opening…</title>
</head>
<body>
<script>
  // Vänta lite så macOS hinner öppna spelaren
  setTimeout(() => {
    window.close();
  }, 300);
</script>
Opening video…
</body>
</html>
"""

if __name__ == "__main__":
    app.run(port=PORT, host="127.0.0.1")