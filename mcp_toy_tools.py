"""
mcp_toy_tools.py — Drop-in MCP tools for MonsterParty / Ankni toy control

Usage: paste these functions into your own FastMCP server, or run standalone:
  pip install fastmcp websockets
  python3 mcp_toy_tools.py  # starts MCP server on stdio

The daemon script is written to /tmp/fast_ankni.py on first connect and
communicates via file IPC (/tmp/ankni_cmd, /tmp/ankni_state).
"""

from fastmcp import FastMCP
import asyncio, json, os, subprocess, time, urllib.parse, urllib.request

mcp = FastMCP("toy-control")

ANKNI_DAEMON = "/tmp/fast_ankni.py"
ANKNI_CMD    = "/tmp/ankni_cmd"
ANKNI_STATE  = "/tmp/ankni_state"

# Daemon script — written to disk on connect, runs as background process
ANKNI_SCRIPT = r'''import asyncio, json, sys, urllib.request, urllib.parse, os
import websockets

token = sys.argv[1]
url = f"https://api.monsterparty.cc/main/v1/remote?s={urllib.parse.quote(token)}"
d = json.loads(urllib.request.urlopen(url, timeout=5).read())["data"]
ws_url, sess_id, uid = d["socket_url"], d["id"], d["user_id"]

async def run():
    # ping_interval=None: disable library keepalive, use op:8 app heartbeat only
    async with websockets.connect(ws_url, additional_headers={
        "Origin": "https://www.monsterparty.cn",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/537.36 Mobile/15E148"
    }, ping_interval=None, ping_timeout=None) as ws:
        await ws.send(json.dumps({"op":2,"id":8899001,"gender":"male","remoteID":sess_id,
            "senderID":uid,"avatar":"","nickname":"remote","lat":0,"lng":0,"area":""}))
        sender_fd = None; pid = ""
        for _ in range(20):
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                if msg.get("op") == 6: sender_fd = msg["sender"]["fd"]
                if msg.get("op") == 15 and msg.get("conn"):
                    pid = msg.get("pid", ""); break
                if "errNo" in msg: return
            except asyncio.TimeoutError:
                if sender_fd: break
        if not sender_fd: return
        key_type = "suck" if "SUCK" in pid.upper() else "vib"
        is_ds    = "DS"   in pid.upper()
        with open("/tmp/ankni_state", "w") as f:
            json.dump({"sender_fd": sender_fd, "ready": True, "pid": pid,
                       "key_type": key_type, "is_ds": is_ds}, f)
        async def hb():
            while True:
                await asyncio.sleep(9); await ws.send(json.dumps({"op":8}))
        asyncio.create_task(hb())
        while True:
            await asyncio.sleep(0.3)
            if not os.path.exists("/tmp/ankni_cmd"): continue
            line = open("/tmp/ankni_cmd").read().strip(); os.unlink("/tmp/ankni_cmd")
            parts = line.split()
            if not parts: continue
            if parts[0] == "quit": break
            if parts[0] == "stop":
                vib_val = [0]*10; dur = 0
            elif parts[0] == "raw":
                vib_val = json.loads(parts[1])
                dur = float(parts[2]) if len(parts)>2 else 0
            elif is_ds and len(parts) >= 3 and parts[0] == "vib":
                # DS dual-motor: vib <suck> <vibration> [dur]
                # AKN_DS_SUCKEGG mapping: pos[0]=suck, pos[1-4]=vib, pos[5-9]=unused
                s, v = int(parts[1]), int(parts[2])
                vib_val = [s, v, v, v, v, 0, 0, 0, 0, 0]
                dur = float(parts[3]) if len(parts)>3 else 0
            else:
                n = int(parts[1]) if parts[0] != "stop" else 0
                vib_val = [n]*10 if n > 0 else [0]*10
                dur = float(parts[2]) if len(parts)>2 else 0
            await ws.send(json.dumps({"op":3,"vib":vib_val,"fd":sender_fd,"keyType":key_type}))
            if dur > 0:
                await asyncio.sleep(dur)
                await ws.send(json.dumps({"op":3,"vib":[0]*10,"fd":sender_fd,"keyType":key_type}))

asyncio.run(run())
'''


@mcp.tool()
def toy_green_connect(token: str) -> str:
    """Connect to a MonsterParty / Ankni toy.

token: base64 string from the share link path.
  Share link format: https://www.monsterparty.cn/remote/<TOKEN>
  Each token is single-use and expires after disconnection.

On success returns device info. Then call toy_green_vibrate() to control."""
    for p in [ANKNI_STATE, ANKNI_CMD]:
        try: os.unlink(p)
        except: pass

    with open(ANKNI_DAEMON, "w") as f:
        f.write(ANKNI_SCRIPT)

    subprocess.Popen(
        ["python3", ANKNI_DAEMON, token],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    for _ in range(30):
        time.sleep(0.5)
        if os.path.exists(ANKNI_STATE):
            try:
                state = json.loads(open(ANKNI_STATE).read())
                if state.get("ready"):
                    ds = " | dual-motor (suck+vib)" if state.get("is_ds") else ""
                    return f"✅ Connected: {state.get('pid','unknown')}{ds} | fd={state.get('sender_fd')}"
            except: pass

    return "❌ Timeout: device not ready. Make sure the toy is powered on and the share link is fresh."


@mcp.tool()
def toy_green_vibrate(intensity: int, duration: float = 0.0, suck: int = -1) -> str:
    """Control toy vibration.

intensity: vibration strength 0–100 (0 = stop)
duration:  seconds to vibrate then auto-stop; 0 = hold until next command
suck:      suction strength 0–100, for dual-motor devices only (AKN_DS_SUCKEGG).
           Omit (default -1) to use intensity for all motors.
           When provided, controls suction and vibration independently.

Dual-motor note — AKN_DS_SUCKEGG motor mapping (empirically verified):
  vib array pos [0]   → suction pump
  vib array pos [1-4] → vibration motor
  vib array pos [5-9] → unused"""
    if not os.path.exists(ANKNI_STATE):
        return "❌ Not connected — call toy_green_connect(token) first"
    try:
        state = json.loads(open(ANKNI_STATE).read())
        if not state.get("ready"):
            return "❌ Device not ready"
    except:
        return "❌ State file corrupted, reconnect"

    intensity = max(0, min(100, intensity))
    is_ds = state.get("is_ds", False)

    if suck >= 0 and is_ds:
        suck = max(0, min(100, suck))
        cmd  = f"vib {suck} {intensity} {duration}" if duration > 0 else f"vib {suck} {intensity}"
        desc = f"suck={suck} vib={intensity}"
    else:
        cmd  = f"vib {intensity} {duration}" if duration > 0 else f"vib {intensity}"
        desc = f"intensity={intensity}"

    with open(ANKNI_CMD, "w") as f:
        f.write(cmd)

    dur_str = f"for {duration}s" if duration > 0 else "until next command"
    return f"✅ Sent: {desc} | {dur_str}"


@mcp.tool()
def toy_green_stop() -> str:
    """Stop all toy motors immediately."""
    if not os.path.exists(ANKNI_STATE):
        return "❌ Not connected"
    with open(ANKNI_CMD, "w") as f:
        f.write("stop")
    return "✅ Stopped"


@mcp.tool()
def toy_green_status() -> str:
    """Check toy connection status."""
    if not os.path.exists(ANKNI_STATE):
        return "Not connected (no state file)"
    try:
        state = json.loads(open(ANKNI_STATE).read())
        alive = subprocess.run(["pgrep", "-f", "fast_ankni.py"],
                               capture_output=True).returncode == 0
        return (
            f"Device:    {state.get('pid', 'unknown')}\n"
            f"fd:        {state.get('sender_fd')}\n"
            f"key_type:  {state.get('key_type')}\n"
            f"dual-motor:{state.get('is_ds', False)}\n"
            f"daemon:    {'running' if alive else 'stopped (reconnect needed)'}"
        )
    except:
        return "State file unreadable"


if __name__ == "__main__":
    mcp.run()
