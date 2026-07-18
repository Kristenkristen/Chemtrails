"""
template.py — Generic cloud toy controller template

Use this as a starting point for brands other than Ankni/MonsterParty.
Fill in the blanks found by inspecting your device's share page in DevTools.

Step-by-step:
  1. Open the share link in a browser with DevTools > Network tab open
  2. Find the REST API call that returns a WebSocket URL (look for ws:// or wss://)
  3. Open the WS tab and observe the messages exchanged
  4. Find the main JS bundle and search for: "op", "vib", "send(", "connect("
  5. Fill in BRAND_* constants below and implement parse_cmd() for your device
"""

import asyncio
import json
import os
import sys
import urllib.request

import websockets

# ── Fill these in from your reverse engineering ─────────────────────────────

BRAND_API_URL   = "https://api.example.com/remote?s={token}"   # REST endpoint
BRAND_ORIGIN    = "https://www.example.com"                     # Origin header
BRAND_USER_AGENT = "Mozilla/5.0 (iPhone; ...)"

# op codes (find in JS bundle)
OP_JOIN         = 2    # sent after WS connect (handshake)
OP_CONTROL      = 3    # sent to control device
OP_HEARTBEAT    = 8    # sent every N seconds to keep connection alive
OP_FD           = 6    # server sends us the "fd" (device handle)
OP_DEVICE_READY = 15   # server confirms device is connected and ready

HEARTBEAT_INTERVAL = 9  # seconds — adjust based on observed server behavior

CMD_FILE   = "/tmp/toy_cmd"
STATE_FILE = "/tmp/toy_state"


def fetch_session(token: str) -> dict:
    """Call the REST API to get WebSocket URL and session parameters."""
    url = BRAND_API_URL.format(token=token)
    data = json.loads(urllib.request.urlopen(url, timeout=10).read())
    # Adjust key names to match your brand's response format
    return {
        "ws_url":   data["data"]["socket_url"],
        "sess_id":  data["data"]["id"],
        "user_id":  data["data"]["user_id"],
    }


def build_join_msg(sess_id: str, user_id: str) -> dict:
    """Build the handshake message sent right after connecting."""
    # Adjust fields to match what the JS sends (op:2 equivalent)
    return {
        "op":       OP_JOIN,
        "remoteID": sess_id,
        "senderID": user_id,
        # add other required fields here
    }


def build_control_msg(fd: str, intensity: int, device_info: dict) -> dict:
    """Build a control command.

    intensity: 0–100
    Returns the JSON dict to send over WebSocket.
    """
    # Common patterns:
    #   array:  {"op": 3, "vib": [intensity]*10, "fd": fd, "keyType": "vib"}
    #   scalar: {"op": 3, "speed": intensity, "fd": fd}
    # Inspect your device's JS for the exact format.
    return {
        "op":      OP_CONTROL,
        "vib":     [intensity] * 10,   # adjust array length / structure
        "fd":      fd,
        "keyType": device_info.get("key_type", "vib"),
    }


async def run(token: str):
    session = fetch_session(token)

    async with websockets.connect(
        session["ws_url"],
        additional_headers={
            "Origin":     BRAND_ORIGIN,
            "User-Agent": BRAND_USER_AGENT,
        },
        ping_interval=None,   # use app-level heartbeat only
        ping_timeout=None,
    ) as ws:

        # --- handshake ---
        await ws.send(json.dumps(build_join_msg(session["sess_id"], session["user_id"])))

        fd = None
        device_info = {}
        for _ in range(20):
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                op  = msg.get("op")
                if op == OP_FD:
                    fd = msg["sender"]["fd"]       # adjust key path if needed
                if op == OP_DEVICE_READY:
                    device_info["pid"] = msg.get("pid", "")
                    break
                if "errNo" in msg:
                    print(f"Error: {msg}")
                    return
            except asyncio.TimeoutError:
                if fd:
                    break

        if not fd:
            print("Failed to obtain device handle")
            return

        with open(STATE_FILE, "w") as f:
            json.dump({"fd": fd, "ready": True, **device_info}, f)
        print("Connected", flush=True)

        # --- heartbeat ---
        async def heartbeat():
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await ws.send(json.dumps({"op": OP_HEARTBEAT}))

        asyncio.create_task(heartbeat())

        # --- command loop (file IPC) ---
        while True:
            await asyncio.sleep(0.3)
            if not os.path.exists(CMD_FILE):
                continue
            line = open(CMD_FILE).read().strip()
            os.unlink(CMD_FILE)

            if line == "quit":
                break
            if line == "stop":
                intensity = 0
            else:
                try:
                    intensity = int(line.split()[1])
                except (IndexError, ValueError):
                    continue

            await ws.send(json.dumps(build_control_msg(fd, intensity, device_info)))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 template.py <token>")
        sys.exit(1)
    asyncio.run(run(sys.argv[1]))
