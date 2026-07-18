# phantom-touch-bridge

> Control cloud-connected adult toys via their own WebSocket relay — no Bluetooth, no proximity required.  
> Works from anywhere with internet access. Designed for AI-assisted remote control.

---

## How it works

Most cloud-connected toys work through a **WebSocket relay server**:

```
Your phone (toy owner)  ←──→  Brand's WS relay server  ←──→  Controller (you / your AI)
```

The share link your toy generates contains a session token. Anyone who "opens" that link connects to the relay as a controller. We skip the browser and connect directly via Python.

## Supported devices

| Device | Brand | Protocol | Motors |
|--------|-------|----------|--------|
| AKN_DS_SUCKEGG | Ankni / MonsterParty | MonsterParty WS | suction + vibration (dual) |
| Single-motor Ankni devices | Ankni | MonsterParty WS | vibration |
| Other brands | — | see `template.py` | varies |

---

## Quick start (Ankni / MonsterParty)

```bash
pip install websockets

# Start daemon — token is from the share link path:
# https://www.monsterparty.cn/remote/<TOKEN>
python3 ankni_client.py <TOKEN>

# In another terminal, send commands:
echo "vib 70"           > /tmp/ankni_cmd   # vibrate at 70%
echo "vib 60 3"         > /tmp/ankni_cmd   # 60% for 3 seconds then stop
echo "vib 50 80"        > /tmp/ankni_cmd   # DS device: suction=50, vib=80
echo "stop"             > /tmp/ankni_cmd   # stop all motors
echo "quit"             > /tmp/ankni_cmd   # disconnect daemon
```

### Daemon state

```bash
cat /tmp/ankni_state
# {"sender_fd": 12296, "ready": true, "pid": "AKN_DS_SUCKEGG", "key_type": "suck", "is_ds": true}
```

---

## Protocol details (MonsterParty)

### Session setup

```
GET https://api.monsterparty.cc/main/v1/remote?s=<token>
→ { data: { socket_url, id (sess_id), user_id } }
```

### WebSocket handshake

```json
// 1. Connect to socket_url with Origin: https://www.monsterparty.cn
// 2. Send join message:
{ "op": 2, "id": 8899001, "gender": "male", "remoteID": <sess_id>,
  "senderID": <user_id>, "avatar": "", "nickname": "remote",
  "lat": 0, "lng": 0, "area": "" }

// 3. Wait for op:6 (fd assignment):
{ "op": 6, "sender": { "fd": 12296 }, "isSuck": false }

// 4. Wait for op:15 (device ready — toy is connected):
{ "op": 15, "conn": true, "pid": "AKN_DS_SUCKEGG" }
```

### Control command

```json
{ "op": 3, "vib": [70, 70, 70, 70, 70, 70, 70, 70, 70, 70],
  "fd": <sender_fd>, "keyType": "suck" }
```

`vib` is always a 10-element integer array (0–100). `keyType` is `"suck"` for suction-type devices, `"vib"` otherwise.

### Heartbeat

```json
{ "op": 8 }   // send every ~9 seconds
```

⚠️ **Disable the websockets library's built-in ping** (`ping_interval=None, ping_timeout=None`) — otherwise it causes spurious disconnects. Use only the op:8 application heartbeat.

### AKN_DS_SUCKEGG motor mapping

Discovered through empirical testing (position isolation):

| vib array position | Motor |
|--------------------|-------|
| `[0]` | Suction pump |
| `[1]`, `[2]`, `[3]`, `[4]` | Vibration motor |
| `[5]`–`[9]` | Unused |

To control both motors independently:
```python
vib = [suction, vibration, vibration, vibration, vibration, 0, 0, 0, 0, 0]
```

---

## Other brands

See `template.py` for a commented starting point. General steps:

1. Open share link in browser DevTools → Network tab
2. Find WebSocket connection and note the URL
3. Observe the message sequence (join, fd, control)
4. Download the main JS bundle and search for `"op"`, `"vib"`, `send(`
5. Fill in `template.py` constants

> Brands using the same MonsterParty backend (same parent company 醉清风健康科技):
> **谜姬**, **安可尼**, **醉清风** — same protocol, same op codes.

---

## AI integration

The daemon uses file-based IPC (`/tmp/ankni_cmd`) so any process — including an AI agent — can send commands without managing WebSocket state:

```python
# From your AI tool implementation:
with open("/tmp/ankni_cmd", "w") as f:
    f.write(f"vib {intensity} {duration}")
```

Example MCP tool wrapper: see [our blog post / Xiaohongshu post].

---

## Known issues / gotchas

| Issue | Cause | Fix |
|-------|-------|-----|
| Disconnect after ~2 min | websockets library keepalive ping timeout | `ping_interval=None, ping_timeout=None` |
| `errNo: -1` | Token expired or already used | Get a fresh share link |
| Only one motor responds | Wrong vib array format for DS device | Use DS motor mapping above |
| Device doesn't respond at all | op:15 not received (device offline) | Ensure toy is powered on |

---

## Credits

Protocol reverse-engineered via browser DevTools + JS bundle analysis.  
Motor mapping discovered through live empirical testing.
