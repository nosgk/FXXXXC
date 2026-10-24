# Changelog

所有对外可感知的变化记录在此文件。格式参考 Keep a Changelog。

## [3.2.1] - 2026-10-24

合并上游 multimodal 分支、修复桌面端启动卡死、精简 CI。

### Added

- 多模态图像测验题支持（移植自 DemaciaForge/chaoxing `fix/multimodal-image-questions`）：题干/选项中的图片经安全下载后以 `image_url` 内容块发给视觉大模型；图片选择题统一让模型返回选项字母；图片判断题无法识别时留空仅保存，禁止随机乱答。
- 图片下载安全加固：仅 HTTPS、解析钉扎公网 IP（拒绝内网/组播/IPv6 过渡地址）、限 10MB、域名级 chaoxing cookies、不泄漏会话到第三方图床。
- 图像题使用独立缓存键 `vision-choices-v3:*`（含题型与选项），避免命中旧的公式正文缓存。

### Fixed

- **桌面客户端启动即"未响应"**：窗口初始化改为首帧渲染后再执行（此前 `runApp` 之前等待原生窗口回调会与首帧互等，消息泵卡死）；Python 引擎改为首帧后启动。
- 引擎子进程继承完整父进程环境（此前只传 token，Windows 上缺 `SystemRoot` 会破坏 TLS/网络初始化）。
- **本地/自定义 AI 端点连接失败**：`http://` 或回环端点（如 `http://127.0.0.1:8000/v1`，本地模型）不再走系统代理（httpx `trust_env=False`），修复被代理转发成 502 的问题。

### Changed

- CI 精简为单一手动 Windows 构建 job（移除 ruff/mypy/bandit/pip-audit/pytest/coverage/flutter-quality 门禁流程），构建时间显著下降；代码质量检查回归为本地 pre-commit + pytest 自查。

## [3.2.0] - 2026-10-24

Harness 工程化改造：GUI、引擎、门禁与核心修复。

### Added

- Windows x64 桌面客户端（Flutter/Material You）：仪表盘、课程选择、任务概览、实时日志、手动答题弹窗与设置页。
- 本地 Python 引擎（`python -m fxxxxc.engine`）：127.0.0.1 HTTP JSON-RPC + WebSocket 事件，Bearer Token 鉴权。
- 核心包 `fxxxxc/`（paths/events/cancellation/infra/tiku/orchestrator/engine），`api/` 保留兼容 re-export，`main.py` 变为薄入口。
- 手动触发的 GitHub Actions 工作流：质量检查 + Windows 构建 + 打包（推送不再自动构建）。
- pre-commit、ruff/mypy/coverage 配置、`scripts/harness_metrics.py`、配置键一致性测试。
- 新配置：`chapter_max_tries`、`learning_count_interval`、`insecure_skip_verify`；CLI 新增 `--data-dir`、`--version`。

### Changed

- **行为**：`course_list` 显式填写但无任何匹配时直接报错退出（旧版会静默学习全部课程）。
- **行为**：章节检测回滚计数改为当前章节局部（旧版一次回滚会让后续所有章节忽略覆盖率强制提交）。
- `get_job_list` 在章节已声明任务点数量满足时提前停止，减少每章最多 6 次额外请求。
- 题库缓存改为实例内快照 + 批量原子写；`query_all` 不再逐题读写整个文件。
- 第三方题库/验证码请求默认开启 TLS 校验，可通过 `insecure_skip_verify` 显式关闭。
- 日志对 cookie/token/通知 URL 等敏感字段脱敏；文件日志级别可用 `FXXXXC_LOG_LEVEL` 调整。

### Fixed

- `SessionManager` 单例每次取用都重建会话/清空 headers 导致登录态丢失。
- 任务线程内异常导致 `task_queue.join()` 永久挂起；新增可取消/可暂停的 worker 池与重试线程生命周期管理。
- `Tiku.query` 缓存未命中丢弃答案、重做反馈分支 `UnboundLocalError`。
- 章节检测错误反馈跨章节残留（缓存被跳过、旧错题反馈注入后续章节）。
- 直播任务失败被吞成成功；倍速为 0 时除零。
- `ChapterResult` 枚举值误写成元组。
- cookies 写入改为原子 + UTF-8；缓存损坏时备份并恢复。
- 字体映射初始化失败不再让整章解析崩溃；HTML 解析对缺失字段容错。
- `pip install .` 现在能正确安装 `api`/`fxxxxc`/`main`（此前 `py-modules=[]` 导致装不上代码）。

### Removed

- 未使用的 Celery/Flask 脚手架 `app.py`、`argparse` backport、`tenacity` 依赖。
- 死代码：`process_course`、`show_progress`、`formatted_output`、未使用异常类与 `--auto-sign`（解析保留但不再暗示可用）。
- 旧的 push 自动构建工作流（合并进手动 `ci.yml`）。
