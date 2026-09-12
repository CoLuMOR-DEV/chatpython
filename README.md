# Console-Controlled Temporary Chat

Everything is driven from your terminal. There is no web-based admin page —
**your Python process *is* the admin**:

- Run `python app.py` and you get a `>` prompt right there in the terminal.
- Type `new` to mint a random, unguessable link (e.g. `/r/aZ9k3Qp7Lm2Xr`).
- Share that link. People who open it can chat with each other AND with you.
- You watch/send messages with `view` / `send` — typed directly into Python.
- `delete <hash>` instantly kills the room: everyone connected sees
  "This chat is no longer available" and the link 404s from then on.
- All of it lives only in a Python dict in RAM. Stop the script -> everything
  is gone. Nothing is ever written to disk.

## 1. Run it

```bash
pip install -r requirements.txt
python app.py
```

You'll see:
```
Server running on http://localhost:5000

Commands:
  new [label]          Create a new room...
  ...
>
```

Try it locally first — open `http://localhost:5000` in one browser tab,
type `new` in the terminal, open the printed `/r/<hash>` link in another
tab, and chat between the browser tab and the `send <hash> <text>` command.

## 2. Admin commands (typed at the `>` prompt)

| Command | What it does |
|---|---|
| `new [label]` | Creates a room, prints the shareable path. `label` is just a private note for you. |
| `rooms` | Lists all active rooms: hash, your label, user count, message count, age. |
| `view <hash>` | Prints the full message history of a room. |
| `send <hash> <message>` | Sends a message into the room as "Admin" — visitors see it live. |
| `delete <hash>` | Deletes the room. The link stops working immediately for everyone. |
| `help` | Shows the command list again. |
| `quit` | Shuts the whole thing down. |

## 3. Make the link reachable by other people (free)

Right now `http://localhost:5000` only works on your own machine. To let
anyone on the internet open your `/r/<hash>` link, expose port 5000 with a
**free tunnel** — no cloud hosting account needed, and it fits this design
perfectly since the "server" is your own running Python process.

### Option A — Cloudflare Tunnel (recommended, no signup needed for quick tunnels)
```bash
# macOS
brew install cloudflared
# Windows/Linux: download from https://github.com/cloudflare/cloudflared/releases

cloudflared tunnel --url http://localhost:5000
```
It prints a public `https://xxxxx.trycloudflare.com` URL. Share links as
`https://xxxxx.trycloudflare.com/r/<hash>`.

### Option B — localtunnel (needs Node.js)
```bash
npx localtunnel --port 5000
```
Prints a `https://xxxxx.loca.lt` URL (first-time visitors see a one-time
"click to continue" interstitial page — that's normal for localtunnel).

### Option C — ngrok (free tier, requires a free account + authtoken)
```bash
ngrok http 5000
```

**Important:** whichever tunnel you use, keep the tunnel command *and*
`python app.py` running in two terminals at the same time. Closing either
one takes the chat offline — which, given the "temporary" design, is
usually exactly what you want.

## How "temporary" and "unguessable" work here
- Each room hash is generated with `secrets.token_urlsafe(12)` — cryptographically
  random, ~96 bits of entropy, not something anyone can guess or enumerate.
- The tunnel options above all serve over **HTTPS**, so traffic between
  visitors and your machine is encrypted in transit.
- Messages are kept only in the `rooms` dict in memory — deleting a room or
  stopping the script erases them for good.

## Customize
- Change `ADMIN_NAME` in `app.py` if you want your messages labeled
  something other than "Admin".
- Message/room history has no size cap here since it's meant to be short-lived;
  add a cap similar to `MAX_MESSAGES_KEPT` if you plan to leave it running a long time.
