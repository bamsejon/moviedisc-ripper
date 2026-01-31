# includes/metadata_layout.py
import time
import requests

import os
DISCFINDER_API = os.getenv("DISCFINDER_API", "https://disc-api.bylund.cloud")


def wait_for_metadata_layout_ready(checksum: str, poll_interval: int = 5):
    """
    Blocks indefinitely until metadata_layout.status == 'ready'.
    Will retry forever on network errors - user can Ctrl+C to abort.
    """
    print("\n⏳ Waiting for metadata layout to become READY...")
    print("   Edit in browser, then mark as READY when done.")
    print("   (Press Ctrl+C to abort)\n")

    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    i = 0
    error_count = 0

    while True:
        try:
            r = requests.get(
                f"{DISCFINDER_API}/metadata-layout/{checksum}",
                timeout=10,
            )

            if r.status_code != 200:
                error_count += 1
                print(f"\r⚠️  API returned {r.status_code} (retry {error_count})...", end="", flush=True)
                time.sleep(poll_interval)
                continue

            error_count = 0
            status = r.json().get("status", "unknown")

            print(
                f"\r{spinner[i % len(spinner)]} status = {status}   ",
                end="",
                flush=True
            )
            i += 1

            if status == "ready":
                print("\n✅ Metadata layout is READY")
                return

        except requests.exceptions.Timeout:
            error_count += 1
            print(f"\r⚠️  Request timeout (retry {error_count})...     ", end="", flush=True)
        except requests.exceptions.RequestException as e:
            error_count += 1
            print(f"\r⚠️  Network error (retry {error_count})...       ", end="", flush=True)
        except KeyboardInterrupt:
            print("\n\n❌ Aborted by user")
            raise SystemExit(1)

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