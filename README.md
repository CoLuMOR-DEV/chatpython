# Temporary Chat

Two parts now, instead of one:

```
console-chat/
├── server/          <- deploy this to a cloud host (always-on, public links)
│   ├── app.py
│   ├── requirements.txt
│   ├── Procfile
│   ├── render.yaml
│   └── templates/
│       ├── chat.html
│       └── gone.html
└── admin_app/        <- runs on YOUR computer, controls the server remotely
    ├── admin_gui.py
    └── requirements.txt
```

**Why the split?** The old version ran the web server *and* the admin
window in the same script on your machine — so links only worked
while your computer was on and the script was running. Now:

- `server/` is a plain web app you deploy once to a free cloud host.
  It runs 24/7 on its own, so any link you share works for anyone,
  anytime — no dependence on your laptop.
- `admin_app/admin_gui.py` is your control panel. It connects to the
  deployed server over the internet (using a secret admin key) so you
  can create rooms, chat as "Admin", and delete rooms from anywhere.

What's new in this version:
- **Notification sound** in the browser chat page, plus in the admin
  app, whenever a new message arrives.
- **Flashing tab title** ("New message!") in the browser when the tab
  isn't focused, so you notice replies even in a background tab.
  Stops flashing as soon as you switch back.
- **Responsive layout** — the web chat now adapts from small phones up
  through tablets and desktop screens, instead of being locked to a
  narrow mobile-only column.

---

## 1. Deploy the server (so links work for everyone)

Any host that runs Python web apps works — Render, Railway, Fly.io, a
VPS, etc. Render's free tier is the easiest starting point:

1. Push the `server/` folder to a GitHub repo (or the whole
   `console-chat` folder — Render just needs to be pointed at
   `server/` as the root).
2. Go to [render.com](https://render.com) → **New** → **Web Service**
   → connect that repo.
3. Set:
   - **Root Directory:** `server` (skip if your repo root *is* the
     `server` folder)
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn --worker-class eventlet -w 1 app:app`
4. Add an environment variable **`ADMIN_KEY`** set to a long random
   string you make up (this is the password your admin app will use —
   keep it secret). Render's blueprint (`render.yaml`) will
   auto-generate one for you if you use "New → Blueprint" instead.
5. Also add an environment variable **`PYTHON_VERSION`** set to
   `3.11.9`. Render sometimes defaults new services to a very recent
   Python (e.g. 3.14) that `eventlet` doesn't support yet, which fails
   with `AttributeError: module 'eventlet.green.thread' has no
   attribute 'start_joinable_thread'`. The included `runtime.txt` /
   `.python-version` files should make Render pick 3.11 automatically,
   but if it still deploys on the wrong version, set this env var
   explicitly in the dashboard.
6. Deploy. Render gives you a public URL like
   `https://your-app.onrender.com` — that's your server's address.

Note: Render's free tier sleeps after inactivity and briefly wakes on
the next visit (a few seconds' delay). For an always-instant-awake
server, use a paid tier or a different always-on host — the code
doesn't change either way.

Prefer not to deploy anywhere permanent? For a quick, temporary public
link without hosting an account, you can still run `server/app.py` on
your own machine and expose it with a tunnel:
```
python app.py
cloudflared tunnel --url http://localhost:5000
```
But this only stays up while your computer and the tunnel are
running — the whole point of deploying is to avoid that limitation.

## 2. Run your admin app (on your own computer, anytime)

```
cd admin_app
pip install -r requirements.txt
python admin_gui.py
```

On first launch, enter:
- **Server URL** — the address from step 1, e.g.
  `https://your-app.onrender.com`
- **Admin key** — the `ADMIN_KEY` you set on the server

Click **Connect**. Both fields are remembered locally afterward. From
here it works like before: **New Room** creates a shareable link,
selecting a room shows its live conversation, typing and hitting
Send replies as "Admin", and **Delete** closes the room for everyone.
You'll also hear a notification sound whenever anyone sends a new
message, even in a room you're not currently viewing (toggle the
**Sound** checkbox to mute it).

## Notes

- Everything is stored in memory only — restarting the server clears
  all rooms and messages, same as before.
- The admin key is the only thing protecting room creation/deletion
  and the ability to post as "Admin" — treat it like a password, and
  set your own real value in production rather than relying on the
  auto-generated one that's only meant for quick local testing.
