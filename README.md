# :computer: FXXXXC —— 超星学习通自动化完成任务点（CLI + Windows 桌面端）

<p align="center">
    <a href="https://github.com/nosgk/FXXXXC" target="_blank">
        <img src="https://img.shields.io/github/stars/nosgk/FXXXXC" alt="Github Stars" />
    </a>
    <a href="https://github.com/nosgk/FXXXXC" target="_blank">
        <img src="https://img.shields.io/github/languages/code-size/nosgk/FXXXXC" alt="Code size" />
    </a>
    <img src="https://img.shields.io/badge/python-3.13+-blue" alt="python" />
    <img src="https://img.shields.io/badge/license-GPL--3.0-green" alt="license" />
</p>

本项目的最终目的是通过开源消灭所谓的付费刷课平台。希望有能力的朋友提交代码，支持项目良性发展。

> **FXXXXC** 在 Samueli924/chaoxing 的 CLI 能力之上做了工程化改造：
> - 修复了会话、任务队列、题库缓存等一批影响稳定性的问题；
> - 拆分核心模块为可测试的 `fxxxxc/` 包（旧的 `api/` 导入路径保持兼容）；
> - 新增 **本地 Python 引擎 + Flutter/Material You Windows 桌面客户端**；
> - 提供手动触发（不随推送自动构建）的 GitHub Actions 质量门禁与 Windows 便携包构建。

## :warning: 免责声明

- 本代码遵循 [GPL-3.0 License](./LICENSE)，允许**开源/免费使用和引用/修改/衍生代码的开源/免费使用**，不允许修改和衍生的代码作为闭源商业软件发布和销售，禁止使用本代码盈利。
- 本代码仅用于**学习讨论**，禁止用于盈利；使用者的一切行为与作者无关。

## :books: 使用方法

### 1. 源码运行（Python 3.13+）

```bash
git clone https://github.com/nosgk/FXXXXC
cd FXXXXC
pip install -r requirements.txt
```

复制 `config_template.ini` 为 `config.ini` 并填写账号/题库，然后：

```bash
python main.py                    # 读取当前目录 config.ini（无配置则交互输入）
python main.py -c config.ini      # 指定配置文件
python main.py -u 手机号 -p 密码 -l 课程ID1,课程ID2 -a retry
python main.py --data-dir D:/fxxxxc-data -c D:/fxxxxc-data/config.ini
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `-c/--config` | 配置文件路径 |
| `--data-dir` | 数据目录（config.ini / cookies.txt / cache.json / 日志），默认当前目录 |
| `-u/-p` | 手机号 / 密码 |
| `-l/--list` | 课程 ID，逗号分隔 |
| `-s/--speed` | 倍速（1.0-2.0） |
| `-j/--jobs` | 并发章节数 |
| `-a/--notopen-action` | retry / ask / continue |
| `--retry-interval` | 重试间隔（秒） |
| `-lc/--add-learning-count` | 完成后增加章节学习次数 |
| `-tc/--target-count` | 学习次数目标 |
| `-v/--verbose` | 调试日志 |

退出码：`0` 成功；`1` 配置/登录错误；`2` 参数错误；`130` 用户中断。

### 2. Windows 桌面客户端（Material You）

从 Releases（或 Actions 手动构建产物）下载 `FXXXXC-windows-x64-*.zip`，解压后运行 `FXXXXC.exe`：

- 左侧导航：仪表盘 / 课程 / 任务 / 日志 / 设置；
- 支持亮/暗主题与 Material You 强调色；
- 学习进度、实时日志、手动答题弹窗、通知与题库测试；
- 配置与日志保存在 `%APPDATA%\FXXXXC` 与 `%LOCALAPPDATA%\FXXXXC`，引擎仅监听 127.0.0.1 并使用随机端口 + Token 鉴权。

### 3. Docker 运行

```bash
docker build -t fxxxxc .
docker run -it -v /本地路径/config.ini:/config/config.ini fxxxxc
```

容器默认使用挂载到 `/config/config.ini` 的配置；未挂载时自动复制模板。

## :gear: 配置说明

完整键位见 `config_template.ini`（与代码有键位一致性测试）。常用项：

| 节 | 键 | 默认 | 说明 |
| --- | --- | --- | --- |
| `[common]` | `use_cookies` | `false` | true 时忽略账号密码 |
| `[common]` | `course_list` | 空 | 课程 ID；**显式填写但无匹配会报错退出** |
| `[common]` | `speed` / `jobs` | `1` / `4` | 倍速 / 并发章节 |
| `[common]` | `notopen_action` | `retry` | retry / ask / continue |
| `[common]` | `work_redo_enabled` / `work_max_retries` | `false` / `3` | 章节检测重做 |
| `[common]` | `add_learning_count` / `target_count` / `learning_count_interval` | `false` / `100` / `30` | 章节学习次数 |
| `[tiku]` | `provider` | `TikuYanxi` | 题库，可逗号分隔多题库回退 |
| `[tiku]` | `submit` / `cover_rate` / `delay` | `false` / `0.9` / `1.0` | 提交模式与覆盖率 |
| `[tiku]` | `endpoint` / `key` / `model` | 空 | AI（OpenAI 兼容） |
| `[tiku]` | `insecure_skip_verify` | `false` | 显式关闭 TLS 校验（不建议） |
| `[notification]` | `provider` / `url` / `tg_chat_id` | 空 | ServerChan / Qmsg / Bark / Telegram |

提交模式：不配置题库视为不答题自动跳过章节检测；`submit=false` 只保存不提交；`submit=true` 达到 `cover_rate` 后提交。

## :rocket: 构建（GitHub Actions，手动触发）

构建不在本地进行。仓库提供单一工作流 `.github/workflows/ci.yml`：

- 触发方式：仅 `workflow_dispatch`（Actions 页面手动 Run），推送不会自动触发；
- 流程：Python 质量（ruff/mypy/bandit/pip-audit/pytest+coverage）→ Windows 测试 → Flutter 质量（analyze/test）→ Windows x64 构建（PyInstaller 引擎 + Flutter GUI）→ 便携 zip + SHA256；
- 产物命名 `FXXXXC-windows-x64-<version>.zip`，可在 Run 页面下载，也可勾选创建 Release。

## :heart: 参与贡献

见 [CONTRIBUTING.md](./CONTRIBUTING.md)。提交前请运行：

```bash
pre-commit run --all-files
pytest -q
```

## :book: 文档

- `config_template.ini`：全部配置键与默认值；
- `api/README.md`：模块地图与兼容层说明；
- 架构/ADR 等内部开发文档保留在本地 `docs/`（不入库）。

## :warning: 安全提示

- `config.ini`、`cookies.txt`、`cache.json`、`chaoxing.log` 含账号/会话/题库 token，请勿提交或分享；
- 日志会脱敏 cookie/token 等字段；如需完全关闭 TLS 校验，请显式设置 `insecure_skip_verify = true` 并自担风险；
- 更多内容见 [SECURITY.md](./SECURITY.md)。
