"""
mcp_template.py — Generic MCP toy control template for AI to fill in

FOR OTHER BRANDS (not MonsterParty / Ankni):
  If your toy uses a cloud relay with a share link, follow AI_GUIDE.md to
  reverse-engineer the protocol, then fill in the BRAND_* constants below.

FOR MONSTERPARTY / ANKNI BRANDS (谜姬 / 安可尼 / 醉清风):
  Use mcp_toy_tools.py instead — it's already complete and ready to run.

─────────────────────────────────────────────────────────────────────────────
HOW TO FILL IN THIS TEMPLATE (AI-readable instructions):

Step 1: Get the share link from the toy app. Open it in a browser with
        DevTools > Network open. Find:
        A. The REST API call that returns a WebSocket URL (look for ws:// or wss://)
        B. The messages in the WS tab (handshake, control, heartbeat)

Step 2: Download the page's main JS file (usually main.js or main.dart.js).
        Search for "op", "vib", "send(", "connect(" to find message formats.

Step 3: Fill in the six BRAND_* constants below, then implement:
        - fetch_session(): parse the REST API response
        - build_join_msg(): the first message sent after WS connect
        - build_control_msg(): the vibration/control command format

Step 4: Test by running:  python3 mcp_template.py
        Then: echo "vib 50" > /tmp/toy_cmd
─────────────────────────────────────────────────────────────────────────────
"""

from fastmcp import FastMCP
import asyncio, json, os, subprocess, time, urllib.request

mcp = FastMCP("toy-control-generic")

# ── ① Fill these six constants from DevTools inspection ──────────────────────

BRAND_API_URL      = "https://api.YOURBRAND.com/remote?s={token}"
# ^ REST endpoint that returns the WebSocket URL and session params.
#   Replace {token} with the user's share token.

BRAND_WS_ORIGIN    = "https://www.YOURBRAND.com"
# ^ Value for the Origin header when connecting to the WebSocket.

BRAND_USER_AGENT   = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/537.36 Mobile/15E148"
# ^ Usually a mobile browser UA works; copy from DevTools if needed.

OP_JOIN            = 2
# ^ op code for the first message sent after WS connect (find in JS: op:2 or similar)

OP_CONTROL         = 3
# ^ op code for the vibration/control command

OP_HEARTBEAT       = 8
# ^ op code for keepalive ping sent every N seconds

HEARTBEAT_INTERVAL = 9
# ^ seconds between heartbeats; adjust based on observed server behavior

# ── ② Implement these three functions ────────────────────────────────────────

def fetch_session(token: str) -> dict:
    """Call the brand's REST API to get WebSocket URL and session parameters.
    Return a dict with at least: ws_url, sess_id, user_id."""
    url = BRAND_API_URL.format(token=token)
    data = json.loads(urllib.request.urlopen(url, timeout=10).read())
    # ↓ Adjust key paths to match your brand's response JSON structure
    return {
        "ws_url":  data["data"]["socket_url"],   # WebSocket URL
        "sess_id": data["data"]["id"],            # session / room ID
        "user_id": data["data"]["user_id"],       # user ID of the toy owner
    }


def build_join_msg(sess_id: str, user_id: str) -> dict:
    """Build the handshake message sent immediately after connecting.
    Find this in DevTools WS tab — it's the first message from the controller."""
    return {
        "op":       OP_JOIN,
        "remoteID": sess_id,
        "senderID": user_id,
        # ↓ Add any other required fields your brand expects
    }


def build_control_msg(fd: str, vib_array: list, device_info: dict) -> dict:
    """Build a vibration control command.
    vib_array: list of 1–10 integers (0–100), format depends on brand.
    Find this in DevTools WS tab — it's sent when you tap a speed button."""
    return {
        "op":  OP_CONTROL,
        "vib": vib_array,              # ← some brands use "speed", "level", etc.
        "fd":  fd,                     # ← some brands don't need fd
        # ↓ Add keyType, channelId, or other brand-specific fields
    }


def is_device_ready(msg: dict) -> tuple[bool, str]:
    """Return (True, pid_string) when the server signals the device is connected.
    Find this in DevTools WS tab — it's the message that appears when the toy connects."""
    # MonsterParty example: {"op":15,"conn":true,"pid":"AKN_DS_SUCKEGG"}
    if msg.get("op") == 15 and msg.get("conn"):
        return True, msg.get("pid", "")
    return False, ""


def get_fd(msg: dict) -> str | None:
    """Extract the device handle (fd) from a server message, if present.
    Find this in DevTools WS tab — it's usually in the first server→client message."""
    # MonsterParty example: {"op":6,"sender":{"fd":12296}}
    if msg.get("op") == 6:
        return msg.get("sender", {}).get("fd")
    return None

# ── ③ Below this line: no changes needed ─────────────────────────────────────

CMD_FILE   = "/tmp/toy_cmd"
STATE_FILE = "/tmp/toy_state"
DAEMON_FILE = "/tmp/toy_daemon.py"

def _make_daemon_script() -> str:
    """Generate the daemon script with the brand-specific functions embedded."""
    import inspect
    fns = "\n\n".join(inspect.getsource(f) for f in [
        fetch_session, build_join_msg, build_control_msg,
        is_device_ready, get_fd,
    ])
    return f'''import asyncio, json, os, sys, urllib.request
import websockets

BRAND_API_URL      = {BRAND_API_URL!r}
BRAND_WS_ORIGIN    = {BRAND_WS_ORIGIN!r}
BRAND_USER_AGENT   = {BRAND_USER_AGENT!r}
OP_JOIN            = {OP_JOIN!r}
OP_CONTROL         = {OP_CONTROL!r}
OP_HEARTBEAT       = {OP_HEARTBEAT!r}
HEARTBEAT_INTERVAL = {HEARTBEAT_INTERVAL!r}

{fns}

token = sys.argv[1]

async def run():
    session = fetch_session(token)
    async with websockets.connect(session["ws_url"], additional_headers={{
        "Origin": BRAND_WS_ORIGIN, "User-Agent": BRAND_USER_AGENT,
    }}, ping_interval=None, ping_timeout=None) as ws:
        await ws.send(json.dumps(build_join_msg(session["sess_id"], session["user_id"])))
        fd = None; device_info = {{}}
        for _ in range(20):
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                fd_val = get_fd(msg)
                if fd_val: fd = fd_val
                ready, pid = is_device_ready(msg)
                if ready: device_info["pid"] = pid; break
                if "errNo" in msg: return
            except asyncio.TimeoutError:
                if fd: break
        if not fd: return
        with open({STATE_FILE!r}, "w") as f:
            json.dump({{"fd": fd, "ready": True, **device_info}}, f)
        async def hb():
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await ws.send(json.dumps({{"op": OP_HEARTBEAT}}))
        asyncio.create_task(hb())
        while True:
            await asyncio.sleep(0.3)
            if not os.path.exists({CMD_FILE!r}): continue
            line = open({CMD_FILE!r}).read().strip(); os.unlink({CMD_FILE!r})
            parts = line.split()
            if not parts or parts[0] == "quit": break
            n = 0 if parts[0] == "stop" else int(parts[1])
            dur = float(parts[2]) if len(parts)>2 else 0
            vib = [n]*10 if n > 0 else [0]*10
            await ws.send(json.dumps(build_control_msg(fd, vib, device_info)))
            if dur > 0:
                await asyncio.sleep(dur)
                await ws.send(json.dumps(build_control_msg(fd, [0]*10, device_info)))

asyncio.run(run())
'''


@mcp.tool()
def toy_connect(token: str) -> str:
    """Connect to a cloud toy using a share link token.

token: the string after the last / in your share link.
Example: https://app.example.com/remote/TOKEN_HERE → pass "TOKEN_HERE"

Each token is single-use. Get a fresh one from your toy app each session."""
    for p in [STATE_FILE, CMD_FILE]:
        try: os.unlink(p)
        except: pass

    with open(DAEMON_FILE, "w") as f:
        f.write(_make_daemon_script())

    subprocess.Popen(
        ["python3", DAEMON_FILE, token],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    for _ in range(30):
        time.sleep(0.5)
        if os.path.exists(STATE_FILE):
            try:
                state = json.loads(open(STATE_FILE).read())
                if state.get("ready"):
                    return f"✅ Connected: {state.get('pid', 'device')} | fd={state.get('fd')}"
            except: pass

    return "❌ Timeout: device not ready. Make sure the toy is on and the link is fresh."


@mcp.tool()
def toy_vibrate(intensity: int, duration: float = 0.0) -> str:
    """Vibrate the toy.

intensity: strength 0–100 (0 = stop)
duration:  seconds then auto-stop; 0 = hold until next command"""
    if not os.path.exists(STATE_FILE):
        return "❌ Not connected — call toy_connect(token) first"
    intensity = max(0, min(100, intensity))
    cmd = f"vib {intensity} {duration}" if duration > 0 else f"vib {intensity}"
    with open(CMD_FILE, "w") as f:
        f.write(cmd)
    dur_str = f"for {duration}s" if duration > 0 else "until next command"
    return f"✅ Sent: intensity={intensity} | {dur_str}"


@mcp.tool()
def toy_stop() -> str:
    """Stop the toy immediately."""
    if not os.path.exists(STATE_FILE):
        return "❌ Not connected"
    with open(CMD_FILE, "w") as f:
        f.write("stop")
    return "✅ Stopped"


if __name__ == "__main__":
    mcp.run()
