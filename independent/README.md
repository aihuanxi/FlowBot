# FlowBot 独立服务 MVP

独立的 Python 后端和 Android 执行端，不连接作者托管平台。首阶段支持企业微信单设备文本发送、私聊通知回调及固定关键词自动回复；配置最多 10 个设备密钥，每台设备串行执行任务。

原仓库缺少 `autojs`、`apkbuilder`、`LocalRepo`、`paddleocr` 等构建模块及完整业务后端，因此此目录单独构建。执行端沿用原仓库 `UiObject` 的节点遍历和 Android 平台动作方式，不包含原软件的编辑器、OCR 或其全部功能。

## 主链路

```text
管理接口 POST /messages → SQLite 任务队列
    → 手机 HTTPS 轮询 → AccessibilityService 搜索/校验联系人/输入/发送
    → 手机本地保存结果 → POST /device/result
企业微信私聊通知 → NotificationListenerService → 手机持久化待上传事件
    → POST /device/incoming → SQLite 消息记录 → 关键词匹配 → 回复任务
```

ADB 仅用于安装、配置和诊断。企业微信业务操作由手机无障碍服务执行，不使用 ADB 点击、坐标输入、Root 或 Hook。通知回调指手机向本后端上传消息；当前没有向第三方地址转发的 Webhook。

## 本地构建与接口验证

要求 Python 3.10+、JDK 17+、Android SDK 36；手机要求 Android 11 及以上。后端仅用标准库；Android 仅用平台 API。APK 用于专用手机侧载，当前 `targetSdk=32`，未准备 Google Play 发布；Lint 仅排除对应的 Play 发布目标版本检查，保留 API 兼容检查。

```bash
cd independent
python3 -m unittest -v test_server.py
python3 server.py --config /private/path/config.json --init --device phone1
python3 server.py --config /private/path/config.json --db /private/path/flowbot.sqlite3
cd android
./gradlew :app:assembleDebug
adb -s <手机序列号> install -r app/build/outputs/apk/debug/app-debug.apk
```

通知正文校准测试不依赖 Android 或第三方测试库，在 `independent/android` 执行：

```bash
mkdir -p /tmp/flowbot-java-test
javac -d /tmp/flowbot-java-test app/src/main/java/dev/aihuanxi/flowbot/NotificationText.java app/src/test/java/dev/aihuanxi/flowbot/NotificationTextTest.java
java -ea -cp /tmp/flowbot-java-test dev.aihuanxi.flowbot.NotificationTextTest
```

`--init` 不覆盖已有配置。它生成独立管理密钥和设备密钥，文件权限为 `0600`；不要将配置、私钥、数据库或 APK 签名密钥提交到 Git。

## 独立服务器部署

使用专用 Ubuntu 24.04 或 Debian 服务器，准备 Python 3.10+、OpenSSL、systemd。首阶段可用 2 核、2 GiB、20 GiB 系统盘；实际容量以设备和消息频率验证为准。公网只开放 TCP 443，SSH 22 限制到管理员来源 IP。

将本目录的 `server.py`、`deploy.sh` 复制到服务器同一目录，然后在服务器运行：

```bash
sudo bash deploy.sh <服务器公网IPv4> phone1
sudo systemctl status flowbot
sudo journalctl -u flowbot -n 30
```

脚本创建 `flowbot` 用户并安装服务：

| 路径 | 用途 |
| --- | --- |
| `/opt/flowbot/server.py` | 后端程序 |
| `/etc/flowbot/config.json` | 管理密钥与 1–10 个设备密钥 |
| `/etc/flowbot/server.pem` | IP 测试用 TLS 证书，客户端须信任它 |
| `/etc/flowbot/server.key` | TLS 私钥，只留在服务器 |
| `/var/lib/flowbot/flowbot.sqlite3` | 任务、设备状态、消息及回复规则 |
| `/etc/systemd/system/flowbot.service` | 开机启动与失败后重启 |

再次运行脚本会替换程序并重启服务，保留配置、证书及数据库。它不会清空历史或重新发送已有任务。

首次创建的自签名证书包含指定公网 IP，有效期 365 天；它不会自动续期。下载 **公钥证书** `server.pem` 给管理客户端及手机；不要关闭证书校验，不要下载服务器私钥。到期前须换证书并同步手机信任，长期部署可改用域名及可信证书。

```bash
curl --cacert /private/path/server.pem https://<公网IP>/health
```

新设备：在服务器配置 `devices` 对象中增加唯一设备 ID 和独立随机密钥（如 Python `secrets.token_urlsafe(32)`），总数不超过 10，然后 `sudo systemctl restart flowbot`。管理密钥与全部设备密钥必须互不相同且至少 32 字符。每台手机只配置自己的设备密钥，管理密钥只给管理客户端。

## 手机配置

1. 企业微信已登录，目标联系人可搜索到。当前选择器针对企业微信 5.0.11 校准；升级企业微信后应重新验收。
2. 安装并打开 **FlowBot 独立版**，点“开启无障碍服务”，在系统中开启 **FlowBot 独立版**；Google 无障碍菜单不是本执行器。
3. 点“开启消息通知读取”，允许 **FlowBot 企业微信消息接收**。企业微信本身须允许通知显示消息正文。
4. 填写 `https://<公网IP>`、本机设备 ID、该设备密钥及完整 `server.pem` 内容，点击“保存并启动”。无障碍、通知接收均显示“已开启”，运行状态显示“在线，等待任务”。
5. 保持手机解锁、亮屏、充电，允许 FlowBot 和企业微信后台运行；按机型关闭这两个应用的省电限制。应用不会绕过锁屏，也不会静默修改系统权限。

本地 USB 调试可运行 `adb -s <序列号> reverse tcp:8787 tcp:8787`，手机使用 `http://127.0.0.1:8787`，证书留空。远程地址必须使用 HTTPS。

不要用强制停止应用的方式重载配置：部分手机会关闭无障碍开关。修改配置前点“停止执行”，保存并启动后检查两项权限。手机重启后先解锁并打开 FlowBot，检查权限，再点“保存并启动”；当前没有开机广播自动启动。

## 管理接口

除 `GET /health` 外都要求 `Authorization: Bearer <密钥>`。管理密钥和设备密钥不能相互调用对方接口。为避免密钥进入命令参数，管理客户端读取私有配置文件：

```bash
python3 client.py --config /private/path/config.json \
  --url https://<公网IP> --ca /private/path/server.pem /devices
```

将发送请求保存为 `message.json`：

```json
{"device_id":"phone1","contact":"心向明月","text":"你好 2026-10-10","request_id":"send-20261010-001"}
```

```bash
python3 client.py --config /private/path/config.json \
  --url https://<公网IP> --ca /private/path/server.pem \
  --method POST --body-file message.json /messages
```

返回任务 `id`。使用 `GET /tasks/<id>` 查询结果。同一 `request_id` 和正文返回原任务；同一 ID 更换正文会拒绝，不会重复发送。

| 管理接口 | 作用 |
| --- | --- |
| `POST /messages` | 创建文本任务，字段如上 |
| `GET /tasks`、`GET /tasks/<id>` | 最近 100 条任务或指定任务 |
| `GET /events` | 最近 100 条真实通知回调 |
| `GET /devices` | 设备最近连接时间、权限和解锁状态 |
| `POST /rules` | 设置某设备、联系人的唯一精确关键词规则 |
| `GET /rules` | 查看规则 |
| `DELETE /rules` | 删除规则，正文含 `device_id`、`contact` |

自动回复请求示例：

```json
{"device_id":"phone1","contact":"心向明月","trigger":"FlowBot测试","reply":"你好 2026-10-10"}
```

用上述客户端向 `/rules` 提交，之后让该联系人发送 **FlowBot测试**。保持企业微信在后台，避免当前聊天前台不产生通知。检查 `/events` 出现该真实通知、`/tasks` 出现一条回复任务，并在双方聊天中确认内容。重复通知依据事件 ID 去重；回复不能与触发词相同。

设备协议均为 POST：`/device/poll` 上传 `state` 并领取一个任务；`/device/result` 上传 `task_id/status/detail`；`/device/incoming` 上传 `event_id/contact/text/source`，其中 `source` 为 `wecom_notification`。设备身份由其密钥确定；它只能领取、回报自己的任务。消息正文最长 2000 字符，接收正文最长 4000 字符，JSON 请求最大 16 KiB。

## 结果、恢复与限制

- `queued` 等待设备；`running` 正在执行；`succeeded` 表示无障碍点击后输入框清空且出现新消息气泡，**不表示对方已读或已送达**。
- `failed` 表示未进入发送动作便失败。`unknown` 表示动作可能已执行或结果超时，必须人工核对聊天，不能直接重发。后台不会自动重试发送。
- 领取后超过 120 秒未回报的任务在设备下一次轮询时转为 `unknown`，不会重新排队。晚到的真实结果可补齐状态。
- 手机本地 SQLite 保存执行记录和待上传回调，断网后恢复上传。通知服务重新连接时读取仍存在的系统通知，依据事件 ID 去重。企业微信通知包含聚合条数时，只有显示正文与系统 ticker 的原文精确对应才提取原文，不盲目删除用户消息里的 `[N条]`。进程中断留下的执行记录标为 `unknown`，不再次执行。清除手机应用数据会丢失这些记录，不要在待验收任务期间清数据。
- 服务器重启会保留队列、消息与规则。备份或回退前停止服务，复制 `/etc/flowbot` 和整个 `/var/lib/flowbot`；回退仅替换兼容的程序，再启动服务并检查 `/health`、`/devices` 及原任务状态。
- 只处理已配置联系人的私聊通知，不读取群聊、个人微信、历史聊天、图片或文件。通知未显示正文、被系统抑制、当前聊天处于前台时可能无法接收；目前没有 UI 收消息补充路径。联系人需名称精确匹配且唯一，不会猜测相似名称。
- 手机 UI 自动化依赖实际企业微信界面。联系人重名、未发送草稿、锁屏或选择器失效会停止该任务，保留可诊断结果；升级系统或企业微信后先用测试联系人验收。

## 已完成的首阶段验收

2026-10-10，使用 Android 12 的 OPPO 真机、企业微信 5.0.11，以及北京区 2 核、2 GiB 独立服务器，完成以下验收：

- 后端下发文本任务，手机通过无障碍服务发送「你好 2026-10-10」及「你好」，用户确认均已收到。
- 联系人发来的真实「FlowBot测试」通知上传并持久化，精确关键词触发一条自动回复，用户确认看到了回复。
- 服务器重启后，原任务结果、两条真实通知记录和规则保留，未新增重复回复；手机恢复在线，本地执行数据库完整，待上传队列为空。
- 5 个后端行为测试、8 个通知解析断言、APK 构建和 Lint 通过。

后端测试覆盖真实 HTTP 鉴权、设备隔离、任务幂等、并发领取、回调去重、自动回复及数据库重启恢复。首阶段仅验收一台手机，未做 10 台真机持续运行或吞吐量测试，也未验收手机重启、断网和省电策略下的长期运行。
