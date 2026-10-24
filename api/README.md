# 模块地图

## 兼容层（保留，勿新增依赖）

- `api/base.py`：旧入口，内部实现已迁移到 `fxxxxc/`，此文件仅 re-export 与 `Chaoxing` 业务类。
- `api/answer.py`：题库 provider 集合；`CacheDAO` 已迁移到 `fxxxxc/tiku/cache.py`。
- `api/decode.py`：HTML 解析（课程/章节/任务卡/题目）。
- `api/notification.py`：通知服务。
- 其余模块：`config`（常量与路径）、`cookies`（原子读写）、`logger`（loguru + tqdm sink）、`redact`（日志脱敏）、`cipher`、`captcha`、`font_decoder` + `cxsecret_font`、`live` + `live_process`、`process`（学习次数编排）、`answer_check`、`exceptions`。

## `fxxxxc/` 新包

| 模块 | 职责 |
| --- | --- |
| `fxxxxc/paths.py` | 数据目录（CLI=cwd，桌面端=%APPDATA%/FXXXXC）与资源路径 |
| `fxxxxc/config.py` | INI 读写助手（engine 与 GUI 共用） |
| `fxxxxc/events.py` | 线程安全事件总线（引擎日志/进度/手动答题） |
| `fxxxxc/cancellation.py` | 取消/暂停原语 |
| `fxxxxc/infra/session.py` | 单次初始化的 `requests.Session` 单例（可 reset） |
| `fxxxxc/infra/rate_limit.py` | 限速器 |
| `fxxxxc/text/answers.py` | 答案归一化、选项匹配、作答记录解析 |
| `fxxxxc/tiku/cache.py` | 原子化题库缓存（批量写） |
| `fxxxxc/orchestrator/job_processor.py` | 章节队列/worker 池/任务分发/课程过滤 |
| `fxxxxc/engine/` | 桌面引擎：HTTP JSON-RPC + WebSocket 事件（`python -m fxxxxc.engine`） |
| `fxxxxc/cli.py` | `fxxxxc` 命令行入口（等价 `python main.py`） |

## 数据流

```text
CLI (main.py) ──┐
                ├─→ fxxxxc/orchestrator → api/base.Chaoxing → api/decode / api/live / ...
GUI ─ fxxxxc/engine ─┘                       └→ api/answer (题库) / api/notification
```

## 扩展点

- 新题库：在 `api/answer.py` 实现 `Tiku` 子类并注册 `PROVIDER_REGISTRY`。
- 新通知：在 `api/notification.py` 实现 `NotificationService` 子类（配置 `provider` 名与类名一致）。
- 新任务类型：`api/decode.py` 识别 + `fxxxxc/orchestrator/job_processor.py` 分发。
