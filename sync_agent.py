"""
Sync agent — runs on YOUR LAPTOP, not on the server.

It polls the Drop Point server every few seconds. Whenever someone uploads a
new file there, this script downloads it into the local `received/` folder
and (by default) deletes it from the server, so the server never fills up
and the laptop always ends up with a local copy.

No inbound ports needed on the laptop — it only makes outbound requests,
so this works from behind any home router, coffee-shop wifi, etc.

Setup:
    pip install requests
    python sync_agent.py
"""

import os
import time
import json
import requests
from requests.auth import HTTPBasicAuth

# ---------------- Configuration — edit these ----------------
SERVER_URL = "https://web-bridge-wheat.vercel.app/"   # the Drop Point server's address
PASSWORD = "Shubham20."                   # must match UPLOAD_PASSWORD set on the server
POLL_INTERVAL = 5                                       # seconds between checks
DELETE_FROM_SERVER = True                               # remove file from server once safely downloaded
LOCAL_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "received")
# --------------------------------------------------------------

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".synced.json")
auth = HTTPBasicAuth("sync", PASSWORD) if PASSWORD else None

os.makedirs(LOCAL_FOLDER, exist_ok=True)


def load_synced():
    """Only needed when DELETE_FROM_SERVER is False, so we don't re-download forever."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return set(json.load(f))
    return set()


def save_synced(synced):
    with open(STATE_FILE, "w") as f:
        json.dump(sorted(synced), f)


def poll_once(synced):
    resp = requests.get(f"{SERVER_URL}/api/files", auth=auth, timeout=15)
    resp.raise_for_status()
    remote_files = resp.json()

    for entry in remote_files:
        name = entry["name"]
        if name in synced:
            continue

        print(f"[new] {name} ({entry['size']} bytes) — downloading...")
        # Download straight from the Blob CDN URL the API gave us, rather
        # than routing through the server — faster, and doesn't count
        # against the server's own function limits.
        dl = requests.get(entry["download_url"], timeout=120)
        dl.raise_for_status()

        dest = os.path.join(LOCAL_FOLDER, name)
        with open(dest, "wb") as f:
            f.write(dl.content)
        print(f"      saved -> {dest}")

        if DELETE_FROM_SERVER:
            del_resp = requests.delete(f"{SERVER_URL}/api/files/{name}", auth=auth, timeout=15)
            if del_resp.ok:
                print(f"      removed from server")
            else:
                print(f"      warning: could not remove from server ({del_resp.status_code})")
        else:
            synced.add(name)


def main():
    print(f"Watching {SERVER_URL}")
    print(f"New files will be saved to: {LOCAL_FOLDER}")
    print("Press Ctrl+C to stop.\n")

    synced = load_synced() if not DELETE_FROM_SERVER else set()

    while True:
        try:
            poll_once(synced)
            if not DELETE_FROM_SERVER:
                save_synced(synced)
        except requests.exceptions.RequestException as e:
            print(f"Could not reach server ({e}) — retrying in {POLL_INTERVAL}s")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
