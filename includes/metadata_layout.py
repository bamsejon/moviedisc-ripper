# includes/metadata_layout.py
import time
import requests

DISCFINDER_API = "https://discfinder-api.bylund.cloud"


def wait_for_metadata_layout_ready(checksum: str, poll_interval: int = 3):
    """
    Blocks until metadata_layout.status == 'ready'
    """
    print("\n⏳ Waiting for metadata layout to become READY...")
    print("   (admin selection in UI)")

    while True:
        r = requests.get(
            f"{DISCFINDER_API}/metadata-layout/{checksum}",
            timeout=5,
        )

        if r.status_code != 200:
            print("❌ Failed to fetch metadata layout status")
            print(r.text)
            raise SystemExit(1)

        status = r.json().get("status")
        print(f"   status = {status}")

        if status == "ready":
            print("✅ Metadata layout is READY")
            return

        time.sleep(poll_interval)

def ensure_metadata_layout(checksum: str, disc_type: str, movie: dict):
    payload = {
        "disc_type": disc_type,
        "imdb_id": movie.get("imdbID"),
        "title": movie.get("Title"),
        "year": movie.get("Year"),
    }

    r = requests.post(
        f"{DISCFINDER_API}/metadata-layout/{checksum}",
        json=payload,
        timeout=5,
    )

    if r.status_code in (200, 201):
        print("🆕 Metadata layout created")
        return

    if r.status_code == 409:
        print("ℹ️ Metadata layout already exists")
        return

    print("❌ Failed to ensure metadata layout")
    print(r.status_code, r.text)
    raise SystemExit(1)