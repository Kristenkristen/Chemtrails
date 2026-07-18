# phantom-touch-bridge

> 通过玩具自带的 WebSocket 中继控制云端远程玩具——不需要蓝牙，不需要近距离。  
> 只要有网络，随时随地可控制。专为 AI 辅助远程控制设计。

---

## 前提条件

**玩具端**
- 你的玩具 APP 能生成**远程控制链接**（邀请好友控制）
- 这个链接可以**直接在手机或电脑浏览器里打开**（不需要 APP，不需要扫码）
- 不满足这个条件的玩具（纯蓝牙、必须开 APP 才能用的）目前不支持

**运行环境**
```bash
# Python 3.10+
pip install websockets       # 连接玩具 WebSocket 用
pip install fastmcp          # 仅使用 mcp_toy_tools.py / mcp_template.py 时需要
```

---

## 原理

绝大多数云端玩具通过**WebSocket 中继服务器**工作：

```
手机（玩具持有方）←──→ 品牌 WS 中继服务器 ←──→ 控制端（你/你的AI）
```

玩具生成的分享链接里含有 session token。任何"打开"这个链接的人都会以控制端身份接入中继。我们跳过浏览器，直接用 Python 连接。

---

## 支持的设备

| 设备 | 品牌 | 协议 | 马达 |
|------|------|------|------|
| AKN_DS_SUCKEGG | 安可尼 / MonsterParty | MonsterParty WS | 吸力 + 震动（双马达） |
| 安可尼单马达设备 | 安可尼 | MonsterParty WS | 震动 |
| 其他品牌 | — | 见 `template.py` | 因设备而异 |

> 使用同一 MonsterParty 后端的品牌（同属醉清风健康科技）：**谜姬**、**安可尼**、**醉清风**——协议相同，op 码相同。

---

## 快速开始（安可尼 / MonsterParty）

```bash
pip install websockets

# 启动 daemon — token 来自分享链接路径：
# https://www.monsterparty.cn/remote/<TOKEN>
python3 ankni_client.py <TOKEN>

# 另开一个终端发命令：
echo "vib 70"        > /tmp/ankni_cmd   # 70% 强度持续震动
echo "vib 60 3"      > /tmp/ankni_cmd   # 60% 持续 3 秒后自动停止
echo "vib 50 80"     > /tmp/ankni_cmd   # 双马达设备：吸力=50，震动=80
echo "stop"          > /tmp/ankni_cmd   # 停止所有马达
echo "quit"          > /tmp/ankni_cmd   # 断开 daemon
```

### 状态文件

```bash
cat /tmp/ankni_state
# {"sender_fd": 12296, "ready": true, "pid": "AKN_DS_SUCKEGG", "key_type": "suck", "is_ds": true}
```

---

## 协议细节（MonsterParty）

### 获取 session

```
GET https://api.monsterparty.cc/main/v1/remote?s=<token>
→ { data: { socket_url, id (sess_id), user_id } }
```

### WebSocket 握手

```json
// 1. 连接 socket_url，Origin: https://www.monsterparty.cn
// 2. 发加入消息：
{ "op": 2, "id": 8899001, "gender": "male", "remoteID": <sess_id>,
  "senderID": <user_id>, "avatar": "", "nickname": "remote",
  "lat": 0, "lng": 0, "area": "" }

// 3. 等待 op:6（fd 分配）：
{ "op": 6, "sender": { "fd": 12296 }, "isSuck": false }

// 4. 等待 op:15（设备就绪——玩具已连线）：
{ "op": 15, "conn": true, "pid": "AKN_DS_SUCKEGG" }
```

### 控制指令

```json
{ "op": 3, "vib": [70, 70, 70, 70, 70, 70, 70, 70, 70, 70],
  "fd": <sender_fd>, "keyType": "suck" }
```

`vib` 始终是 10 位整数数组（0–100）。`keyType` 对吸力类设备为 `"suck"`，否则为 `"vib"`。

### 心跳

```json
{ "op": 8 }   // 每 ~9 秒发一次
```

⚠️ **必须禁用 websockets 库自带的 ping**（`ping_interval=None, ping_timeout=None`）——否则会导致莫名断连。只用 op:8 应用层心跳。

### AKN_DS_SUCKEGG 双马达映射

通过实测位置隔离发现：

| vib 数组位置 | 马达 |
|-------------|------|
| `[0]` | 吸力泵 |
| `[1]`、`[2]`、`[3]`、`[4]` | 震动马达 |
| `[5]`–`[9]` | 未使用 |

独立控制两个马达：
```python
vib = [吸力强度, 震动强度, 震动强度, 震动强度, 震动强度, 0, 0, 0, 0, 0]
```

---

## 用哪个文件？

| 你的设备品牌 | 推荐方案 |
|-------------|---------|
| 安可尼 / 谜姬 / 醉清风（MonsterParty 后端） | **`mcp_toy_tools.py`** — 完整实现，直接用 |
| 其他品牌，想要 MCP 工具 | **`mcp_template.py`** — 通用 MCP 模板，填 6 个参数 |
| 其他品牌，只要控制脚本 | **`template.py`** — 通用脚本模板，填参数 |

> 不知道自己的品牌用什么后端？先按 `AI_GUIDE.md` 抓接口，AI 帮你分析。

## 其他品牌适配

参见 `template.py` / `mcp_template.py`（有详细注释）和 `AI_GUIDE.md`（AI 执行步骤）。

通用步骤：
1. 用浏览器开发者工具打开分享链接，Network 标签抓接口
2. 找到 WebSocket 连接和消息
3. 下载主 JS 文件，搜索 `"op"`、`"vib"`、`send(`
4. 填入 `template.py` 对应常量

---

## AI 集成

daemon 使用文件 IPC（`/tmp/ankni_cmd`），任何进程——包括 AI agent——都可以直接发命令，不需要管理 WebSocket 状态：

```python
# AI 工具实现示例：
with open("/tmp/ankni_cmd", "w") as f:
    f.write(f"vib {intensity} {duration}")
```

详细的 AI 执行教程见 `AI_GUIDE.md`。

---

## 常见坑

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 约 2 分钟后断连 | websockets 库 keepalive ping 超时 | `ping_interval=None, ping_timeout=None` |
| `errNo: -1` | token 已过期或已被使用 | 重新获取分享链接 |
| 只有一侧马达响应 | 双马达设备 vib 数组格式不对 | 用上方 DS 映射格式 |
| 设备完全没反应 | 未收到 op:15（设备离线） | 确认玩具已开机 |

---

## 致谢

协议通过浏览器 DevTools + JS 分析逆向工程获得。  
双马达映射通过实测逐位排查发现。
