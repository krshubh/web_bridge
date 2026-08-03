import os
import secrets
from datetime import datetime
from functools import wraps

import vercel_blob

from flask import (
    Flask, request, render_template, redirect, url_for,
    flash, jsonify, abort
)
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Vercel Functions have a hard 4.5 MB request-body limit at the infrastructure
# level — this cannot be raised from application code. Keep some headroom
# below that for multipart overhead.
MAX_CONTENT_LENGTH = 4 * 1024 * 1024  # 4 MB per request

# Restrict file types if you want. None = allow anything.
# Example: {"png", "jpg", "jpeg", "pdf", "zip", "txt"}
ALLOWED_EXTENSIONS = None

# Optional password protection (HTTP Basic Auth).
# Set the UPLOAD_PASSWORD environment variable in your Vercel project
# settings to require a password. Username can be anything.
UPLOAD_PASSWORD = os.environ.get("UPLOAD_PASSWORD", "")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(16))
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


def allowed_file(filename):
    if ALLOWED_EXTENSIONS is None:
        return True
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if UPLOAD_PASSWORD:
            auth = request.authorization
            if not auth or auth.password != UPLOAD_PASSWORD:
                return (
                    "Authentication required", 401,
                    {"WWW-Authenticate": 'Basic realm="Drop Point"'}
                )
        return f(*args, **kwargs)
    return decorated


def human_size(num_bytes):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.0f} {unit}" if unit == "B" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} PB"


def format_uploaded_at(value):
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            dt = value
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(value)


def list_blobs():
    """Every file currently in the Blob store, newest first."""
    result = vercel_blob.list({"limit": "1000"})
    blobs = result.get("blobs", [])
    blobs.sort(key=lambda b: b.get("uploadedAt", ""), reverse=True)
    return blobs


def find_blob(filename):
    return next((b for b in list_blobs() if b["pathname"] == filename), None)


@app.route("/", methods=["GET"])
@requires_auth
def index():
    blobs = list_blobs()
    entries = [{
        "name": b["pathname"],
        "size": human_size(b["size"]),
        "mtime": format_uploaded_at(b.get("uploadedAt", "")),
    } for b in blobs]
    return render_template("index.html", files=entries, upload_dir="Vercel Blob storage")


@app.route("/upload", methods=["POST"])
@requires_auth
def upload():
    if "files" not in request.files:
        flash("No files were attached to that request.", "error")
        return redirect(url_for("index"))

    uploaded_files = request.files.getlist("files")
    saved, rejected = 0, []
    existing_names = {b["pathname"] for b in list_blobs()}

    for file in uploaded_files:
        if not file or file.filename == "":
            continue
        if not allowed_file(file.filename):
            rejected.append(file.filename)
            continue

        filename = secure_filename(file.filename)
        if not filename:
            rejected.append(file.filename)
            continue

        # Avoid overwriting existing blobs with the same name
        base, ext = os.path.splitext(filename)
        candidate = filename
        counter = 1
        while candidate in existing_names:
            candidate = f"{base}_{counter}{ext}"
            counter += 1
        filename = candidate

        data = file.read()
        vercel_blob.put(filename, data, {"access": "public", "addRandomSuffix": "false"})
        existing_names.add(filename)
        saved += 1

    if saved:
        flash(f"Received {saved} file(s).", "success")
    if rejected:
        flash(f"Rejected: {', '.join(rejected)}", "error")
    if not saved and not rejected:
        flash("Nothing to upload.", "error")

    return redirect(url_for("index"))


@app.route("/files/<path:filename>")
@requires_auth
def download(filename):
    # Redirect straight to Vercel's Blob CDN rather than proxying the bytes
    # through this function — sidesteps the function response-size limit
    # entirely, and downloads come straight off the CDN.
    blob = find_blob(filename)
    if not blob:
        abort(404)
    return redirect(blob["url"])


# ---------------------------------------------------------------------------
# JSON API — used by sync_agent.py to pull new files down to another machine
# ---------------------------------------------------------------------------
@app.route("/api/files", methods=["GET"])
@requires_auth
def api_list_files():
    entries = [{
        "name": b["pathname"],
        "size": b["size"],
        "mtime": b.get("uploadedAt", ""),
        "download_url": b["url"],
    } for b in list_blobs()]
    return jsonify(entries)


@app.route("/api/files/<path:filename>", methods=["DELETE"])
@requires_auth
def api_delete_file(filename):
    blob = find_blob(filename)
    if not blob:
        return jsonify({"error": "not found"}), 404
    vercel_blob.delete([blob["url"]])
    return jsonify({"deleted": filename}), 200


if __name__ == "__main__":
    # Local testing only. Requires BLOB_READ_WRITE_TOKEN to be set
    # (see README.md — "vercel env pull" or the Vercel dashboard).
    app.run(host="0.0.0.0", port=8000, debug=False)
