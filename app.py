"""
Console-Controlled Temporary Chat
---------------------------------
You run this script. It:
  1. Serves a website (via Flask + Socket.IO) that visitors open with a
     random, unguessable link like:  http://<your-address>/r/aZ9k3Qp7Lm2Xr
  2. Lets YOU watch and send messages from this terminal — you're a
     participant, driven entirely from Python, not from a browser.
  3. Lets YOU delete a room from the terminal. The moment you do, the link
     stops working for everyone ("This chat is no longer available").

Everything lives in RAM only (the `rooms` dict below). Stop the script and
every room + message is gone.

--------------------------------------------------------------------------
Run it:
    pip install -r requirements.txt
    python app.py

Then, to make the link reachable by other people (not just localhost),
expose port 5000 with a free tunnel — see README.md. Two good options:
    cloudflared tunnel --url http://localhost:5000
    npx localtunnel --port 5000
--------------------------------------------------------------------------
"""

import secrets
import threading
import time
from datetime import datetime

from flask import Flask, render_template, request, abort
from flask_socketio import SocketIO, join_room, emit

app = Flask(__name__)
app.config["SECRET_KEY"] = secrets.token_hex(16)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ---------------------------------------------------------------------------
# In-memory store. Nothing here ever touches disk.
# rooms[room_hash] = {
#   "label": str,               <- your own note, not shown to visitors
#   "messages": [ {who, text, ts}, ... ],
#   "users": { sid: display_name },
#   "created": epoch_seconds,
# }
# ---------------------------------------------------------------------------
rooms = {}
rooms_lock = threading.Lock()
ADMIN_NAME = "Admin"


def new_hash():
    # 16 bytes of CSPRNG randomness, url-safe -> effectively unguessable
    return secrets.token_urlsafe(12)


def timestamp():
    return datetime.now().strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# Web routes
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
    return "Console-Controlled Chat is running. Ask the admin for a room link.", 200


# ---------------------------------------------------------------------------
# Socket.IO events (browser <-> server)
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
    emit("message", {"who": "System", "text": f"{name} joined.", "ts": timestamp()}, room=room_hash)
    print(f"[{timestamp()}] + {name} joined room {room_hash}")


@socketio.on("send_message")
def on_send_message(data):
    room_hash = data.get("room")
    name = data.get("name", "Anonymous")
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
    print(f"[{timestamp()}] ({room_hash}) {name}: {text}")


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    with rooms_lock:
        for room_hash, r in rooms.items():
            if sid in r["users"]:
                name = r["users"].pop(sid)
                socketio.emit("message", {"who": "System", "text": f"{name} left.", "ts": timestamp()}, room=room_hash)
                print(f"[{timestamp()}] - {name} left room {room_hash}")
                break


# ---------------------------------------------------------------------------
# Admin actions — callable both from the CLI below AND importable elsewhere
# ---------------------------------------------------------------------------
def create_room(label=""):
    room_hash = new_hash()
    with rooms_lock:
        rooms[room_hash] = {
            "label": label or "(no label)",
            "messages": [],
            "users": {},
            "created": time.time(),
        }
    return room_hash


def admin_send(room_hash, text):
    with rooms_lock:
        if room_hash not in rooms:
            print("No such room.")
            return
        entry = {"who": ADMIN_NAME, "text": text, "ts": timestamp()}
        rooms[room_hash]["messages"].append(entry)
    socketio.emit("message", entry, room=room_hash)


def delete_room(room_hash):
    with rooms_lock:
        if room_hash not in rooms:
            print("No such room.")
            return
        rooms.pop(room_hash)
    # Tell every currently-connected browser the link is dead, then kick them.
    socketio.emit("gone", room=room_hash)
    print(f"Room {room_hash} deleted. Its link is no longer valid.")


def list_rooms():
    with rooms_lock:
        if not rooms:
            print("(no active rooms)")
            return
        for h, r in rooms.items():
            age_min = int((time.time() - r["created"]) / 60)
            print(f"  {h}   label='{r['label']}'   users={len(r['users'])}   "
                  f"messages={len(r['messages'])}   age={age_min}m")


def view_room(room_hash):
    with rooms_lock:
        if room_hash not in rooms:
            print("No such room.")
            return
        msgs = list(rooms[room_hash]["messages"])
    if not msgs:
        print("(no messages yet)")
    for m in msgs:
        print(f"  [{m['ts']}] {m['who']}: {m['text']}")


# ---------------------------------------------------------------------------
# Terminal control panel (this is YOUR chat client + admin console)
# ---------------------------------------------------------------------------
HELP_TEXT = """
Commands:
  new [label]          Create a new room. Prints the path to open, e.g. /r/aZ9k3Qp7Lm2Xr
  rooms                List all active rooms
  view <hash>           Print full message history of a room
  send <hash> <text>    Send a message into a room as "Admin"
  delete <hash>         Delete a room -> its link stops working immediately
  help                  Show this help
  quit                  Shut down everything and exit
"""


def cli_loop(base_url):
    print(HELP_TEXT)
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            raw = "quit"

        if not raw:
            continue
        parts = raw.split(" ", 2)
        cmd = parts[0].lower()

        if cmd == "new":
            label = parts[1] if len(parts) > 1 else ""
            h = create_room(label)
            print(f"Created room. Share this link: {base_url}/r/{h}")

        elif cmd == "rooms":
            list_rooms()

        elif cmd == "view" and len(parts) > 1:
            view_room(parts[1])

        elif cmd == "send" and len(parts) > 2:
            admin_send(parts[1], parts[2])

        elif cmd == "delete" and len(parts) > 1:
            delete_room(parts[1])

        elif cmd == "help":
            print(HELP_TEXT)

        elif cmd == "quit":
            print("Shutting down.")
            # os._exit avoids waiting on lingering socket threads
            import os
            os._exit(0)

        else:
            print("Unrecognized command. Type 'help' for the list of commands.")


if __name__ == "__main__":
    PORT = 5000
    server_thread = threading.Thread(
        target=lambda: socketio.run(
            app, host="0.0.0.0", port=PORT, debug=False,
            use_reloader=False, allow_unsafe_werkzeug=True,
        ),
        daemon=True,
    )
    server_thread.start()
    time.sleep(1)  # give the server a moment to bind before printing the prompt
    print(f"Server running on http://localhost:{PORT}")
    print("If you're using a tunnel (cloudflared/localtunnel/ngrok), use the")
    print("public URL it gives you instead of localhost when sharing links.\n")
    cli_loop(base_url=f"http://localhost:{PORT}")
