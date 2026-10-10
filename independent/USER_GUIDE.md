# FlowBot 独立版用户手册

适用于手机操作员、服务管理员和 Agent 接入者。本文覆盖 APK 获取、手机安装、消息收发、Webhook、部署和恢复，不需要查阅历史聊天记录。对应第一期版本 **0.2.0 / versionCode 2**，验收日期为 **2026-10-10（北京时间）**。

## 下载与资料入口

[飞书交付手册与附件下载](https://aihuanxi.feishu.cn/docx/NtbCdkQSjobu1VxfEs8co9g4nug)包含以下文件。下载需要登录飞书并具备文档阅读权限；没有权限时向文档所有者申请。本文可直接在仓库阅读，安装包也可按 [构建说明](README.md#可升级-apk)自行构建。

| 交付物 | 用途 |
| --- | --- |
| FlowBot 独立版 0.2.0.apk | 已签名、不可调试的 release 安装包，供 Android 11 及以上专用手机侧载 |
| FlowBot 0.2.0 完整交付包.zip | 解压为 `flowbot-0.2.0/`，含相同 APK、公钥证书、版本清单及 `independent/` 完整源码和资料 |
| server.pem | 交付测试实例的 TLS 公钥证书；新实例使用自己的证书 |
| FlowBot 0.2.0 OpenAPI.json | 机器可读 HTTP 契约；仓库版本见 [openapi.json](openapi.json) |

0.2.0 附件是固定版本，不会随仓库更新自动替换。可用 `shasum -a 256 <文件>` 或 Windows `Get-FileHash <文件> -Algorithm SHA256` 核对：

```text
APK SHA-256: f1492ada7a906ec5b4bb4b841a06273a3e4521642b8496eba698514b459dcb01
ZIP SHA-256: 26d5c329ab14b266b86f21809a01315a816c89be570a1acea47e7098c3c29177
交付源码: c7b34b69c56a54b514b5ac0240f1aa052ace6aa7
```

交付包不包含真实管理密钥、设备密钥、接收端密钥、账号凭据、TLS 私钥、APK 签名私钥或业务数据库。实际接入前向实例管理员私下领取所需配置。

| 继续阅读 | 解决的问题 |
| --- | --- |
| [Agent 指南](AGENT.md) | 事件、订阅、回复与 Agent 处理记录 |
| [OpenAPI](openapi.json) | 完整请求、返回字段、权限与约束 |
| [项目 Skill](skills/use-flowbot/SKILL.md) | 后续 Agent 的可执行使用指引 |
| [工程说明](README.md) | 构建、设备协议、服务部署与备份恢复 |
| [验收记录](ACCEPTANCE.md) | 已验证路径、具体证据和未验证项 |

## 能力与实际运行路径

独立版把专用 Android 手机上的企业微信账号用作私聊文本机器人，提供 APK、HTTP API 和对外 Webhook。Agent 能主动推送，也能读取来信后判断并回复，不依赖作者托管平台或特定模型框架。

```text
主动发送：Agent → POST /messages → SQLite 队列 → 手机 HTTPS 轮询
         → FlowBot 无障碍服务搜索、校验联系人、输入、发送 → 上传结果
消息接收：私聊通知 / 当前订阅会话的新气泡 → 手机持久化 → 主服务事件库
         → Webhook → 接收端保存去重 → Agent 判断
         → POST /events/{event_id}/reply → 手机无障碍发送 → 查询结果
```

业务操作由 FlowBot 的 Android `AccessibilityService` 执行，后台通知由 `NotificationListenerService` 接收。Google 无障碍菜单不是本执行器。ADB 仅用于安装、配置和诊断，不作为业务点击或输入路径。

后端支持配置 1–10 个设备密钥，每台手机串行执行；第一期只实测一台 OPPO Android 12、企业微信 5.0.11。服务没有网页后台或内置大模型，接收端只保存事件；Agent 的模型、上下文、长期运行和唤醒由接入方安排。仅启动接收端不会产生智能回复。

## 接入前准备

已有服务时，使用管理员提供的地址和资源，无需重新部署。要运行另一套独立服务，先完成下文服务器部署，再安装手机和接入 Agent。

| 资源 | 使用者与要求 |
| --- | --- |
| 服务 HTTPS 地址 | 手机和 Agent；新实例替换为自己的公网地址 |
| 设备 ID、独立设备密钥 | 只给对应手机；每台手机使用唯一身份 |
| 管理密钥 `admin_token` | 只给可信 Agent / 管理员，可操作全部配置设备 |
| 接收端密钥 | 读取通用接收端的 Agent；与管理、设备密钥分开 |
| `server.pem` 公钥证书 | IP 自签名实例的手机与客户端用于 TLS 验证，不关闭证书校验 |
| 企业微信账号与联系人 | 操作员完成登录、验证码和实名；联系人可搜索，显示名精确且唯一 |
| 专用 Android 手机 | Android 11+，保持解锁、亮屏、充电并允许后台运行 |
| Agent 运行环境 | 能访问 HTTPS；使用随包客户端需 Python 3.10+，无需第三方生产依赖 |

管理客户端可只持有 `{"admin_token":"管理员私下提供的真实密钥"}` 这样的私有 JSON 文件；不必把服务器全部设备密钥交给 Agent。接收端密钥单独保存为文本文件。真实密钥不放入 Git、命令参数、聊天或日志。

## 手机安装与运行

1. 登录企业微信，确认能搜索到目标联系人。当前界面选择器针对企业微信 5.0.11 校准，更换系统或企业微信版本后先重新验收。
2. 下载 APK，按系统提示允许对应下载工具安装应用，安装并打开 **FlowBot 独立版**。已有同签名版本可覆盖安装，保留配置与账本；不要先卸载或清空数据。
3. 点“开启无障碍服务”，在系统设置中开启 **FlowBot 独立版**。不同手机菜单位置不同，常见路径为“设置 → 无障碍 → 已下载的应用”；回到 FlowBot 确认显示“已开启”。
4. 点“开启消息通知读取”，允许 **FlowBot 企业微信消息接收**。企业微信自身也须允许通知并显示正文。无障碍与通知读取是两项独立权限，都要开启。
5. 填入 HTTPS 地址、分配的设备 ID、设备密钥和完整 `server.pem` 文本，包含 `BEGIN / END CERTIFICATE` 两行；点“保存并启动”。
6. 检查两项权限均已开启，状态为“在线，等待任务”。Agent 查询 `/devices`，确认连接时间新鲜，`ready/accessibility/notification/unlocked` 都为 `true`。
7. 保持手机解锁、亮屏、充电，允许 FlowBot 与企业微信后台运行，按机型取消两者省电限制。应用不会绕过锁屏或静默修改系统权限。

改配置先点“停止执行”，改完再“保存并启动”。不要通过强制停止重载，部分机型会关闭无障碍开关。手机重启后先解锁并打开 FlowBot，检查权限，再启动；当前没有开机广播自动启动。

## Agent 收发：最小操作闭环

以下示例在仓库或交付包的 `independent/` 目录中，用同一个 Bash 会话执行。先将占位地址、路径、设备 ID 和联系人替换为管理员提供的实际值；`/private/` 表示你自己的私有目录。JSON 文件中的设备 ID 也要相应替换。

```bash
cd independent
FLOWBOT_URL='https://<服务器公网IPv4>'
FLOWBOT_CA='/private/server.pem'
FLOWBOT_ADMIN_CONFIG='/private/config.json'
FLOWBOT_INBOX_URL='https://<接收端公网IPv4>:8443'
FLOWBOT_INBOX_TOKEN_FILE='/private/webhook.token'
```

下文接收端示例默认与主服务共用证书；独立部署接收端且使用另一张自签名证书时，将接收端命令的 `--ca` 替换为它自己的公钥证书路径。

### 检查服务与设备

```bash
curl --cacert "$FLOWBOT_CA" "$FLOWBOT_URL/health"
python3 client.py --config "$FLOWBOT_ADMIN_CONFIG" \
  --url "$FLOWBOT_URL" --ca "$FLOWBOT_CA" /devices
```

`/health` 只代表服务进程可用，不代表手机在线。设备返回 `last_seen` 为 Unix 秒，`state` 是 JSON 字符串，需要再次解析；连接时间和四项状态都应正常后再发送。

### 订阅联系人

先读取 `/subscriptions`，再按需替换指定设备订阅。保存 `subscription.json`：

```json
{"device_id":"phone1","contacts":["心向明月"],"listen_all":false}
```

```bash
python3 client.py --config "$FLOWBOT_ADMIN_CONFIG" \
  --url "$FLOWBOT_URL" --ca "$FLOWBOT_CA" /subscriptions
python3 client.py --config "$FLOWBOT_ADMIN_CONFIG" \
  --url "$FLOWBOT_URL" --ca "$FLOWBOT_CA" \
  --method POST --body-file subscription.json /subscriptions
```

POST 会替换该设备的原订阅，保留仍需监听的联系人。`contacts` 最多 100 个精确显示名，空列表且 `listen_all=false` 停止接收。`listen_all=true` 扩展通知接收，前台界面仍只覆盖 `contacts` 中明确配置的私聊对象。订阅不依赖先发消息或建立规则。

切换到 Agent 模式时，先 GET `/rules`，再 DELETE `/rules`（正文 `device_id/contact`）移除对应固定关键词规则，避免两路同时回复。

### 配置对外 Webhook

每个独立实例支持一个全局 Webhook，携带所有订阅设备事件。已有接收端时不必重配。替换地址会改变整个实例的交付目标，应由管理员确定。

将下列示意内容保存为私有 `/private/webhook.json`，替换地址与占位密钥；密钥须为 32–200 字符随机 ASCII 文本。自签名接收端额外填 `ca_pem`，值为它的完整公钥证书。

```json
{"url":"https://agent.example.com/webhook","token":"REPLACE_WITH_YOUR_RANDOM_ASCII_TOKEN","enabled":true}
```

```bash
python3 client.py --config "$FLOWBOT_ADMIN_CONFIG" \
  --url "$FLOWBOT_URL" --ca "$FLOWBOT_CA" \
  --method POST --body-file /private/webhook.json /webhook
```

接收端校验 `Authorization: Bearer`，按 `event_id` 保存并去重，提交成功后才返回 2xx。任意 2xx 都视为交付成功。收到的原始事件如下，字段值为示意：

```json
{"type":"message.received","event_id":"实际事件ID","device_id":"phone1","contact":"心向明月","text":"今天是哪一天？","source":"wecom_notification","received_at":1791626400.0}
```

`contact` 是显示名而非官方用户 ID。`source` 为 `wecom_notification` 或 `wecom_accessibility`。`received_at` 是后端接收时间，而非企业微信官方发送时间。

### 读取、判断、回复

使用仓库的通用接收端时，Agent 用接收端密钥增量读取：

```bash
python3 client.py --token-file "$FLOWBOT_INBOX_TOKEN_FILE" \
  --url "$FLOWBOT_INBOX_URL" --ca "$FLOWBOT_CA" '/events?after=0'
```

返回 `{"events":[...],"next_cursor":1}`，每条事件附整数 `cursor`。第一次先检查返回的事件，再决定处理哪些；后续使用保存的 cursor。Agent 持久化 `event_id`、处理决定和回复任务 ID，成功创建或找到原任务并保存记录后才推进 cursor。重启复用记录，重复读取本身不触发回复。

Agent 理解真实正文与上下文后，把决定的回复保存为 `reply.json`，例如：

```json
{"text":"今天是2026年10月10日，星期六。"}
```

```bash
FLOWBOT_EVENT_ID='替换为实际event_id'
python3 client.py --config "$FLOWBOT_ADMIN_CONFIG" \
  --url "$FLOWBOT_URL" --ca "$FLOWBOT_CA" \
  --method POST --body-file reply.json "/events/$FLOWBOT_EVENT_ID/reply"
```

服务从原事件确定设备和收件人。默认 `request_id=agent:<event_id>`；相同事件、相同正文重试返回原任务，同一标识改变正文返回 400。第二条独立回复需要显式提供新的稳定 `request_id` 并记录这个决定。

201 表示创建或找到任务，不表示发送完成。取响应的 `id` 继续查询：

```bash
FLOWBOT_TASK_ID='替换为响应的任务id'
python3 client.py --config "$FLOWBOT_ADMIN_CONFIG" \
  --url "$FLOWBOT_URL" --ca "$FLOWBOT_CA" "/tasks/$FLOWBOT_TASK_ID"
```

接收端不可用时，也可使用管理密钥读取主服务 `/events?after=0&device_id=phone1&limit=100`。主服务字段为 `id/received`，Webhook/接收端为 `event_id/received_at`；两个队列的 cursor 独立，不能混用。主服务无参数 GET `/events` 是最近 100 条数组，带查询参数才是增量页面。

### 主动发送

保存 `message.json`，设备 ID 和联系人替换为实际值：

```json
{"device_id":"phone1","contact":"心向明月","text":"你好","request_id":"manual-hello-001"}
```

下面命令会真实创建发送任务，仅在需要发送时执行；随后查询返回任务的终态。

```bash
python3 client.py --config "$FLOWBOT_ADMIN_CONFIG" \
  --url "$FLOWBOT_URL" --ca "$FLOWBOT_CA" \
  --method POST --body-file message.json /messages
```

同一 `request_id` 和相同内容返回原任务，不再次发送；更改内容返回 400。业务上独立的新消息使用不同的稳定标识，网络超时重试复用原标识，不靠随机新 ID 重发。

## 任务、交付状态与接口限制

| 任务状态 | 含义与处理 |
| --- | --- |
| `queued` | 等待手机领取，检查设备连接，不重复创建 |
| `running` | 手机已领取并执行，继续查询原任务 |
| `succeeded` | 手机确认输入框清空且出现新消息气泡；不表示对方已读或已送达 |
| `failed` | 发送动作前失败，查 `detail` 处理实际原因 |
| `unknown` | 动作可能已执行或结果超时，先人工核对聊天，不能盲目重发 |

领取后超过 120 秒未回报，在设备下一次轮询时转为 `unknown`，不重新排队；晚到的真实结果可补齐。后台不会自动重试发送，目前没有任务取消接口。手机持久化账本与待上传事件；清除应用数据会丢失这些记录。

Webhook 为至少一次交付；非 2xx、超时或 TLS 错误持久化重试，间隔 2、4、8 秒递增至最多 300 秒，单次超时 5 秒，不跟随 HTTP 重定向。服务重启继续未完成交付。初次配置不自动重放历史事件；关闭后暂停未完成项且不为新事件建交付项，再开启继续原项。

GET `/webhook/deliveries` 查看最近 100 条记录：`pending/sending/retry/delivered`、尝试次数、下次时间和错误类型。交付可能乱序，接收端 cursor 是落库顺序，整理上下文可结合 `received_at`。失败交付可以重试，未知发送不能盲目重发。

| 限制或错误 | 契约与处理 |
| --- | --- |
| 认证 | 主服务除 `/health` 均要求 Bearer；管理、设备、接收端密钥不能互用 |
| 请求大小 | JSON 最大 16 KiB；发送正文 1–2000 字符，接收正文 1–4000 字符 |
| 标识与订阅 | `device_id` 1–64、`contact` 和 `request_id` 1–100 字符；每设备订阅最多 100 个显示名 |
| 主服务事件分页 | `after` 非负，`limit` 1–100；任务与交付列表为最近 100 条 |
| 设备规模 | 配置 1–10 个设备；没有已验收的 10 台吞吐或固定速率 SLA |
| 400 | 字段、范围或幂等内容冲突，修正原请求 |
| 401 | 缺失、错误或混用了密钥，检查私有配置 |
| 404 | 路径、任务或事件不存在，核对 URL 与 ID |
| 500 | 服务内部错误，管理员查日志；错误 JSON 为 `{"error":"说明"}` |

全部管理接口、设备协议和响应字段见 [OpenAPI](openapi.json)；管理接口速查见 [工程说明](README.md#管理接口)。

## 部署、升级、备份与恢复

由拥有目标环境操作权限的管理员执行。部署脚本安装或替换程序并启动/重启服务；已有实例正常使用无需重复部署。

1. 准备专用 Ubuntu 24.04 / Debian、Python 3.10+、OpenSSL、systemd。初期可从 2 核 / 2 GiB / 20 GiB 起步，实际容量按设备和消息频率验收。
2. 主 API 放通 TCP 443，SSH 22 限制到管理员来源；外部 Agent 需要读取同机接收端时才放通 8443。
3. 将 `server.py`、`deploy.sh` 复制到服务器同一目录，在该目录运行 `sudo bash deploy.sh <公网IPv4> phone1`。首次生成独立配置、证书与服务；检查 `systemctl status flowbot`、`journalctl -u flowbot -n 30`。
4. 如需通用接收端，保持 `deploy-receiver.sh` 和 `examples/webhook_receiver.py` 的相对目录，再执行 `sudo bash deploy-receiver.sh <公网IPv4>`；默认 HTTPS 8443，独立 token 与数据库，之后配置主服务 `/webhook`。
5. 将公钥证书、设备身份和地址给手机，管理密钥与接收端密钥给可信 Agent。按“设备可用 → 主动发送 → 来信 → 事件 → Agent 回复 → 终态 → 对方确认”验收。

| 保留项 | 默认路径与要求 |
| --- | --- |
| 主程序 | `/opt/flowbot/server.py` |
| 服务器配置 | `/etc/flowbot/config.json`；新增唯一设备身份后重启服务，总数不超过 10 |
| TLS 证书/私钥 | `/etc/flowbot/server.pem`、`server.key`；只分发公钥证书 |
| 主数据库 | `/var/lib/flowbot/flowbot.sqlite3`，含任务、消息、订阅、规则与交付 |
| 接收端密钥/数据库 | `/etc/flowbot/webhook-example.token`、`/var/lib/flowbot/agent-inbox.sqlite3` |
| systemd 服务 | `flowbot.service` 与可选 `flowbot-webhook-example.service`，服务器开机启动与失败重启 |

后端升级重新复制程序并运行标准部署脚本，保留配置、证书与数据库。维护会短暂断连，恢复后查原任务、事件和交付；不要删除数据或重新生成身份来重试。

APK 升级保留同一 `applicationId`、同一签名私钥，递增 `versionCode` 后覆盖安装（可用 `adb install -r`）；升级后检查权限并“保存并启动”。0.2.0 沿用测试机原签名证书以保留数据，证书名称仍是 Android Debug，但 APK 本身不可调试。签名私钥在操作员私有目录，须独立备份；换签名不能覆盖已有安装。

离线备份先停止主服务和已安装接收端，备份 `/etc/flowbot`、整个 `/var/lib/flowbot` 和当前程序，再恢复。在线 SQLite 备份使用 `sqlite3.Connection.backup`，不要只复制正在写入的 `.sqlite3` 文件。回退仅替换与数据库兼容的程序，不清空数据；恢复后检查健康、鉴权、设备、原任务、交付和接收队列。停止服务暂停工作，不取消队列。

IP 自签名证书有效期 365 天，不自动续期。用 `openssl x509 -in /etc/flowbot/server.pem -noout -dates` 查看，到期前更新服务证书并同步手机与客户端信任；另一套实例不能直接使用交付测试实例的证书。长期可另行安排域名和可信证书。

构建、签名环境与详细部署步骤见 [工程说明](README.md)；本地接收示例见 [Agent 指南](AGENT.md#通用接收端)。

## 常见问题

| 现象 | 从哪里查 |
| --- | --- |
| 健康正常，任务一直排队 | `/devices` 的连接时间、权限、解锁和运行状态；继续查原任务 |
| 强制停止后不能执行 | 重新检查无障碍与通知权限；配置重载改用应用内“停止执行” |
| 发送失败 | 查任务 `detail`，核对精确唯一联系人、草稿、锁屏及界面版本 |
| 结果未知 | 人工核对目标聊天，不盲目换 ID 重发或清除数据 |
| 有来信但 Agent 看不到 | 先 `/events`，再 `/webhook/deliveries`；无事件查订阅/通知正文/前台基线，有事件且 retry 查接收端/TLS，delivered 查 Agent cursor |
| 保存了事件但没回复 | 确认 Agent 正在运行且调用回复接口；接收端本身不运行模型 |
| 重复读取或乱序 | 持久化处理 `event_id`，复用 `request_id`，按接收队列 cursor 推进并结合时间整理 |
| 手机重启后 | 解锁、打开 FlowBot、检查权限、启动；查看原任务及恢复上传，不生成替代发送 |

## 已验收与边界

一台 OPPO Android 12 / 企业微信 5.0.11 / APK 0.2.0，连接北京区 2 vCPU / 2 GiB Ubuntu 24.04 独立服务器，完成以下真实路径：

- 主动发送“你好 2026-10-10”和“你好”，用户确认收到。
- 前台日期提问、连续两条相同正文、后台能力提问，共四条真实事件经 Webhook 保存，由 Codex 判断并通过 API 回复；用户确认四条均收到。
- 接收端停止、主服务重启后，原三条待交付事件恢复投递，每个事件在接收端只落库一次；重复同一回复请求返回原任务。
- 同签名 release 覆盖升级保留数据；10 个后端 HTTP 行为测试、16 个 Java 断言、构建/Lint、签名与文档/契约检查通过。具体证据见 [验收记录](ACCEPTANCE.md)。

只支持企业微信私聊文本，不支持群聊、个人微信、图片、文件、历史补抓或完整聊天记录同步。通知正文隐藏或抑制时无法完整接收；前台补充依赖明确订阅对象和已校准界面。首次进入会话只建立基线，旧历史与自身发言不上传；切换、滚动历史、重启或可见列表整屏不再重合时重新建基线，不保证期间消息补齐。

没有官方消息 ID，所有通知/界面切换场景的跨来源唯一性未获保证，Agent 应保存处理记录并结合上下文。未验收 10 台真机容量、48 小时运行、手机重启、完整断网或省电杀进程。更换系统或企业微信版本后先重新校准与验收，不能从单台测试推断所有机型都可用。

独立版不包含原软件的编辑器、OCR 或全部功能。根 README 中原作者平台的下载、功能演示及 Apifox 接口属于另一套产品；本独立服务以本目录的 APK、源码与 OpenAPI 为准。
