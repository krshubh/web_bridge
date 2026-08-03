import os
import secrets
from datetime import datetime
from functools import wraps

from flask import (
    Flask, request, render_template, redirect, url_for,
    flash, send_from_directory, jsonify
)
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")

# Max total upload size per request (bytes). 500 MB by default.
MAX_CONTENT_LENGTH = 500 * 1024 * 1024

# Restrict file types if you want. None = allow anything.
# Example: {"png", "jpg", "jpeg", "pdf", "zip", "txt"}
ALLOWED_EXTENSIONS = None

# Optional password protection (HTTP Basic Auth).
# Set the UPLOAD_PASSWORD environment variable before starting the server
# to require a password. Username can be anything.
UPLOAD_PASSWORD = os.environ.get("UPLOAD_PASSWORD", "")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(16))
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


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


@app.route("/", methods=["GET"])
@requires_auth
def index():
    entries = []
    for name in sorted(os.listdir(UPLOAD_FOLDER)):
        if name.startswith("."):
            continue
        path = os.path.join(UPLOAD_FOLDER, name)
        if os.path.isfile(path):
            entries.append({
                "name": name,
                "size": human_size(os.path.getsize(path)),
                "mtime": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M"),
            })
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return render_template("index.html", files=entries, upload_dir=UPLOAD_FOLDER)


@app.route("/upload", methods=["POST"])
@requires_auth
def upload():
    if "files" not in request.files:
        flash("No files were attached to that request.", "error")
        return redirect(url_for("index"))

    uploaded_files = request.files.getlist("files")
    saved, rejected = 0, []

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

        dest = os.path.join(UPLOAD_FOLDER, filename)
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(dest):
            filename = f"{base}_{counter}{ext}"
            dest = os.path.join(UPLOAD_FOLDER, filename)
            counter += 1

        file.save(dest)
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
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)


# ---------------------------------------------------------------------------
# JSON API — used by sync_agent.py to pull new files down to another machine
# ---------------------------------------------------------------------------
@app.route("/api/files", methods=["GET"])
@requires_auth
def api_list_files():
    entries = []
    for name in sorted(os.listdir(UPLOAD_FOLDER)):
        if name.startswith("."):
            continue
        path = os.path.join(UPLOAD_FOLDER, name)
        if os.path.isfile(path):
            entries.append({
                "name": name,
                "size": os.path.getsize(path),
                "mtime": os.path.getmtime(path),
            })
    return jsonify(entries)


@app.route("/api/files/<path:filename>", methods=["DELETE"])
@requires_auth
def api_delete_file(filename):
    filename = secure_filename(filename)
    path = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.isfile(path):
        os.remove(path)
        return jsonify({"deleted": filename}), 200
    return jsonify({"error": "not found"}), 404


if __name__ == "__main__":
    # Dev server only. For real use, run with waitress or gunicorn (see README.md).
    app.run(host="0.0.0.0", port=8000, debug=False)
