# 用 Agent 操作 FlowBot

Agent 运行在你选择的电脑或服务中。FlowBot 负责手机收发及事件交付，Agent 决定如何回复，不要求特定模型或 Agent 框架。接口契约见 [openapi.json](openapi.json)，项目 Skill 见 [use-flowbot](skills/use-flowbot/SKILL.md)。

## 接入所需资源

准备服务地址、私有管理配置 `config.json`、设备 ID、目标联系人的精确显示名，以及 IP 测试证书 `server.pem`。配置中的 `admin_token` 能操作全部设备，应只交给可信 Agent；手机只持有自己的设备密钥。所有凭据留在私有目录，不放入 Git、聊天、日志或命令参数。

管理客户端在 `independent` 目录执行，下文中的路径是占位符：

```bash
python3 client.py --config /private/config.json --url https://<服务器IP> \
  --ca /private/server.pem /devices
```

`last_seen` 是 Unix 秒；`state` 是 JSON 字符串。先确认连接时间新鲜、`ready/accessibility/notification/unlocked` 均为 `true`。第一期必须保持专用手机解锁、亮屏和充电。

## 订阅与 Webhook

先建立独立订阅，无需先发送消息或创建回复规则。将以下 JSON 保存为私有请求文件，使用 `client.py --method POST --body-file <文件> /subscriptions`：

```json
{"device_id":"phone1","contacts":["心向明月"],"listen_all":false}
```

`contacts` 最多 100 个精确显示名；同设备再次 POST 替换配置。空列表且 `listen_all=false` 停止接收。`listen_all=true` 接收系统可识别的私聊通知；前台界面补充路径仍只覆盖 `contacts` 中明确配置的私聊对象。需要前台接收的联系人始终填入列表。

Agent 可以使用自己的 HTTPS Webhook，也可以运行 [通用接收端](examples/webhook_receiver.py)。接收端应校验 Bearer token，将事件按 `event_id` 持久化并去重，提交后再返回 2xx。只返回 2xx 就会被视为交付成功。

配置文件内容如下，使用 `POST /webhook`；`ca_pem` 仅在接收端使用自签名证书时填写完整公钥证书：

```json
{"url":"https://agent.example.com/webhook","token":"<至少32字符的随机ASCII密钥>","enabled":true}
```

一个独立实例配置一个全局 Webhook，携带所有订阅设备的事件：

```json
{"type":"message.received","event_id":"<服务事件ID>","device_id":"phone1","contact":"心向明月","text":"今天是哪一天？","source":"wecom_accessibility","received_at":1791626400.0}
```

`contact` 是显示名，不是企业微信官方用户 ID。`source` 为 `wecom_notification` 或 `wecom_accessibility`。历史事件不会在初次配置 Webhook 后自动重放。非 2xx、超时或 TLS 错误会持久化重试，间隔 2、4、8 秒递增至最多 300 秒；后台重启继续交付。HTTP 重定向不跟随，Bearer 密钥不会转发到重定向目标。

`GET /webhook/deliveries` 查看最近 100 条交付记录，含 `event_id/status/attempts/next_attempt/last_status/last_error`。`retry` 时先修复地址、证书或接收端；不要新建同一条消息。关闭 Webhook 会暂停已有交付并停止为新事件建交付项，再开启会继续未完成项。

## 通用接收端

接收端只用 Python 标准库，收到事件后存入 SQLite，Agent 再通过 HTTP 读取。它与主后端可以部署在不同服务器；同机部署也使用独立进程、密钥和数据库。

```bash
python3 examples/webhook_receiver.py --host 127.0.0.1 --port 8789 \
  --db /private/agent-inbox.sqlite3 --token-file /private/webhook.token
```

本机 HTTP 用于测试；公网监听必须增加 `--cert <证书> --key <私钥>`。专用服务器已运行 `deploy.sh` 时，可以运行 `sudo bash deploy-receiver.sh <公网IPv4>`，复用服务器证书，监听 HTTPS 8443。仅在需要外部 Agent 读取这个示例时放通该端口。

接收端 `POST /webhook` 与 `GET /events?after=0` 都使用接收端密钥。以下命令不把密钥放入参数：

```bash
python3 client.py --token-file /private/webhook.token \
  --url https://<接收端IP>:8443 --ca /private/server.pem '/events?after=0'
```

响应为 `{"events":[...],"next_cursor":1}`；每条事件带接收端的整数 `cursor`。读取后按事件 ID 处理，成功确认回复任务及保存处理记录后再推进本地 cursor。Agent 重启先重用原事件的回复标识；不要因为读到同一事件就创建另一个发送请求。重复读取不会自动触发回复。

重试可能改变交付顺序，cursor 表示接收端落库顺序；需要整理会话上下文时结合 `received_at`，它是后端收到事件的时间，不是企业微信官方消息时间。

如果 Webhook 接收端不可用，也可用管理密钥读取后端 `GET /events?after=0&device_id=phone1&limit=100`。该响应的事件 ID 字段为 `id`、时间为 `received`；Webhook 为 `event_id/received_at`。两个队列的 cursor 各自独立，不能混用。

## 判断与回复

读取真实消息后，Agent 根据正文和上下文决定回复。将请求保存为文件：

```json
{"text":"今天是2026年10月10日。"}
```

```bash
python3 client.py --config /private/config.json --url https://<服务器IP> \
  --ca /private/server.pem --method POST --body-file /private/reply.json \
  /events/<event_id>/reply
```

服务从原事件确定设备和联系人。默认 `request_id=agent:<event_id>`；同一事件、同一正文再次调用返回原任务，同一标识改正文返回 400。如果确实需要第二条独立回复，显式提供新的稳定 `request_id`（最多 100 字符），并记录该决定。

返回 201 表示创建或找到了任务。继续 `GET /tasks/<id>`，直到终态：

- `succeeded`：手机确认新增文本气泡和清空输入框；不表示对方已读。
- `failed`：发送动作开始前失败，先处理原因。
- `unknown`：可能已发出，人工核对后再决定；不盲目重发。

主动推送使用 `POST /messages`，字段 `device_id/contact/text/request_id`；幂等规则相同。发送正文最多 2000 字符，接收正文最多 4000 字符。

从旧关键词模式切换时，先用 `GET /rules` 查看对应规则，再 `DELETE /rules`（正文 `device_id/contact`）删除该联系人的固定回复，避免与 Agent 同时回复。账号登录、验证码、实名及 Android 授权由操作员完成。

收消息有明确边界：通知必须包含可解析正文；前台补充基于已校准的企业微信界面，打开会话后的首次快照是基线，不重放旧聊天。短时间大量消息跨过整屏、滚动历史、未登录、被省电杀进程等情况不保证完整接收。详见 [README](README.md) 的恢复与验收记录。
