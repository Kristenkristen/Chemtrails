#!/usr/bin/env python3
"""
BLE Relay Server for ANKNI JH1
- WebSocket server (port 8769): accepts connection from ble_debug.html
- HTTP server (port 8770): accepts commands from main window via exec_vps
Protocol: AA 08 04 [ext] [vib] [suc] [heat] [cs] sent every 200ms
"""
import asyncio
import json
import logging
import signal
import struct
from http.server import BaseHTTPRequestHandler
from io import BytesIO
import threading
import time

import websockets

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)

# Shared state
state = {
    "ext": 0,   # extension  0-100
    "vib": 0,   # vibration  0-100
    "suc": 0,   # suction    0-100
    "heat": 0,  # heat       0-100
    "active": False,
    "connected": False,
}
bridge_ws = None  # WebSocket connection from ble_debug.html
rx_log = []       # Device notifications


def make_cmd(ext, vib, suc, heat):
    cs = (0xAA + 0x08 + 0x04 + ext + vib + suc + heat) & 0xFF
    return [0xAA, 0x08, 0x04, ext, vib, suc, heat, cs]


async def handle_bridge(websocket):
    global bridge_ws, state
    bridge_ws = websocket
    state["connected"] = True
    log.info("BLE bridge connected")
    try:
        async for msg in websocket:
            try:
                data = json.loads(msg)
                rx_log.append(data)
                if len(rx_log) > 200:
                    rx_log.pop(0)
                log.info(f"RX from device: {data}")
            except Exception:
                pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        bridge_ws = None
        state["connected"] = False
        log.info("BLE bridge disconnected")


# ── HTTP command server ──────────────────────────────────────────────────────

class CmdHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # suppress HTTP logs

    def do_GET(self):
        if self.path == "/status":
            body = json.dumps({**state, "rx_log": rx_log[-10:]}).encode()
            self._respond(200, body)
        elif self.path == "/stop":
            state.update(ext=0, vib=0, suc=0, heat=0, active=False)
            asyncio.run_coroutine_threadsafe(send_cmd_once(), loop)
            self._respond(200, b'{"ok":true}')
        else:
            self._respond(404, b'not found')

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            self._respond(400, b'bad json')
            return

        if self.path == "/set":
            state["ext"]  = max(0, min(100, int(data.get("ext", state["ext"]))))
            state["vib"]  = max(0, min(100, int(data.get("vib", state["vib"]))))
            state["suc"]  = max(0, min(100, int(data.get("suc", state["suc"]))))
            state["heat"] = max(0, min(100, int(data.get("heat", state["heat"]))))
            state["active"] = any(state[k] > 0 for k in ("ext","vib","suc","heat"))
            asyncio.run_coroutine_threadsafe(send_cmd_once(), loop)
            self._respond(200, json.dumps(state).encode())
        else:
            self._respond(404, b'not found')

    def _respond(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


async def send_cmd_once():
    if bridge_ws:
        try:
            cmd = make_cmd(state["ext"], state["vib"], state["suc"], state["heat"])
            await bridge_ws.send(json.dumps({"type": "cmd", "bytes": cmd}))
        except Exception:
            pass  # bridge disconnected mid-send; handle_bridge will clean up


async def keepalive_loop():
    """Send current state every 500ms while active, keepalive every 5s when idle."""
    last_keepalive = 0
    while True:
        await asyncio.sleep(0.5)
        if bridge_ws:
            try:
                if state["active"]:
                    await send_cmd_once()
                elif time.time() - last_keepalive >= 5:
                    # Keepalive: all motors off (AA 08 04 00 00 00 00 B6)
                    await bridge_ws.send(json.dumps({
                        "type": "cmd",
                        "bytes": [0xAA, 0x08, 0x04, 0x00, 0x00, 0x00, 0x00, 0xB6]
                    }))
                    last_keepalive = time.time()
            except Exception:
                pass  # bridge disconnect mid-send; loop must not crash


loop = None


async def main():
    global loop
    loop = asyncio.get_running_loop()

    # WebSocket server for BLE bridge
    ws_server = await websockets.serve(handle_bridge, "0.0.0.0", 8769)
    log.info("WebSocket relay on ws://0.0.0.0:8769")

    # HTTP command server in thread
    from http.server import HTTPServer
    http = HTTPServer(("127.0.0.1", 8770), CmdHandler)
    t = threading.Thread(target=http.serve_forever, daemon=True)
    t.start()
    log.info("HTTP API on http://127.0.0.1:8770")

    await keepalive_loop()


if __name__ == "__main__":
    asyncio.run(main())
