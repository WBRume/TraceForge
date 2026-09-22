# DSH 故障诊断执行前 guard

这个 Cordis 插件只用于诊断 Run 的专属 DSH Host。它会拒绝未绑定会话的所有工具，也会拒绝绑定会话的 shell、文件写入、委派和 PTC 执行。允许的四个工具经平台 MCP 入口执行，凭据只授权当前 Run 的候选提交或源码读取，不授权证据写入。

DSH 需要具有 `ctx.tools.guard` 的版本。该接口在 `tools/pre-execute` 之后、工具函数执行之前作单调拒绝；普通工具事件订阅不能替代它。插件不声称提供操作系统沙箱。

部署时将本目录作为 Cordis 插件加载，配置 `platformOrigin` 为后端 Origin、`port` 为专属本机控制端口。Host 和后端进程都应通过 `TRACEFORGE_PLAYBOOK_GUARD_TOKEN` 注入同一个至少 32 字符的随机凭据；不要将凭据写到规程 YAML。控制端口固定监听 `127.0.0.1`。

受信任的环境 probe 返回：

```json
{
  "dedicated_backend_host": true,
  "backend_url": "http://127.0.0.1:4098",
  "guard_control": {
    "url": "http://127.0.0.1:4198",
    "token_env": "TRACEFORGE_PLAYBOOK_GUARD_TOKEN"
  }
}
```

这些是 probe 输出中的部分字段；Run 还要求独立的环境、源码、策略 digest，以及隔离、证据存储和工作目录绑定。未经验证的部署只能报告 `ADVISORY_GUARD`，且规程与用户必须都明确允许该模式。

本地契约测试：`node --test integrations/dsh-playbook/guard.test.mjs`。真实 DSH Host 的端到端执行尚需单独验证。`tools.json` 对应平台 `tool_server.TOOLS`，契约测试会检查它们保持一致。
