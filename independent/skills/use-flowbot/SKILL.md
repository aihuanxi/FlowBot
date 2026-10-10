---
name: use-flowbot
description: 通过 FlowBot HTTP API 和 Webhook 读取企微消息、按真实事件回复或主动发送文本。适用于用户已授权的机器人通信，不负责账号登录或平台实名。
---

# 使用 FlowBot

按 [Agent 接入指南](../../AGENT.md) 调用仓库的 [client.py](../../client.py)。需要精确字段时查 [OpenAPI](../../openapi.json)；安装、升级和恢复时查 [README](../../README.md)。不要求特定 Agent 框架。

操作前确定服务 URL、私有管理配置、设备 ID、联系人和通信授权。IP 测试服务还需要公钥 CA 文件；接收示例需要独立 token 文件。密钥通过文件读取，不进入命令参数、聊天或日志。手机使用设备密钥，Agent 使用管理密钥。

接入时通过 `/subscriptions` 配置明确私聊联系人，通过 `/webhook` 配置已认证且持久化去重的接收地址。订阅不依赖发送历史。`listen_all` 只扩展通知接收，前台接收仍需填入 `contacts`。切换 Agent 模式时检查并移除对应的旧固定回复规则。

读取接收端 `/events?after=<cursor>`，用 `event_id` 关联上下文。先根据真实正文决定应对，再调用 `/events/<event_id>/reply`，由服务确定回复对象。默认一个事件一个幂等回复标识；重试相同正文重用它，第二条回复须明确使用另一个稳定 `request_id`。处理记录持久化后推进 cursor。后端增量 `/events` 是备用路径，字段为 `id/received`，cursor 与接收端独立。

主动发送使用 `/messages` 和稳定 `request_id`。查询 `/tasks/<id>` 确认执行结果，201 仅表示任务已创建。`unknown` 不自动重发，应人工核对；`succeeded` 仅表示界面发送确认。Webhook 故障查 `/webhook/deliveries` 的 HTTP 状态、重试时间及错误类型。

专用手机须已登录、已解锁亮屏、允许后台运行，两项 FlowBot 权限已开启。业务动作由 APK 的 AccessibilityService 完成；ADB 只用于安装、配置或诊断。不要强制停止、清除数据或卸载来重试消息。会话首次快照不回放历史；企业微信升级后重新校准 UI。
