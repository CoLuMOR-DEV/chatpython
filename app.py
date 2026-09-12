"""
GUI-Controlled Temporary Chat
-----------------------------
Run this script and a desktop window opens on your screen:
  - Left panel: list of active rooms (auto-refreshing).
  - "New Room" button: creates a random, unguessable link and shows it.
  - Select a room to see its live conversation on the right.
  - Type in the box at the bottom and hit Send/Enter to speak as "Admin" —
    it appears instantly in every visitor's browser.
  - "Delete" button: kills the room. Visitors immediately see
    "This chat is no longer available" and the link stops working.

Everything lives only in the `rooms` dict in RAM. Close the window (or the
script) and every room + message is gone for good — nothing is written to disk.

--------------------------------------------------------------------------
Run it:
    pip install -r requirements.txt
    python app.py

To let other people (not just your own machine) open the links, expose
port 5000 with a free tunnel — see README.md, e.g.:
    cloudflared tunnel --url http://localhost:5000
--------------------------------------------------------------------------
"""

import secrets
import threading
import time
from datetime import datetime

import tkinter as tk
from tkinter import simpledialog, messagebox, scrolledtext

from flask import Flask, render_template, request
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
    return secrets.token_urlsafe(12)  # ~96 bits, effectively unguessable


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
    return "Chat server is running. Ask the admin for a room link.", 200


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


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    with rooms_lock:
        for room_hash, r in rooms.items():
            if sid in r["users"]:
                name = r["users"].pop(sid)
                socketio.emit("message", {"who": "System", "text": f"{name} left.", "ts": timestamp()}, room=room_hash)
                break


# ---------------------------------------------------------------------------
# Admin actions — called by the GUI, but plain functions so they're testable
# on their own too.
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
            return False
        entry = {"who": ADMIN_NAME, "text": text, "ts": timestamp()}
        rooms[room_hash]["messages"].append(entry)
    socketio.emit("message", entry, room=room_hash)
    return True


def delete_room(room_hash):
    with rooms_lock:
        if room_hash not in rooms:
            return False
        rooms.pop(room_hash)
    socketio.emit("gone", room=room_hash)
    return True


def snapshot_rooms():
    """Read-only snapshot for the GUI to render: [(hash, label, user_count, msg_count, age_min), ...]"""
    with rooms_lock:
        return [
            (h, r["label"], len(r["users"]), len(r["messages"]), int((time.time() - r["created"]) / 60))
            for h, r in rooms.items()
        ]


def snapshot_messages(room_hash):
    with rooms_lock:
        r = rooms.get(room_hash)
        return list(r["messages"]) if r else None


# ---------------------------------------------------------------------------
# Desktop GUI (this is your admin console — this window IS how you access chats)
# ---------------------------------------------------------------------------
class AdminGUI:
    def __init__(self, root, base_url):
        self.root = root
        self.base_url = base_url
        self.selected_room = None
        self.room_hashes = []
        self._last_msg_count = {}

        root.title("Temporary Chat — Admin")
        root.geometry("820x520")
        root.minsize(640, 420)
        self._build_ui()
        self._tick()

    # ---- UI construction -------------------------------------------------
    def _build_ui(self):
        left = tk.Frame(self.root, width=260)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        tk.Label(left, text="Active Rooms", font=("", 11, "bold")).pack(pady=(10, 4))
        self.room_listbox = tk.Listbox(left, activestyle="dotbox")
        self.room_listbox.pack(fill="both", expand=True, padx=10)
        self.room_listbox.bind("<<ListboxSelect>>", self._on_select_room)

        btns = tk.Frame(left)
        btns.pack(fill="x", padx=10, pady=8)
        tk.Button(btns, text="New Room", command=self._new_room).pack(side="left", expand=True, fill="x", padx=(0, 4))
        tk.Button(btns, text="Delete", fg="white", bg="#c0392b", command=self._delete_selected).pack(
            side="left", expand=True, fill="x", padx=(4, 0)
        )

        tk.Label(left, text="Shareable link:", anchor="w").pack(fill="x", padx=10)
        self.link_var = tk.StringVar(value="(select or create a room)")
        link_entry = tk.Entry(left, textvariable=self.link_var, state="readonly")
        link_entry.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(left, text="Copy Link", command=self._copy_link).pack(fill="x", padx=10, pady=(0, 10))

        right = tk.Frame(self.root)
        right.pack(side="right", fill="both", expand=True)

        self.chat_box = scrolledtext.ScrolledText(right, state="disabled", wrap="word")
        self.chat_box.pack(fill="both", expand=True, padx=10, pady=10)

        send_row = tk.Frame(right)
        send_row.pack(fill="x", padx=10, pady=(0, 10))
        self.msg_entry = tk.Entry(send_row)
        self.msg_entry.pack(side="left", fill="x", expand=True)
        self.msg_entry.bind("<Return>", lambda e: self._send())
        tk.Button(send_row, text="Send", command=self._send).pack(side="left", padx=(6, 0))

        self.status_var = tk.StringVar(value=f"Server: {self.base_url}")
        tk.Label(self.root, textvariable=self.status_var, anchor="w", fg="#666").pack(fill="x", padx=10, pady=(0, 6))

    # ---- Actions -----------------------------------------------------
    def _new_room(self):
        label = simpledialog.askstring("New Room", "Optional label (just for you):", parent=self.root) or ""
        h = create_room(label)
        self._refresh_room_list()
        self._select_room(h)
        self.status_var.set(f"Created room {h}")

    def _delete_selected(self):
        if not self.selected_room:
            messagebox.showinfo("No room selected", "Select a room first.")
            return
        if messagebox.askyesno("Delete room", "Delete this room? Its link will stop working immediately."):
            delete_room(self.selected_room)
            self.status_var.set(f"Deleted room {self.selected_room}")
            self.selected_room = None
            self.link_var.set("(select or create a room)")
            self._set_chat_text("")
            self._refresh_room_list()

    def _on_select_room(self, _event):
        sel = self.room_listbox.curselection()
        if not sel:
            return
        self._select_room(self.room_hashes[sel[0]])

    def _select_room(self, room_hash):
        self.selected_room = room_hash
        self.link_var.set(f"{self.base_url}/r/{room_hash}")
        self._render_messages(force=True)

    def _copy_link(self):
        link = self.link_var.get()
        if link and link.startswith("http"):
            self.root.clipboard_clear()
            self.root.clipboard_append(link)
            self.status_var.set("Link copied to clipboard.")

    def _send(self):
        if not self.selected_room:
            messagebox.showinfo("No room selected", "Select or create a room first.")
            return
        text = self.msg_entry.get().strip()
        if not text:
            return
        admin_send(self.selected_room, text)
        self.msg_entry.delete(0, "end")
        self._render_messages(force=True)

    # ---- Rendering / polling -----------------------------------------
    def _refresh_room_list(self):
        data = snapshot_rooms()
        self.room_hashes = [d[0] for d in data]
        keep_selection = self.selected_room
        self.room_listbox.delete(0, "end")
        for h, label, users, msgs, age in data:
            self.room_listbox.insert("end", f"{h[:10]}…  [{label}]  {users} online · {msgs} msgs · {age}m")
        if keep_selection in self.room_hashes:
            self.room_listbox.selection_set(self.room_hashes.index(keep_selection))
        elif keep_selection and keep_selection not in self.room_hashes:
            # room got deleted from elsewhere (or expired) — clear the view
            self.selected_room = None
            self.link_var.set("(select or create a room)")
            self._set_chat_text("(this room no longer exists)")

    def _render_messages(self, force=False):
        if not self.selected_room:
            return
        msgs = snapshot_messages(self.selected_room)
        if msgs is None:
            return
        count = len(msgs)
        if not force and self._last_msg_count.get(self.selected_room) == count:
            return
        self._last_msg_count[self.selected_room] = count
        text = "\n".join(f"[{m['ts']}] {m['who']}: {m['text']}" for m in msgs)
        self._set_chat_text(text)

    def _set_chat_text(self, text):
        self.chat_box.config(state="normal")
        self.chat_box.delete("1.0", "end")
        self.chat_box.insert("end", text)
        self.chat_box.see("end")
        self.chat_box.config(state="disabled")

    def _tick(self):
        self._refresh_room_list()
        self._render_messages()
        self.root.after(700, self._tick)


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
    time.sleep(1)

    root = tk.Tk()
    gui = AdminGUI(root, base_url=f"http://localhost:{PORT}")
    root.mainloop()
