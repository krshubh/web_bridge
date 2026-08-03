# Drop Point

A tiny web app: open it in a browser, drag files in, they get saved straight to disk
on whichever machine is running the server. No accounts, no cloud storage.

```
project/
├── app.py              # Flask server
├── templates/index.html
├── static/style.css
├── requirements.txt
└── uploads/            # files land here (created automatically)
```

## 1. Run it locally first

```bash
pip install -r requirements.txt
python app.py
```

Open `http://localhost:8000` — confirm you can drag a file in and see it appear
in the manifest list and in the `uploads/` folder. Do this before worrying about
the public internet part.

## 2. Run it properly (not the Flask dev server)

`python app.py` uses Flask's built-in dev server, which isn't meant to sit on
the open internet. Once local testing works, run it with **waitress** instead:

```bash
waitress-serve --host=0.0.0.0 --port=8000 app:app
```

(Linux/Mac alternative: `gunicorn -w 2 -b 0.0.0.0:8000 app:app`)

## 3. Add a password (do this before exposing it publicly)

Anyone who can reach the address can upload/download once it's on the public
internet. Set a password:

```bash
# Linux/Mac
export UPLOAD_PASSWORD="something-only-you-know"
waitress-serve --host=0.0.0.0 --port=8000 app:app

# Windows PowerShell
$env:UPLOAD_PASSWORD="something-only-you-know"
waitress-serve --host=0.0.0.0 --port=8000 app:app
```

The browser will prompt for a username (anything) and that password.

## 4. Make it reachable from the public internet

Your laptop doesn't have a public IP by default — it's behind your home
router's NAT. Pick one:

### Option A — Cloudflare Tunnel or ngrok (easiest, no router config)
Both give you a public HTTPS URL that forwards to your laptop, with no port
forwarding and no exposure of your home IP. Good default choice.

```bash
# ngrok
ngrok http 8000
# gives you something like https://random-name.ngrok-free.app
```

`cloudflared tunnel --url http://localhost:8000` works similarly and is free.

### Option B — Port forwarding on your router
1. Set your laptop to a static local IP (in router settings or OS network settings).
2. In your router admin panel, forward external port 443 (or any port) → your
   laptop's local IP, port 8000.
3. Find your public IP (search "what is my IP") or set up a free Dynamic DNS
   hostname (No-IP, DuckDNS) if your ISP changes your IP periodically.
4. Watch out for **CGNAT** — if your ISP doesn't give you a real public IP
   (common on mobile/cable plans), port forwarding won't work no matter what
   you configure. Option A sidesteps this entirely.

This option exposes the port directly, so put a reverse proxy (Caddy or
nginx) in front for HTTPS, or accept that traffic is unencrypted over plain
HTTP.

### Option C — A small cloud VM
Spin up the cheapest instance on DigitalOcean/AWS/Linode/Hetzner — these come
with a real public IP already. Copy the project over, run it there instead of
your laptop. Most reliable option if this needs to stay up long-term.

## 5. Auto-download uploads to your laptop

If the server lives on a cloud VPS (so anyone can reach it) but you want the
actual files to end up on your laptop automatically, run `sync_agent.py` on
your laptop. It polls the server every few seconds, downloads anything new
into a local `received/` folder, then deletes it from the server.

```
[someone uploads] ---> [cloud server: app.py] <--- polls every few seconds --- [your laptop: sync_agent.py]
                                                        (outbound only, no port forwarding needed on laptop)
```

Your laptop never needs an open port or a public IP for this — the agent
only makes outbound requests to the server, so it works from any network.

**On your laptop:**
```bash
pip install requests
```
Edit the top of `sync_agent.py`:
```python
SERVER_URL = "http://your-server-ip-or-domain:8000"
PASSWORD = "the same UPLOAD_PASSWORD you set on the server"
```
Then run it:
```bash
python sync_agent.py
```
Leave it running (or set it up as a background service — Task Scheduler on
Windows, `systemd`/`launchd` elsewhere) and any file someone uploads on the
server shows up in `received/` on your laptop within `POLL_INTERVAL` seconds,
by default 5.

By default the agent **deletes files off the server** once they're safely
downloaded, so the cloud server never accumulates storage. Set
`DELETE_FROM_SERVER = False` in `sync_agent.py` if you'd rather keep copies
on both ends — it'll then track what's already synced in `.synced.json` so
it doesn't re-download the same file forever.

## 6. Deploying `app.py` to a cloud VPS

Any small Ubuntu VPS works (DigitalOcean, Hetzner, AWS Lightsail, Linode —
the cheapest tier is plenty for this).

```bash
ssh you@your-server-ip

sudo apt update && sudo apt install -y python3-pip python3-venv
mkdir drop-point && cd drop-point
# copy app.py, templates/, static/, requirements.txt here (scp, git, etc.)

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export UPLOAD_PASSWORD="something-only-you-know"
waitress-serve --host=0.0.0.0 --port=8000 app:app
```

Open the port:
```bash
sudo ufw allow 8000/tcp
```
Also check your cloud provider's **security group / firewall panel** (AWS,
DigitalOcean, etc. block ports by default at the network level too, separate
from `ufw`).

To keep it running after you disconnect, wrap it in a `systemd` service:

```ini
# /etc/systemd/system/droppoint.service
[Unit]
Description=Drop Point
After=network.target

[Service]
WorkingDirectory=/home/you/drop-point
Environment=UPLOAD_PASSWORD=something-only-you-know
ExecStart=/home/you/drop-point/venv/bin/waitress-serve --host=0.0.0.0 --port=8000 app:app
Restart=always
User=you

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now droppoint
```

For HTTPS, put [Caddy](https://caddyserver.com/) in front with a domain name
pointed at the server — it gets you a free, auto-renewing certificate with a
two-line config.

## Notes on the app itself

- **File size limit**: 500 MB per request by default — change `MAX_CONTENT_LENGTH`
  in `app.py`.
- **File types**: all types allowed by default. Restrict via `ALLOWED_EXTENSIONS`
  in `app.py`, e.g. `{"png", "jpg", "pdf", "zip"}`.
- **Filenames**: sanitized with `secure_filename`, and duplicates get a `_1`,
  `_2`… suffix rather than overwriting.
- **Downloads**: every received file is listed with a download link, so the
  same page works for pulling files back off the server too.
