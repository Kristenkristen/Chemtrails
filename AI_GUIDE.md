# 云端远程玩具控制 · AI 执行附件

> **前提**：分享链接能在手机/电脑浏览器直接打开（不需要 APP）。满足这个条件，以下方法对任意品牌都适用。

---

## Step 1 · 用户操作：抓接口

打开分享链接，同时打开浏览器开发者工具：
- Windows/Linux：F12
- Mac：Cmd + Option + I

进入 **Network** 标签 → 刷新页面 → 截图发给你的 AI。

AI 要找的东西：
- XHR/Fetch 请求里有没有返回 WebSocket 地址（`ws://` 或 `wss://`）
- WS 标签里有没有已建立的 WebSocket 连接和消息

---

## Step 2 · AI 操作：分析 JS 找协议

找到页面加载的主 JS 文件（通常叫 `main.js`，Flutter 应用叫 `main.dart.js`），下载下来。

搜索关键词：
- `"op"` / `op:` → 操作码
- `WebSocket` / `connect` → 连接逻辑
- `send(` → 消息发送位置
- `vib` / `intensity` / `level` → 控制参数名

目标是找到：
1. **握手消息格式**：连上 WebSocket 后第一条要发什么
2. **控制指令格式**：震动/停止的消息长什么样
3. **动态参数来源**：哪些值需要从服务器响应里拿（如 fd、session_id）

---

## Step 3 · AI 操作：写连接脚本

通用流程结构（具体参数从 Step 2 挖出来填入）：

```python
import asyncio, json, urllib.request, urllib.parse, os
import websockets

# 1. REST API 拿 session 信息（WebSocket 地址 + session 参数）
token = "用户提供的 token"
# 具体接口地址从 DevTools Network 里看

# 2. 连接 WebSocket
async with websockets.connect(ws_url, additional_headers={
    "Origin": "品牌官网域名",
    "User-Agent": "手机浏览器 UA"
}) as ws:

    # 3. 发握手消息
    await ws.send(json.dumps({ 握手格式 }))

    # 4. 等设备就绪，提取动态参数（fd 或类似值）
    dynamic_param = None
    for _ in range(15):
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
        if 设备就绪条件:
            dynamic_param = msg[...]
            break

    # 5. 心跳（按品牌间隔发，防断线）
    async def heartbeat():
        while True:
            await asyncio.sleep(间隔秒数)
            await ws.send(json.dumps({ 心跳格式 }))
    asyncio.create_task(heartbeat())

    # 6. 命令循环（文件 IPC）
    while True:
        await asyncio.sleep(0.3)
        if os.path.exists("/tmp/toy_cmd"):
            cmd = open("/tmp/toy_cmd").read().strip()
            os.unlink("/tmp/toy_cmd")
            # 根据 cmd 发控制指令
            await ws.send(json.dumps({ 控制指令格式, "intensity": ... }))

asyncio.run(run())
```

---

## Step 4 · 持久化运行

后台启动脚本，通过文件传命令：

```bash
# 启动 daemon
python3 script.py <token> &

# 控制（具体格式看脚本实现）
echo "vib 80 3" > /tmp/toy_cmd   # 震动强度80，持续3秒
echo "stop"    > /tmp/toy_cmd   # 停止
echo "quit"    > /tmp/toy_cmd   # 退出 daemon
```

这样 AI 连接一次后可以随时发指令，不需要每次重连（避免 token 失效问题）。

---

## 常见坑

| 问题 | 原因 | 解决 |
|------|------|------|
| 连上了但设备没反应 | 控制参数格式错误（数组 vs 标量、参数名不对） | 回 JS 里确认格式 |
| `errNo: -1` | token 已失效（断线后不可复用） | 让用户重新分享链接 |
| 没有 WS 连接 | 链接不是 WebSocket 方案，可能是轮询或其他协议 | 看 XHR 频率，换思路 |
| 服务器无响应 | 少发了握手消息 | 确认连接后第一条消息是否发了 |
| 心跳没发导致断线 | 忘了 heartbeat 任务 | 加心跳，间隔参考品牌 APP 行为 |
