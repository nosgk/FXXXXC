# 安全说明

## 报告漏洞

请通过 GitHub Security Advisories（Security → Report a vulnerability）私下报告，不要在公开 issue 中附具体利用细节。我们会在 7 天内回应。

## 数据与凭据

以下文件包含敏感信息，**永远不要提交或分享**：

- `config.ini`：账号、密码、题库/大模型 key、通知 webhook；
- `cookies.txt`：登录会话；
- `cache.json`：题目与答案缓存；
- `chaoxing.log`：运行日志（已尽力脱敏）。

以上文件默认写入数据目录（CLI 为当前目录，桌面端为 `%APPDATA%\FXXXXC`），仓库 `.gitignore` 已全部忽略。

## 网络与 TLS

- 第三方题库/大模型请求默认开启 TLS 证书校验；
- 如需关闭，请在 `[tiku]` 设置 `insecure_skip_verify = true`，或设置环境变量 `FXXXXC_INSECURE_SKIP_VERIFY=1`；这会使 token 暴露给中间人，请仅在可信网络使用；
- 登录接口使用超星官方前端相同的 AES 参数加密后传输。

## 日志脱敏

`api/redact.py` 会在记录前对 cookie/authorization/token/password 等键做掩码处理；日志默认级别为 TRACE 写入文件，可通过 `FXXXXC_LOG_LEVEL` 调整。

## 桌面引擎

- 引擎只绑定 `127.0.0.1`，随机端口；
- 所有 RPC 需要携带 GUI 启动时生成的 Bearer Token（仅存在于进程环境变量与内存中）；
- GUI 与引擎同机同用户运行；不要把端口/Token 暴露到外部。
