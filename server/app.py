"""
Temporary Chat — Web Server
---------------------------
This is the piece that has to run somewhere reachable on the internet
(a small cloud host, not your laptop) so that room links work for
anyone, at any time, even when your own computer is off.

The admin console (New Room / Delete / Send as Admin / notification
sounds) now lives in a SEPARATE app — admin_app/admin_gui.py — which
connects to this server remotely over Socket.IO using an admin key.
That's what makes this "not locally hosted": the server runs on a
host like Render/Railway/Fly.io, and you (the admin) can control it
from your own machine from anywhere, while visitors use the links.

Everything still lives only in RAM (the `rooms` dict). Restart this
process and every room + message is gone for good — nothing is
written to disk.

--------------------------------------------------------------------
Environment variables:
  ADMIN_KEY   Secret the admin app must present to control rooms.
              REQUIRED in production — set it in your host's
              dashboard as an environment variable. If unset, a
              random one is generated and printed to the server log
              once at startup (fine for quick testing only).
  PORT        Port to listen on (most hosts set this for you).
--------------------------------------------------------------------
Local run (for testing only):
    pip install -r requirements.txt
    python app.py

Production (see README.md for step-by-step hosting instructions):
    gunicorn --worker-class eventlet -w 1 app:app
--------------------------------------------------------------------
"""

import eventlet
eventlet.monkey_patch()

import os
import secrets
import threading
import time
from datetime import datetime

from flask import Flask, render_template, request
from flask_socketio import SocketIO, join_room, emit

app = Flask(__name__)
app.config["SECRET_KEY"] = secrets.token_hex(16)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

ADMIN_KEY = os.environ.get("ADMIN_KEY")
if not ADMIN_KEY:
    ADMIN_KEY = secrets.token_urlsafe(16)
    print("=" * 70)
    print("No ADMIN_KEY environment variable set. Generated one for you:")
    print(f"  ADMIN_KEY = {ADMIN_KEY}")
    print("Set this as a real env var on your host for production use,")
    print("so the key doesn't change every time the server restarts.")
    print("=" * 70)

# ---------------------------------------------------------------------------
# In-memory store. Nothing here ever touches disk.
# rooms[room_hash] = {
#   "label": str,
#   "messages": [ {who, text, ts}, ... ],
#   "users": { sid: display_name },
#   "created": epoch_seconds,
# }
# ---------------------------------------------------------------------------
rooms = {}
rooms_lock = threading.Lock()
ADMIN_NAME = "Admin"

# sids (in the /admin namespace) that have successfully authenticated
authenticated_admins = set()
admins_lock = threading.Lock()


def new_hash():
    return secrets.token_urlsafe(12)  # ~96 bits, effectively unguessable


def timestamp():
    return datetime.now().strftime("%H:%M:%S")


def snapshot_rooms():
    with rooms_lock:
        return [
            {
                "hash": h,
                "label": r["label"],
                "users": len(r["users"]),
                "messages": len(r["messages"]),
                "age_min": int((time.time() - r["created"]) / 60),
            }
            for h, r in rooms.items()
        ]


def broadcast_rooms_update():
    socketio.emit("rooms_update", snapshot_rooms(), namespace="/admin")


def broadcast_admin_message(room_hash, entry):
    """Let every connected admin app see every message, in every room,
    so it can show it and (if it's not from Admin) play a notification."""
    socketio.emit("message", {"room": room_hash, **entry}, namespace="/admin")


# ---------------------------------------------------------------------------
# Web routes (visitor side)
# ---------------------------------------------------------------------------
@app.route("/r/<room_hash>")
def room_page(room_hash):
    with rooms_lock:
        exists = room_hash in rooms
    if not exists:
        return render_template("gone.html"), 404
    return render_template("chat.html", room_hash=room_hash)


@app.route("/")
def index():
    return "Chat server is running. Ask the admin for a room link.", 200


@app.route("/health")
def health():
    # Handy for host uptime checks.
    return {"status": "ok"}, 200


# ---------------------------------------------------------------------------
# Socket.IO — default namespace: visitors (browser <-> server)
# ---------------------------------------------------------------------------
@socketio.on("join")
def on_join(data):
    room_hash = data.get("room")
    name = (data.get("name") or "Anonymous").strip()[:20] or "Anonymous"

    with rooms_lock:
        if room_hash not in rooms:
            emit("gone")
            return
        rooms[room_hash]["users"][request.sid] = name
        history = list(rooms[room_hash]["messages"])

    join_room(room_hash)
    emit("history", history)
    join_entry = {"who": "System", "text": f"{name} joined.", "ts": timestamp()}
    emit("message", join_entry, room=room_hash)
    broadcast_admin_message(room_hash, join_entry)
    broadcast_rooms_update()


@socketio.on("send_message")
def on_send_message(data):
    room_hash = data.get("room")
    name = (data.get("name") or "Anonymous").strip()[:20] or "Anonymous"
    text = (data.get("text") or "").strip()[:2000]
    if not text:
        return
    with rooms_lock:
        if room_hash not in rooms:
            emit("gone")
            return
        entry = {"who": name, "text": text, "ts": timestamp()}
        rooms[room_hash]["messages"].append(entry)

    emit("message", entry, room=room_hash)
    broadcast_admin_message(room_hash, entry)
    broadcast_rooms_update()


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    with rooms_lock:
        for room_hash, r in rooms.items():
            if sid in r["users"]:
                name = r["users"].pop(sid)
                entry = {"who": "System", "text": f"{name} left.", "ts": timestamp()}
                socketio.emit("message", entry, room=room_hash)
                broadcast_admin_message(room_hash, entry)
                break
    broadcast_rooms_update()


# ---------------------------------------------------------------------------
# Socket.IO — /admin namespace: the remote admin desktop app connects here
# ---------------------------------------------------------------------------
def _require_admin(sid):
    with admins_lock:
        return sid in authenticated_admins


@socketio.on("connect", namespace="/admin")
def admin_connect():
    pass  # wait for "auth" before trusting this connection


@socketio.on("auth", namespace="/admin")
def admin_auth(data):
    key = (data or {}).get("key", "")
    sid = request.sid
    if secrets.compare_digest(key, ADMIN_KEY):
        with admins_lock:
            authenticated_admins.add(sid)
        emit("auth_ok")
        emit("rooms_update", snapshot_rooms())
    else:
        emit("auth_fail")


@socketio.on("disconnect", namespace="/admin")
def admin_disconnect():
    with admins_lock:
        authenticated_admins.discard(request.sid)


@socketio.on("create_room", namespace="/admin")
def admin_create_room(data):
    if not _require_admin(request.sid):
        emit("auth_fail")
        return
    label = (data or {}).get("label", "") or "(no label)"
    room_hash = new_hash()
    with rooms_lock:
        rooms[room_hash] = {
            "label": label,
            "messages": [],
            "users": {},
            "created": time.time(),
        }
    emit("room_created", {"hash": room_hash, "label": label})
    broadcast_rooms_update()


@socketio.on("delete_room", namespace="/admin")
def admin_delete_room(data):
    if not _require_admin(request.sid):
        emit("auth_fail")
        return
    room_hash = (data or {}).get("room")
    with rooms_lock:
        existed = rooms.pop(room_hash, None) is not None
    if existed:
        socketio.emit("gone", room=room_hash)
        emit("room_deleted", {"room": room_hash})
        broadcast_rooms_update()


@socketio.on("get_messages", namespace="/admin")
def admin_get_messages(data):
    if not _require_admin(request.sid):
        emit("auth_fail")
        return
    room_hash = (data or {}).get("room")
    with rooms_lock:
        r = rooms.get(room_hash)
        messages = list(r["messages"]) if r else []
    emit("messages", {"room": room_hash, "messages": messages})


@socketio.on("send_message", namespace="/admin")
def admin_send_message(data):
    if not _require_admin(request.sid):
        emit("auth_fail")
        return
    room_hash = (data or {}).get("room")
    text = (data.get("text") or "").strip()[:2000]
    if not text:
        return
    with rooms_lock:
        if room_hash not in rooms:
            return
        entry = {"who": ADMIN_NAME, "text": text, "ts": timestamp()}
        rooms[room_hash]["messages"].append(entry)
    socketio.emit("message", entry, room=room_hash)  # to visitors
    broadcast_admin_message(room_hash, entry)  # to admin apps (incl. this one)
    broadcast_rooms_update()


if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 5000))
    print(f"Starting locally on http://localhost:{PORT} (for testing only —")
    print("see README.md to deploy this so links work for everyone).")
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
