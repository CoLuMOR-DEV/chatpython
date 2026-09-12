"""
Temporary Chat — Admin Console (remote)
----------------------------------------
This is YOUR app. It does not host anything itself — it connects to
your chat server (the one you deployed from server/app.py) over the
network, the same way a browser would, and lets you:

  - See active rooms (auto-refreshing) and how many people are in each.
  - Create a new room -> get a shareable, unguessable link.
  - Read a room's live conversation and reply as "Admin".
  - Delete a room -> visitors instantly see "This chat is no longer
    available" and the link stops working.
  - Get a notification sound whenever someone sends a new message,
    even in a room you're not currently looking at.

Because it just connects over the internet, you can run this from any
computer, and it works as long as your server is deployed and running
— it doesn't need to be the same machine, and it doesn't need to stay
open for other people's links to keep working.

--------------------------------------------------------------------
Run it:
    pip install -r requirements.txt
    python admin_gui.py

On first run it asks for:
  - Server URL   e.g. https://your-app.onrender.com
  - Admin key    the ADMIN_KEY you set on the server

Both are remembered locally (in admin_config.json next to this
script) so you don't have to retype them every time.
--------------------------------------------------------------------
"""

import json
import os
import sys
import threading

import tkinter as tk
from tkinter import simpledialog, messagebox, scrolledtext

import socketio

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin_config.json")


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"server_url": "", "admin_key": ""}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f)
    except Exception:
        pass


def play_notification_sound(root):
    """Cross-platform notification 'ding'. Uses winsound for a nicer
    tone on Windows, and falls back to the system bell everywhere
    else (macOS / Linux) with no extra dependencies required."""
    try:
        if sys.platform.startswith("win"):
            import winsound
            winsound.Beep(880, 150)
            winsound.Beep(660, 150)
        else:
            root.bell()
    except Exception:
        try:
            root.bell()
        except Exception:
            pass


class AdminGUI:
    def __init__(self, root):
        self.root = root
        self.selected_room = None
        self.room_hashes = []
        self.rooms_data = {}  # hash -> dict
        self.chat_cache = {}  # hash -> list of messages
        self.connected = False
        self.sound_enabled = tk.BooleanVar(value=True)

        cfg = load_config()
        self.server_url_var = tk.StringVar(value=cfg.get("server_url", ""))
        self.admin_key_var = tk.StringVar(value=cfg.get("admin_key", ""))

        self.sio = socketio.Client(reconnection=True, reconnection_delay=2)
        self._register_socket_events()

        root.title("Temporary Chat — Admin")
        root.geometry("900x560")
        root.minsize(680, 440)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()

        if self.server_url_var.get() and self.admin_key_var.get():
            self._connect()

    # ---- UI construction ---------------------------------------------
    def _build_ui(self):
        top = tk.Frame(self.root, bg="#171a21")
        top.pack(fill="x")
        tk.Label(top, text="Server URL:", bg="#171a21", fg="#ccc").pack(side="left", padx=(10, 4), pady=8)
        tk.Entry(top, textvariable=self.server_url_var, width=32).pack(side="left", pady=8)
        tk.Label(top, text="Admin key:", bg="#171a21", fg="#ccc").pack(side="left", padx=(10, 4), pady=8)
        tk.Entry(top, textvariable=self.admin_key_var, width=22, show="*").pack(side="left", pady=8)
        self.connect_btn = tk.Button(top, text="Connect", command=self._connect)
        self.connect_btn.pack(side="left", padx=10, pady=8)
        tk.Checkbutton(top, text="Sound", variable=self.sound_enabled, bg="#171a21", fg="#ccc",
                        selectcolor="#171a21", activebackground="#171a21").pack(side="left", padx=(0, 10))
        self.conn_status_var = tk.StringVar(value="Not connected")
        tk.Label(top, textvariable=self.conn_status_var, bg="#171a21", fg="#8a8f9c").pack(side="right", padx=10)

        left = tk.Frame(self.root, width=280)
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

        self.status_var = tk.StringVar(value="Enter your server URL and admin key, then Connect.")
        tk.Label(self.root, textvariable=self.status_var, anchor="w", fg="#666").pack(fill="x", padx=10, pady=(0, 6))

    # ---- Connection ----------------------------------------------------
    def _connect(self):
        url = self.server_url_var.get().strip().rstrip("/")
        key = self.admin_key_var.get().strip()
        if not url or not key:
            messagebox.showinfo("Missing info", "Enter both the server URL and the admin key.")
            return
        save_config({"server_url": url, "admin_key": key})

        if self.sio.connected:
            self.sio.disconnect()

        self.conn_status_var.set("Connecting…")

        def do_connect():
            try:
                self.sio.connect(url, namespaces=["/admin"], transports=["websocket", "polling"])
            except Exception as e:
                error_msg = f"Connection failed: {e}"
                self.root.after(0, lambda: self.conn_status_var.set(error_msg))

        threading.Thread(target=do_connect, daemon=True).start()

    def _register_socket_events(self):
        sio = self.sio

        @sio.event(namespace="/admin")
        def connect():
            self.sio.emit("auth", {"key": self.admin_key_var.get().strip()}, namespace="/admin")

        @sio.event(namespace="/admin")
        def connect_error(data):
            self.root.after(0, lambda: self.conn_status_var.set("Connection error — check server URL."))

        @sio.event(namespace="/admin")
        def disconnect():
            self.connected = False
            self.root.after(0, lambda: self.conn_status_var.set("Disconnected"))

        @sio.on("auth_ok", namespace="/admin")
        def on_auth_ok():
            self.connected = True
            self.root.after(0, lambda: self.conn_status_var.set("Connected ✓"))
            self.root.after(0, lambda: self.status_var.set("Connected to server."))

        @sio.on("auth_fail", namespace="/admin")
        def on_auth_fail():
            self.connected = False
            self.sio.disconnect()
            self.root.after(0, lambda: self.conn_status_var.set("Auth failed"))
            self.root.after(0, lambda: messagebox.showerror(
                "Admin key rejected", "That admin key doesn't match the server's ADMIN_KEY."))

        @sio.on("rooms_update", namespace="/admin")
        def on_rooms_update(data):
            self.root.after(0, lambda: self._apply_rooms_update(data))

        @sio.on("room_created", namespace="/admin")
        def on_room_created(data):
            def apply():
                self._select_room(data["hash"])
                self.status_var.set(f"Created room {data['hash']}")
            self.root.after(0, apply)

        @sio.on("room_deleted", namespace="/admin")
        def on_room_deleted(data):
            def apply():
                if self.selected_room == data.get("room"):
                    self.selected_room = None
                    self.link_var.set("(select or create a room)")
                    self._set_chat_text("(this room no longer exists)")
                self.status_var.set(f"Deleted room {data.get('room')}")
            self.root.after(0, apply)

        @sio.on("messages", namespace="/admin")
        def on_messages(data):
            def apply():
                room = data.get("room")
                msgs = data.get("messages", [])
                self.chat_cache[room] = msgs
                if room == self.selected_room:
                    self._render_chat(room)
            self.root.after(0, apply)

        @sio.on("message", namespace="/admin")
        def on_message(entry):
            def apply():
                room = entry.get("room")
                msg = {"who": entry.get("who"), "text": entry.get("text"), "ts": entry.get("ts")}
                self.chat_cache.setdefault(room, []).append(msg)
                if room == self.selected_room:
                    self._render_chat(room)
                if msg["who"] not in ("Admin",) and self.sound_enabled.get():
                    play_notification_sound(self.root)
            self.root.after(0, apply)

    def _on_close(self):
        try:
            if self.sio.connected:
                self.sio.disconnect()
        except Exception:
            pass
        self.root.destroy()

    # ---- Actions ---------------------------------------------------
    def _server_url(self):
        return self.server_url_var.get().strip().rstrip("/")

    def _new_room(self):
        if not self.connected:
            messagebox.showinfo("Not connected", "Connect to your server first.")
            return
        label = simpledialog.askstring("New Room", "Optional label (just for you):", parent=self.root) or ""
        self.sio.emit("create_room", {"label": label}, namespace="/admin")

    def _delete_selected(self):
        if not self.selected_room:
            messagebox.showinfo("No room selected", "Select a room first.")
            return
        if messagebox.askyesno("Delete room", "Delete this room? Its link will stop working immediately."):
            self.sio.emit("delete_room", {"room": self.selected_room}, namespace="/admin")

    def _on_select_room(self, _event):
        sel = self.room_listbox.curselection()
        if not sel:
            return
        self._select_room(self.room_hashes[sel[0]])

    def _select_room(self, room_hash):
        self.selected_room = room_hash
        self.link_var.set(f"{self._server_url()}/r/{room_hash}")
        if room_hash in self.chat_cache:
            self._render_chat(room_hash)
        else:
            self._set_chat_text("(loading…)")
        if self.connected:
            self.sio.emit("get_messages", {"room": room_hash}, namespace="/admin")
        idx = self.room_hashes.index(room_hash) if room_hash in self.room_hashes else None
        if idx is not None:
            self.room_listbox.selection_clear(0, "end")
            self.room_listbox.selection_set(idx)

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
        self.sio.emit("send_message", {"room": self.selected_room, "text": text}, namespace="/admin")
        self.msg_entry.delete(0, "end")

    # ---- Rendering --------------------------------------------------
    def _apply_rooms_update(self, data):
        keep_selection = self.selected_room
        self.rooms_data = {d["hash"]: d for d in data}
        self.room_hashes = list(self.rooms_data.keys())
        self.room_listbox.delete(0, "end")
        for h in self.room_hashes:
            d = self.rooms_data[h]
            self.room_listbox.insert(
                "end",
                f"{h[:10]}…  [{d['label']}]  {d['users']} online · {d['messages']} msgs · {d['age_min']}m",
            )
        if keep_selection in self.room_hashes:
            self.room_listbox.selection_set(self.room_hashes.index(keep_selection))
        elif keep_selection and keep_selection not in self.room_hashes:
            self.selected_room = None
            self.link_var.set("(select or create a room)")
            self._set_chat_text("(this room no longer exists)")

    def _render_chat(self, room_hash):
        msgs = self.chat_cache.get(room_hash, [])
        text = "\n".join(f"[{m['ts']}] {m['who']}: {m['text']}" for m in msgs)
        self._set_chat_text(text)

    def _set_chat_text(self, text):
        self.chat_box.config(state="normal")
        self.chat_box.delete("1.0", "end")
        self.chat_box.insert("end", text)
        self.chat_box.see("end")
        self.chat_box.config(state="disabled")


if __name__ == "__main__":
    root = tk.Tk()
    gui = AdminGUI(root)
    root.mainloop()
