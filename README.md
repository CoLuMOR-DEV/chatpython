# GUI-Controlled Temporary Chat

Run this and a **desktop window opens on your screen** — that window is your
whole admin console:

- **Left panel** — list of active rooms, auto-refreshing, with a "New Room"
  and "Delete" button.
- **Right panel** — the live conversation of whichever room you've selected,
  plus a text box + Send button so you can talk as "Admin."
- Deleting a room instantly kicks everyone out of it and the link 404s from
  then on.
- Everything lives only in memory (a Python dict). Close the window and it's
  all gone — nothing is ever written to disk.

## 1. Install & run

```bash
pip install -r requirements.txt
python app.py
```

A window titled **"Temporary Chat — Admin"** should pop up.

> **Linux users:** if you get `ModuleNotFoundError: No module named 'tkinter'`,
> install it with your package manager, e.g. `sudo apt-get install python3-tk`.
> Windows and macOS installs of Python normally include tkinter already, so
> this step usually isn't needed there.

## 2. Using the window

1. Click **New Room** → optionally type a private label for yourself (only
   you see it) → a random link appears in the box, e.g.
   `http://localhost:5000/r/9HPGpMJuahjRekxo`.
2. Click **Copy Link** and send it to whoever you want in the chat.
3. As people join and type, their messages appear in the right-hand panel
   automatically (it refreshes ~1.5x/second).
4. Click a room in the list to switch which conversation you're viewing.
5. Type in the bottom box and press **Enter** or **Send** to post as "Admin"
   — it shows up instantly for everyone in that room.
6. Click **Delete** to end a room. Everyone connected sees "This chat has
   been closed by the admin" and the link stops working.

## 3. Make the link reachable by other people (free)

By default the link only works on your own computer
(`http://localhost:5000/...`). To let anyone on the internet open it, expose
port 5000 with a **free tunnel** — this fits the design well, since the
"server" really is your own running Python process with a window open.

### Option A — Cloudflare Tunnel (no signup needed for quick tunnels)
```bash
# macOS
brew install cloudflared
# Windows/Linux: download from https://github.com/cloudflare/cloudflared/releases

cloudflared tunnel --url http://localhost:5000
```
It prints a public `https://xxxxx.trycloudflare.com` URL. Room links then
look like `https://xxxxx.trycloudflare.com/r/<hash>`.

### Option B — localtunnel (needs Node.js)
```bash
npx localtunnel --port 5000
```
Gives you a `https://xxxxx.loca.lt` link (first-time visitors see a one-time
"click to continue" page — normal for localtunnel).

### Option C — ngrok (free tier, requires a free account + authtoken)
```bash
ngrok http 5000
```

**Keep both `python app.py` and the tunnel command running** at the same
time, in two terminals/windows. Closing either one takes the chat offline —
which matches the "temporary" idea: nothing persists once you stop.

## How "unguessable" and "temporary" work here
- Each room link uses `secrets.token_urlsafe(12)` — cryptographically random,
  ~96 bits, not something anyone could guess or brute-force.
- The tunnel options above all serve over HTTPS, so traffic is encrypted
  between visitors and your machine.
- Room state (messages, who's connected) lives only in RAM in the `rooms`
  dict inside `app.py` — deleting a room, or closing the window/script,
  erases it permanently.

## Files
- `app.py` — Flask + Socket.IO server (background thread) + the tkinter GUI
  (main thread/main window).
- `templates/chat.html` — the page visitors see when they open a room link.
- `templates/gone.html` — shown when a link has been deleted/expired.
- `requirements.txt` — Flask, Flask-SocketIO, simple-websocket (tkinter
  itself is part of the Python standard library, not listed here).

## Customize
- `ADMIN_NAME` in `app.py` controls the name your messages appear under.
- The GUI polls every 700ms (`self.root.after(700, self._tick)`); lower it
  for snappier updates, raise it if you have many rooms open at once.
