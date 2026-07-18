"""
ankni_client.py — MonsterParty / Ankni remote toy controller

Supports AKN_DS_SUCKEGG (dual-stimulation) and single-motor devices.
Motor mapping for DS devices:
  vib[0]   = suction motor
  vib[1-4] = vibration motor
  vib[5-9] = unused

Usage:
  python3 ankni_client.py <token>

  Token is the base64 string from the MonsterParty share link:
    https://www.monsterparty.cn/remote/<TOKEN>

Command file: /tmp/ankni_cmd
  stop                    — stop all motors
  vib N [dur]             — all motors at intensity N (0-100), optional duration in seconds
  vib S V [dur]           — DS only: suction=S, vibration=V independently
  raw [i,i,...,i] [dur]   — exact 10-element array, full control
  suck_k N [dur]          — send with keyType=suck override
  vib_k N [dur]           — send with keyType=vib override
  quit                    — exit daemon

State file: /tmp/ankni_state (JSON)
  sender_fd, ready, pid, key_type, is_ds
"""

import asyncio
import json
import os
import sys
import urllib.parse
import urllib.request

import websockets

CMD_FILE   = "/tmp/ankni_cmd"
STATE_FILE = "/tmp/ankni_state"


def fetch_session(token: str) -> tuple[str, str, str]:
    url = f"https://api.monsterparty.cc/main/v1/remote?s={urllib.parse.quote(token)}"
    data = json.loads(urllib.request.urlopen(url, timeout=10).read())["data"]
    return data["socket_url"], data["id"], data["user_id"]


async def run(token: str):
    ws_url, sess_id, uid = fetch_session(token)
    print(f"sess={sess_id}", flush=True)

    # ping_interval=None disables websockets library keepalive;
    # we use application-level op:8 heartbeat instead.
    async with websockets.connect(
        ws_url,
        additional_headers={
            "Origin": "https://www.monsterparty.cn",
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/537.36 Mobile/15E148"
            ),
        },
        ping_interval=None,
        ping_timeout=None,
    ) as ws:
        # --- handshake ---
        await ws.send(json.dumps({
            "op": 2, "id": 8899001, "gender": "male",
            "remoteID": sess_id, "senderID": uid,
            "avatar": "", "nickname": "remote", "lat": 0, "lng": 0, "area": "",
        }))

        sender_fd = None
        pid = ""
        for _ in range(20):
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                op = msg.get("op")
                print(f"op={op}", flush=True)
                if op == 6:
                    sender_fd = msg["sender"]["fd"]
                    print(f"fd={sender_fd}", flush=True)
                if op == 15 and msg.get("conn"):
                    pid = msg.get("pid", "")
                    print(f"DEVICE_READY pid={pid}", flush=True)
                    break
                if "errNo" in msg:
                    print(f"ERROR {msg}", flush=True)
                    return
            except asyncio.TimeoutError:
                if sender_fd:
                    break  # fd obtained, device may not be DS — proceed anyway

        if not sender_fd:
            print("NO_FD — connection failed", flush=True)
            return

        key_type = "suck" if "SUCK" in pid.upper() else "vib"
        is_ds    = "DS"   in pid.upper()
        print(f"keyType={key_type} is_ds={is_ds}", flush=True)

        with open(STATE_FILE, "w") as f:
            json.dump({
                "sender_fd": sender_fd,
                "ready": True,
                "pid": pid,
                "key_type": key_type,
                "is_ds": is_ds,
            }, f)
        print("CONNECTED", flush=True)

        # --- heartbeat ---
        async def heartbeat():
            while True:
                await asyncio.sleep(9)
                await ws.send(json.dumps({"op": 8}))

        asyncio.create_task(heartbeat())

        # --- command loop ---
        while True:
            await asyncio.sleep(0.3)
            if not os.path.exists(CMD_FILE):
                continue

            line = open(CMD_FILE).read().strip()
            os.unlink(CMD_FILE)
            if not line:
                continue

            parts = line.split()
            cmd   = parts[0]
            kt    = key_type
            dur   = 0.0

            if cmd == "quit":
                break

            elif cmd == "stop":
                vib_val = [0] * 10

            elif cmd == "raw":
                vib_val = json.loads(parts[1])
                dur = float(parts[2]) if len(parts) > 2 else 0.0

            elif cmd in ("vib_k", "suck_k"):
                kt      = "vib" if cmd == "vib_k" else "suck"
                n       = int(parts[1])
                vib_val = [n] * 10 if n > 0 else [0] * 10
                dur     = float(parts[2]) if len(parts) > 2 else 0.0

            elif cmd == "vib" and is_ds and len(parts) >= 3:
                # DS mode: vib <suck_intensity> <vib_intensity> [dur]
                s, v    = int(parts[1]), int(parts[2])
                vib_val = [s, v, v, v, v, 0, 0, 0, 0, 0]
                dur     = float(parts[3]) if len(parts) > 3 else 0.0

            else:
                # vib <intensity> [dur]
                n       = int(parts[1]) if cmd != "stop" else 0
                vib_val = [n] * 10 if n > 0 else [0] * 10
                dur     = float(parts[2]) if len(parts) > 2 else 0.0

            await ws.send(json.dumps({"op": 3, "vib": vib_val, "fd": sender_fd, "keyType": kt}))
            print(f"CMD vib={vib_val} keyType={kt}", flush=True)

            if dur > 0:
                await asyncio.sleep(dur)
                await ws.send(json.dumps({"op": 3, "vib": [0] * 10, "fd": sender_fd, "keyType": kt}))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 ankni_client.py <token>")
        sys.exit(1)
    asyncio.run(run(sys.argv[1]))
