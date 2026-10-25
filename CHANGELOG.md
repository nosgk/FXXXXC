# Changelog

所有对外可感知的变化记录在此文件。格式参考 Keep a Changelog。

## [3.2.3] - 2026-10-25

引擎卡顿根治、答题能力对齐 ocsjs、仪表盘结构化重构。

### Fixed

- **刷课进度卡 100% 不进入下一个任务**：视频进度走到片尾后，平台偶发不确认 `isPassed`，旧实现会每 1~2 秒无限重发上报形成死循环。现在终态确认有界重试（默认 6 次，约 15 秒），仍不通过则明确记日志、返回失败并把队列让给后续任务点。
- **多空填空题答案拼接错误**：填空题多空时原实现把各空直接连成一串（"答1答2"），现按超星题库约定以 `#` 分隔提交；单空行为不变。
- 判断题答案清洗：剥离"【答案】/正确答案："等题库常见前缀与首尾标点后再映射，新增 ✔/✓/☑/✗/✘/☒ 等符号与 right/wrong 变体。

### Added

- **答题容错对齐 ocsjs（AnswerUtil）**：新增 `match_option_letter` 五级匹配——原文全等 → 归一化全等（去标点/空白/全半角）→ 仅保留中英日韩数字全等 → 子序列 → 相似度兜底；单选/多选答案匹配统一走该管线。
- **题库命中统计**：多题库回退（TikuFallback）按 provider 记录查询数/命中数，经 `study.status`（`tiku_stats`）与 `tiku_test` 透出，仪表盘可展示命中率。
- **结构化运行事件（`study.task`）**：章节开始/完成/重试、任务开始/完成/异常、视频逐秒进度（1 秒节流）、章节检测覆盖率与成绩，全部带课程/章节上下文；`study.status` 新增 `current`（实时任务快照）、`elapsed`（运行时长）、`tiku_stats`、`last_course_ids`，GUI 断线重连轮询即可恢复全貌。
- **选中课程引擎侧持久化**（`[engine] last_course_ids`）：GUI 重启后从引擎恢复上次选课，与本地持久化构成双向同步；不写 `common.course_list`，CLI 交互语义不变。
- **仪表盘结构化重构**：英雄运行卡（状态标识 + 当前任务 + 动画进度条 + 本地秒表）、六张核心指标卡（章节进度/失败/课程/题库命中率/覆盖率/最近成绩，响应式 2~6 列）、实时活动流（倒序、定长行虚拟列表、视频行内嵌紧凑进度条）、失败/错误告警条、加载骨架屏与空态引导四步；原始日志仍保留在「日志」页。

### Changed

- 事件性能：视频进度事件引擎侧 1 秒节流；GUI 活动流 150ms 批量合并刷入（视频 progress 只更新当前任务快照不入流），容量上限 80 条。
- 课程列表刷新改为 stale-while-revalidate：刷新期间保留旧数据，不再闪骨架屏；错误时已有数据保持展示。
- `study.start` 服务端校验 `notopen_action` 取值（retry/ask/continue），非法值拒绝。

## [3.2.2] - 2026-10-24

设置页保存修复、阿里健康体接入与三阶段体验/性能专项。

### Fixed

- **退出后进程残留**：GUI 关闭时从未停止 Python 引擎（Windows 上子进程不随父进程退出）。现在关闭按钮会先杀引擎进程树（taskkill /T /F，覆盖 shell/python 兜底链）再销毁窗口；引擎侧新增三层看门狗兜底——`--parent-pid` 同步句柄精确等待父进程死亡、stdin 管道 EOF（GUI 崩溃/被杀时管道即断）、pid 轮询兜底——任一触发即自退并清理 `engine-runtime.json`，杜绝 pid 复用竞态。
- **设置页保存不了配置/开关点不上**：根因是 build 期间的配置同步会把用户未保存的编辑整表覆写（开关点完立刻弹回）。改为脏跟踪——只有"引擎配置真的变化"才同步远端值，且永不覆盖未保存字段；保存改走统一的 `configProvider.save` 路径并在成功后回读校验。
- **设置页保存/测试按钮点不到**：按钮原在超长列表最底部，小窗口不进视口。改为底部固定操作栏，常驻可见并带未保存计数。
- **列表"首批正常、后续卡顿"**：日志事件由逐行重建改为 150ms 批量合并刷入；日志页改定长行虚拟列表并移除每行 SelectableText（整页 SelectionArea）；课程页选中状态按行隔离重建；页签懒构建 + Offstage 保活（未访问页面不参与首帧）。

### Added

- 全局字体替换为 **阿里巴巴健康体 2.0 CN 85B**（内置打包，离线可用）。
- 引擎配置 schema 校验（fail-closed）：数值范围/枚举/布尔/题库 provider 白名单，非法整单拒绝并返回字段级错误；合法值自动归一化落盘（如 jobs 99→16、speed 3→2），新增 `config.validate`；GUI 表单带范围提示与前端预校验。
- 课程选择持久化（shared_preferences），刷新后自动修剪失效 ID——GUI 与引擎状态双向同步。
- 骨架屏加载占位、响应式统计卡片网格（2~4 列自适应）、页签 180ms 淡入转场、更友好的空/错状态。

### Changed

- 课程刷新防抖（进行中的刷新直接忽略）；仪表盘开始/暂停/停止按钮带忙态防连点。

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
