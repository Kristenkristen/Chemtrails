# 蓝牙逆向工程教程：无云API控制任意BLE玩具

> 适用场景：玩具没有远程控制链接、不支持 MonsterParty / Lovense 等云端协议，  
> 但有配套 APP、支持蓝牙（BLE）控制。  
> 只要能用 APP 操控，就能逆向出协议，再通过浏览器 Web Bluetooth 实现 AI / 远程控制。

---

## 原理

```
AI / 控制端
    │  HTTP POST /set
    ▼
中继服务器 (Python, VPS 或 Termux+ngrok)
    │  WebSocket ws://...
    ▼
浏览器页面 (Chrome/Android) ← Web Bluetooth API
    │  BLE GATT Write
    ▼
玩具
```

云端方案（见 README）需要品牌服务器配合。这条路线完全绕开品牌，直接用蓝牙通信：

1. 用 **nRF Connect** 抓取 APP 发给玩具的原始 BLE 命令
2. 找出协议格式（字段含义 + 校验和算法）
3. 写一个 Python **中继服务器**，对外暴露 HTTP API
4. 用 **Chrome Web Bluetooth**（运行在安卓手机上）当 BLE 桥接器
5. AI 或任何脚本调 HTTP API → 中继 → 蓝牙 → 玩具

---

## 需要准备什么

| 必须 | 说明 |
|------|------|
| 安卓手机 | iOS 不支持 Web Bluetooth API，只能用安卓 |
| Chrome 浏览器 | 手机上已有 Chrome 即可，不需要电脑 |
| BLE 玩具 | 任何有蓝牙控制的玩具，有配套 APP |
| nRF Connect（安卓 APP） | 用于抓取蓝牙协议，Google Play 免费安装 |

| 可选 | 说明 |
|------|------|
| VPS | 托管中继服务器（公网可访问），AI 远程控制必须 |
| Termux（安卓终端） | 替代 VPS，在手机本地跑 Python，不需要服务器 |
| ngrok | 配合 Termux 将本地端口暴露到公网，实现 AI 远程控制 |

> **最简配置（只需本地控制）**：安卓手机 + 玩具 + nRF Connect + Chrome + Termux
> **AI 远程控制**：上面的 + VPS（或 Termux + ngrok）

---

## 第一步：用 nRF Connect 抓取协议

### 1.1 安装并打开 nRF Connect

Google Play 搜索 **nRF Connect for Mobile**，安装后打开。

### 1.2 扫描设备

点 **SCAN**，找到你的玩具（名字通常是品牌名或型号）。  
点击设备名称 → **CONNECT**。

### 1.3 找到写入特征（Write Characteristic）

连上后会看到 GATT 服务列表。展开每个服务，寻找属性包含 `WRITE` 或 `WRITE WITHOUT RESPONSE` 的特征（Characteristic）。

> 提示：玩具通常有 1–2 个可写特征，其中一个是控制通道，另一个可能是配置或 OTA 固件升级用的。先都记下来。

记录：
- 写入特征的 **UUID**（类似 `0000aabb-0000-1000-8000-00805f9b34fb`）
- 所属服务的 **UUID**

### 1.4 订阅通知（Notify Characteristic）

如果设备有 `NOTIFY` 属性的特征，也订阅上（点 ▶ 箭头）。这是设备状态回传通道，可以看到玩具的实时反馈，帮助确认命令是否生效。

### 1.5 用 APP 操控玩具，同时观察 nRF Connect 日志

**关键步骤**：

1. 保持 nRF Connect 连着玩具
2. 打开玩具官方 APP（大部分 APP 会自动重连，或者 nRF 断开后再用 APP 连）
3. 在 APP 里调整不同的强度（震动 0% → 30% → 60% → 100%）
4. 切回 nRF Connect，在写入特征下方会看到日志，格式类似：

```
[10:23:45] WRITE: aa 08 04 00 1e 00 00 28
[10:23:46] WRITE: aa 08 04 00 3c 00 00 46
[10:23:47] WRITE: aa 08 04 00 64 00 00 6e
```

> 如果 APP 连上后 nRF 断连，说明该设备不支持同时连两个蓝牙客户端（大部分 BLE 设备只支持一个主连接）。  
> 解决方法：在 nRF Connect 里直接发原始命令测试，不用 APP。或者借助 **BLE sniffer**（需要额外硬件）。

---

## 第二步：分析协议格式

### 2.1 找规律

把抓到的命令整理成表格，对比不同操作时哪些字节在变化：

| 操作 | 原始命令（hex） |
|------|----------------|
| 全停 | `aa 08 04 00 00 00 00 b6` |
| 震动30% | `aa 08 04 00 1e 00 00 d4` |
| 震动60% | `aa 08 04 00 3c 00 00 f2` |
| 震动100% | `aa 08 04 00 64 00 00 1a` |
| 吸力50% | `aa 08 04 00 00 32 00 e8` |

固定不变的字节 → 是协议头或马达无关的固定字段。  
随操作变化的字节 → 对应某个马达的强度。

### 2.2 验证校验和

通常最后一个字节是校验和（checksum）。常见算法：

```python
# 所有字节相加取低8位（最常见）
cs = sum(bytes[:-1]) & 0xFF

# 例如 aa 08 04 00 1e 00 00 → 0xAA+0x08+0x04+0x00+0x1E+0x00+0x00 = 0xD4 ✓
```

用几条命令验证一下，算出来对就是这个算法。不对的话试试 XOR、减法、CRC8 等变体。

### 2.3 ANKNI JH1 协议（示例）

以安可尼 JH1 型号为例，通过 nRF Connect 逆向得到的协议：

```
格式：AA 08 04 [ext] [vib] [suc] [heat] [checksum]
长度：8 字节
频率：每 500ms 发送一次（持续发送保持状态）

字段说明：
  AA 08 04  — 固定协议头
  ext       — 伸缩马达 (0–100)
  vib       — 震动马达 (0–100)
  suc       — 吸力泵   (0–100)
  heat      — 加热元件 (0–100)
  checksum  — (0xAA + 0x08 + 0x04 + ext + vib + suc + heat) & 0xFF

示例：
  吸力80% + 震动40%: AA 08 04 00 28 50 00 [cs]
  checksum = (0xAA + 0x08 + 0x04 + 0x00 + 0x28 + 0x50 + 0x00) & 0xFF = 0x36
  完整命令: AA 08 04 00 28 50 00 36
```

---

## 第三步：在 nRF Connect 里验证

逆向出协议后，直接在 nRF Connect 里发命令测试，不依赖 APP：

1. 连接玩具
2. 找到写入特征，点击向上箭头（写入）
3. 选 `BYTE ARRAY`，输入你构造的命令（不带空格，如 `AA08040000500036`）
4. 确认玩具有反应

如果吸力字段控制的是吸力泵，震动字段控制的是震动马达，说明协议已确认。  
如果反应不对，重新排查字段顺序（把强度值挪到不同位置）。

---

## 第四步：搭建中继服务器

### `ble_relay.py`

这是中继的核心：

- **WebSocket 服务器**（端口 8769）：接受来自浏览器桥接页面的连接，负责把命令转发到浏览器（再由浏览器发给玩具）
- **HTTP API**（端口 8770, localhost）：接受来自 AI / 控制脚本的命令

```python
#!/usr/bin/env python3
"""
BLE Relay Server — 通用模板
修改 make_cmd() 适配你的设备协议即可。
"""
import asyncio, json, logging, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
import websockets

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)

# 当前马达状态
state = {
    "ext": 0, "vib": 0, "suc": 0, "heat": 0,
    "active": False, "connected": False,
}
bridge_ws = None  # 来自浏览器的 WebSocket 连接
rx_log = []       # 设备回传的通知数据

# ── 修改这里适配你的设备协议 ────────────────────────────────────────────────

def make_cmd(ext, vib, suc, heat):
    """构造发给设备的 BLE 命令字节序列。"""
    cs = (0xAA + 0x08 + 0x04 + ext + vib + suc + heat) & 0xFF
    return [0xAA, 0x08, 0x04, ext, vib, suc, heat, cs]

KEEPALIVE_CMD = [0xAA, 0x08, 0x04, 0x00, 0x00, 0x00, 0x00, 0xB6]  # 全停心跳
SEND_INTERVAL = 0.5   # 命令发送间隔（秒）
KEEPALIVE_INTERVAL = 5  # 空闲心跳间隔（秒）

# ─────────────────────────────────────────────────────────────────────────────

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
                log.info(f"Device notification: {data}")
            except Exception:
                pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        bridge_ws = None
        state["connected"] = False
        log.info("BLE bridge disconnected")


async def send_cmd_once():
    if bridge_ws:
        try:
            cmd = make_cmd(state["ext"], state["vib"], state["suc"], state["heat"])
            await bridge_ws.send(json.dumps({"type": "cmd", "bytes": cmd}))
        except Exception:
            pass


async def keepalive_loop():
    last_keepalive = 0
    while True:
        await asyncio.sleep(SEND_INTERVAL)
        if bridge_ws:
            try:
                if state["active"]:
                    await send_cmd_once()
                elif time.time() - last_keepalive >= KEEPALIVE_INTERVAL:
                    await bridge_ws.send(json.dumps({"type": "cmd", "bytes": KEEPALIVE_CMD}))
                    last_keepalive = time.time()
            except Exception:
                pass


class CmdHandler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

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
            for k in ("ext", "vib", "suc", "heat"):
                if k in data:
                    state[k] = max(0, min(100, int(data[k])))
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


loop = None

async def main():
    global loop
    loop = asyncio.get_running_loop()
    ws_server = await websockets.serve(handle_bridge, "0.0.0.0", 8769)
    log.info("WebSocket relay on ws://0.0.0.0:8769")
    http = HTTPServer(("127.0.0.1", 8770), CmdHandler)
    t = threading.Thread(target=http.serve_forever, daemon=True)
    t.start()
    log.info("HTTP API on http://127.0.0.1:8770")
    await keepalive_loop()

if __name__ == "__main__":
    asyncio.run(main())
```

### HTTP API 说明

```bash
# 设置马达强度（任意组合，不传的字段保持当前值）
curl -X POST http://127.0.0.1:8770/set \
  -H "Content-Type: application/json" \
  -d '{"suc": 70, "vib": 40}'

# 查当前状态
curl http://127.0.0.1:8770/status

# 立即停止所有马达
curl http://127.0.0.1:8770/stop
```

---

## 第五步：搭建浏览器桥接页面

Web Bluetooth API 只能在浏览器里运行，所以需要一个网页充当 BLE 桥接器。

把下面这段 HTML 保存为 `toy_bridge.html`，放到任何可以在手机 Chrome 里打开的地方（本地文件、Web 服务器、VPS 均可，但必须是 HTTPS 或 localhost）。

> **⚠️ Web Bluetooth 限制**：Chrome 要求页面通过 HTTPS 加载才能使用 Web Bluetooth API（localhost 例外）。如果放在 VPS 上，需要配置 TLS 证书（Let's Encrypt 免费）。

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BLE Bridge</title>
<style>
  body { font-family: monospace; max-width: 480px; margin: 20px auto; padding: 0 16px; }
  button { margin: 6px 4px; padding: 8px 16px; font-size: 14px; }
  #log { height: 200px; overflow-y: auto; background: #111; color: #0f0;
         padding: 8px; font-size: 12px; margin-top: 12px; }
  .ok { color: #0f0; } .err { color: #f44; } .info { color: #88f; }
</style>
</head>
<body>
<h3>BLE Bridge</h3>

<div>
  <b>中继服务器地址：</b><br>
  <input id="wsUrl" value="wss://your-vps-domain.com/ble-ws" style="width:100%;margin:4px 0">
</div>

<div>
  <b>BLE 写入特征 UUID：</b><br>
  <input id="writeUUID" placeholder="留空使用设备默认" style="width:100%;margin:4px 0">
</div>

<div>
  <button onclick="connectBLE()">连接蓝牙</button>
  <button onclick="disconnectBLE()">断开蓝牙</button>
  <span id="bleStatus">未连接</span>
</div>
<div>
  <button onclick="connectRelay()">连接中继</button>
  <button onclick="disconnectRelay()">断开中继</button>
  <span id="relayStatus">未连接</span>
</div>

<div id="log"></div>

<script>
const DEFAULT_SERVICE_UUID = ''; // 留空=扫描所有服务
let device, server, cachedWriteChar = null;
let relayWs = null, relayAutoReconnect = false, relayReconnectTimer = null;
let writeInProgress = false;
let relayLoopTimer = null;

function log(msg, cls='ok') {
  const d = document.getElementById('log');
  d.innerHTML += `<div class="${cls}">[${new Date().toLocaleTimeString()}] ${msg}</div>`;
  d.scrollTop = d.scrollHeight;
}

function setBleStatus(ok) {
  document.getElementById('bleStatus').textContent = ok ? '✓ 已连接' : '✗ 未连接';
  document.getElementById('bleStatus').style.color = ok ? '#0f0' : '#f44';
}
function setRelayStatus(ok) {
  document.getElementById('relayStatus').textContent = ok ? '✓ 已连接' : '✗ 未连接';
  document.getElementById('relayStatus').style.color = ok ? '#0f0' : '#f44';
}

async function cacheWriteChar() {
  const uuid = document.getElementById('writeUUID').value.trim();
  if (!server) return null;
  try {
    const services = await server.getPrimaryServices();
    for (const svc of services) {
      try {
        const chars = await svc.getCharacteristics();
        for (const c of chars) {
          if (c.properties.write || c.properties.writeWithoutResponse) {
            if (!uuid || c.uuid === uuid) {
              cachedWriteChar = c;
              log(`写入特征已缓存: ${c.uuid}`, 'info');
              return c;
            }
          }
        }
      } catch {}
    }
  } catch(e) { log('缓存写入特征失败: ' + e.message, 'err'); }
  return null;
}

async function connectBLE() {
  try {
    const opts = { acceptAllDevices: true, optionalServices: ['generic_attribute'] };
    device = await navigator.bluetooth.requestDevice(opts);
    device.addEventListener('gattserverdisconnected', () => {
      setBleStatus(false);
      cachedWriteChar = null;
      log('蓝牙断开', 'err');
    });
    server = await device.gatt.connect();
    setBleStatus(true);
    log('蓝牙已连接: ' + device.name, 'info');
    await cacheWriteChar();
  } catch(e) { log('蓝牙连接失败: ' + e.message, 'err'); }
}

function disconnectBLE() {
  if (device && device.gatt.connected) device.gatt.disconnect();
}

async function writeBLE(bytes) {
  if (writeInProgress) return;
  writeInProgress = true;
  try {
    const c = cachedWriteChar || await cacheWriteChar();
    if (!c) { log('无可用写入特征', 'err'); return; }
    const buf = new Uint8Array(bytes);
    if (c.properties.writeWithoutResponse && !c.properties.write) {
      await c.writeValueWithoutResponse(buf);
    } else {
      await c.writeValueWithResponse(buf);
    }
  } catch(e) { log('BLE 写入错误: ' + e.message, 'err'); }
  finally { writeInProgress = false; }
}

function connectRelay() {
  if (relayReconnectTimer) { clearTimeout(relayReconnectTimer); relayReconnectTimer = null; }
  if (relayWs) relayWs.close();
  relayAutoReconnect = true;
  const url = document.getElementById('wsUrl').value.trim();
  relayWs = new WebSocket(url);

  relayWs.onopen = async () => {
    setRelayStatus(true);
    log('中继已连接，等待指令…', 'info');
    if (server && !cachedWriteChar) await cacheWriteChar();
  };

  relayWs.onmessage = async (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === 'cmd' && msg.bytes) {
        await writeBLE(msg.bytes);
      }
    } catch(ex) { log('中继消息解析错误: ' + ex.message, 'err'); }
  };

  relayWs.onerror = () => log('中继连接错误', 'err');
  relayWs.onclose = () => {
    setRelayStatus(false);
    relayWs = null;
    if (relayAutoReconnect) {
      log('中继断开，3秒后自动重连…', 'err');
      relayReconnectTimer = setTimeout(connectRelay, 3000);
    }
  };
}

function disconnectRelay() {
  relayAutoReconnect = false;
  if (relayReconnectTimer) { clearTimeout(relayReconnectTimer); relayReconnectTimer = null; }
  if (relayWs) { relayWs.close(); relayWs = null; }
  setRelayStatus(false);
}

// 保持屏幕常亮
if ('wakeLock' in navigator) {
  navigator.wakeLock.request('screen').catch(() => {});
}
</script>
</body>
</html>
```

---

## 第六步：启动并测试

### 方案 A：VPS（AI 远程控制推荐）

```bash
# 安装依赖
pip install websockets

# 启动中继服务器
python3 ble_relay.py

# 如果 VPS 有防火墙，开放 8769 端口（WebSocket 用）
# HTTP 8770 不需要对外开放，只走 localhost

# 也可以通过 nginx 反代 WebSocket（推荐，配合 TLS）：
# location /ble-ws { proxy_pass http://127.0.0.1:8769; proxy_http_version 1.1;
#   proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; }
```

设为开机自启（systemd）：

```ini
# /etc/systemd/system/ble-relay.service
[Unit]
Description=BLE Relay Server
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /path/to/ble_relay.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now ble-relay
```

### 方案 B：Termux（纯手机，无需服务器）

安装 [Termux](https://termux.dev/)（F-Droid 版，不是 Google Play 版）：

```bash
# 在 Termux 里安装 Python
pkg install python
pip install websockets

# 同时启动中继服务器和文件服务器
python3 ble_relay.py &
python3 -m http.server 8080 --directory /path/to/Chemtrails
```

然后在手机 Chrome 里打开：
```
http://localhost:8080/toy_bridge.html
```

> ✅ `localhost` 对 Web Bluetooth API **豁免 HTTPS 限制**，直接可用。  
> 将页面里的中继地址改为 `ws://localhost:8769`，全程不需要任何服务器。

如果需要 AI / 外部远程控制，加一个 ngrok 暴露端口：

```bash
pkg install tsu   # 可选，用于获取更多权限
# 下载 ngrok：https://ngrok.com/download（ARM 版）
./ngrok tcp 8769   # 暴露 WebSocket 端口
# ngrok 会给一个 tcp://xxx.ngrok.io:xxxxx 的地址
# 将 toy_bridge.html 里的中继地址换成 wss://... 即可
```

### 方案 C：GitHub Pages（不想跑 Termux，只需托管网页）

如果只需要托管桥接网页（中继服务器仍需 Termux 或 VPS）：

1. 创建一个 GitHub 仓库，把 `toy_bridge.html` 上传
2. 仓库设置 → Pages → 选择 `main` 分支
3. 网页会自动发布到 `https://你的用户名.github.io/仓库名/toy_bridge.html`

> GitHub Pages 自带 HTTPS，满足 Web Bluetooth 的安全上下文要求，完全免费。

### 方案对比

| | VPS | Termux 纯本地 | Termux + ngrok | GitHub Pages + Termux |
|--|-----|--------------|---------------|----------------------|
| 需要服务器 | ✓ VPS | ✗ | ✗ | ✗ |
| AI 远程控制 | ✓ | ✗（本地限制） | ✓ | ✓（需 Termux 跑中继） |
| 安装难度 | 中 | 低 | 低 | 低 |
| 费用 | VPS 费用 | 免费 | 免费额度内 | 免费 |

### 测试流程

1. 启动 `ble_relay.py`
2. 手机 Chrome 打开桥接页面（`toy_bridge.html`）
3. 填入中继 WebSocket 地址，点"连接中继"
4. 点"连接蓝牙"，选择玩具
5. 在另一个终端发命令测试：

```bash
# 吸力 50%
curl -X POST http://127.0.0.1:8770/set \
  -H "Content-Type: application/json" \
  -d '{"suc": 50}'

# 震动 30%
curl -X POST http://127.0.0.1:8770/set \
  -d '{"vib": 30}' -H "Content-Type: application/json"

# 停止
curl http://127.0.0.1:8770/stop
```

---

## AI 集成

中继暴露的 HTTP API 可以直接被任何 AI agent 调用：

```python
import requests

def set_toy(suc=0, vib=0, ext=0, heat=0):
    """设置玩具强度（0–100）"""
    requests.post("http://127.0.0.1:8770/set",
                  json={"suc": suc, "vib": vib, "ext": ext, "heat": heat})

def stop_toy():
    requests.get("http://127.0.0.1:8770/stop")

def toy_status():
    return requests.get("http://127.0.0.1:8770/status").json()
```

---

## 常见问题

| 问题 | 原因 | 解决方法 |
|------|------|---------|
| "Web Bluetooth is not supported" | iOS Safari / 微信内置浏览器不支持 | 必须用 Android + Chrome |
| 蓝牙连上后立刻断开 | BLE 设备只允许一个主连接，APP 还占着 | 先关掉官方 APP 再连 |
| 发命令没反应 | 写入特征 UUID 不对 | 不填 UUID 让页面自动遍历所有可写特征 |
| 桥接页面切到后台断连 | Chrome 后台限制 WebSocket | 页面已加自动重连（3秒），保持屏幕常亮 |
| 只有第一条命令有效 | 旧版页面每次都重新 getPrimaryServices | 用已有 cachedWriteChar 缓存特征 |
| 校验和算法不对 | 不同品牌算法不一样 | 试试 XOR 累加、减法、CRC8 |
| VPS 上 WebSocket 连不上 | 防火墙没开 8769 端口 | `ufw allow 8769` 或改用 nginx 反代 |

---

## 如何逆向你自己的设备

这篇教程以 ANKNI JH1 为例，但思路通用：

1. **nRF Connect 抓包**：用 APP 操作各个功能，观察 WRITE 日志里哪些字节在变
2. **逐字段隔离**：每次只改一个功能（只调震动不动其他），找出对应字段
3. **验证校验和**：最后一字节通常是校验和，试试 sum & 0xFF
4. **修改 `make_cmd()`**：把逆向出的格式填进 `ble_relay.py` 的 `make_cmd()` 函数
5. **nRF Connect 直接发命令验证**：不用 APP，直接在 nRF 里发构造好的命令，确认玩具有反应

遇到复杂协议（加密、动态字段、握手序列）？把抓到的命令序列发给 AI 分析，通常能很快找出规律。

---

## 致谢

协议通过 nRF Connect 抓包 + 字段逐位排查逆向工程获得。  
BLE 通信层通过 Chrome Web Bluetooth API 实现，无需原生 APP。
