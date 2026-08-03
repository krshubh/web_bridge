# Drop Point (Vercel edition)

A tiny web app: open it in a browser, drag files in, they get stored in
**Vercel Blob** storage. A separate `sync_agent.py` script — run on your
laptop — polls the app and automatically pulls new files down.

```
[someone uploads] ---> [Vercel: app.py + Blob storage] <--- polls every few sec --- [your laptop: sync_agent.py]
```

Your laptop never needs a public IP or an open port for this — the agent
only makes outbound requests, so it works from any network.

```
project/
├── app.py              # Flask app — deployed to Vercel
├── templates/index.html
├── static/style.css
├── requirements.txt
├── vercel.json          # function config (timeout)
└── sync_agent.py        # runs on your laptop, not on Vercel
```

## Why this looks different from a normal Flask app

Vercel Functions are **serverless**: no persistent local disk, fresh
container per request. So instead of saving uploads to a folder, `app.py`
now saves them to **Vercel Blob**, Vercel's object storage product, using
the `vercel_blob` package. Everything else — the drag-and-drop UI, the
password gate, the `/api/files` JSON API the sync agent polls — works the
same as before.

## 1. Set up Vercel Blob storage

1. Push this project to a GitHub repo and import it in the Vercel dashboard
   (or run `vercel` from the project folder with the [Vercel CLI](https://vercel.com/docs/cli)).
2. In the project, go to **Storage → Create Database → Blob** and connect it.
   This automatically adds a `BLOB_READ_WRITE_TOKEN` environment variable to
   your project — you don't set this yourself.
3. Redeploy so the function picks up the new environment variable.

## 2. Add a password

In your Vercel project's **Settings → Environment Variables**, add:
```
UPLOAD_PASSWORD = something-only-you-know
```
Redeploy. The browser will now prompt for a username (anything) and that
password before the upload page loads.

## 3. Deploy

```bash
npm i -g vercel     # one-time
vercel               # deploy a preview
vercel --prod        # deploy to production
```
Vercel auto-detects `app.py` as a Flask entrypoint from `requirements.txt` —
no other config needed beyond `vercel.json` (already included, just sets a
30s timeout so large-ish uploads don't get cut off mid-request).

## 4. Run it locally first (optional but recommended)

```bash
pip install -r requirements.txt
vercel env pull .env.local     # pulls BLOB_READ_WRITE_TOKEN etc. from your project
export $(cat .env.local | xargs)  # or use python-dotenv
python app.py
```
Open `http://localhost:8000` and confirm a drag-and-drop upload shows up in
the manifest before relying on the deployed version.

## 5. The 4 MB file size limit — and why

Vercel Functions have a **hard 4.5 MB request/response body limit** at the
infrastructure level — this is not a setting in `app.py`, it can't be raised
by changing `MAX_CONTENT_LENGTH` or `vercel.json`. `app.py` caps uploads at
4 MB to stay safely under that, and the page rejects bigger files client-side
before they're even sent.

If you need to accept larger files, the options are:
- **Client-side direct-to-Blob upload** — the browser uploads straight to
  Vercel Blob using a short-lived token, bypassing the function entirely.
  This requires the JS `@vercel/blob/client` SDK on the frontend rather than
  a plain HTML form — a bigger rework than this app currently does. Ask if
  you'd like this built out.
- **Go back to a VPS** instead of Vercel — a real server has no such limit.
  (The previous version of this project, which saves straight to a VPS's
  local disk, doesn't have this constraint — happy to hand that version back
  over if you'd rather deploy it that way.)

Downloads aren't affected by this limit: the `/files/<name>` route redirects
straight to the file's Blob CDN URL rather than streaming bytes through the
function, so downloads of any size work fine.

## 6. Auto-download uploads to your laptop

Run `sync_agent.py` on your laptop (not on Vercel). It polls `/api/files`
every few seconds, downloads anything new straight from Blob's CDN into a
local `received/` folder, then deletes it from Blob storage via the API.

**On your laptop:**
```bash
pip install requests
```
Edit the top of `sync_agent.py`:
```python
SERVER_URL = "https://your-project.vercel.app"
PASSWORD = "the same UPLOAD_PASSWORD you set in Vercel"
```
Then run it:
```bash
python sync_agent.py
```
Leave it running (or wire it up as a background task — Task Scheduler on
Windows, `systemd`/`launchd` elsewhere). Anything uploaded on the page shows
up in `received/` within `POLL_INTERVAL` seconds (default 5), and is removed
from Blob storage once safely downloaded — so your Blob storage usage stays
near zero between syncs.

Set `DELETE_FROM_SERVER = False` in `sync_agent.py` if you'd rather keep
copies in both places; it then tracks what's already synced in
`.synced.json` so it won't re-download the same file forever.

## Notes on the app itself

- **File size limit**: 4 MB per file — see section 5 above for why, and the
  options if you need more.
- **File types**: all types allowed by default. Restrict via
  `ALLOWED_EXTENSIONS` in `app.py`, e.g. `{"png", "jpg", "pdf", "zip"}`.
- **Filenames**: sanitized with `secure_filename`; duplicates get a `_1`,
  `_2`… suffix rather than overwriting.
- **Access model**: blobs are uploaded with `access: "public"`, meaning
  anyone with the exact (randomly-pathed) blob URL can fetch it directly,
  bypassing the app's password. The password still gates the upload page and
  the `/api/files` listing/delete endpoints — it's the same "unlisted but not
  truly private" tradeoff as most simple file-drop tools. For stronger
  guarantees, Vercel's **Private Blob** requires authenticated reads through
  a Vercel Function — a further change if you want it.
