# 贡献指南

感谢参与 FXXXXC。为保证每次提交可构建、可回归，请遵守以下约定。

## 开发环境

- Python 3.13+；Flutter 3.47+（仅当改动 `gui/`）。
- 安装依赖：

```bash
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install
```

## 本地检查（提交前必须通过）

```bash
pre-commit run --all-files
python -m compileall -q api fxxxxc main.py scripts
pytest -q
# Flutter（改动 gui/ 时）
cd gui && flutter analyze && flutter test
```

## 构建与发布

- **不在本地构建**。Windows 产物由 `.github/workflows/ci.yml` 手动触发构建（Actions → Run workflow）。
- 工作流会在推送时自动运行——这是有意设计，构建需要人工触发。

## 提交规范

- 使用 Conventional Commits：`feat|fix|refactor|test|docs|ci|chore|perf|build(scope): summary`。
- 提交信息正文写清动机、行为变更（如有）与测试；引用问题 ID（如 `BUG-001`）。
- 保持"合理大提交"：一个提交是一个可构建的逻辑单元，不要把无关修改混在一起。

## 文档政策（重要）

- `docs/` 目录用于本地开发文档（架构、ADR、扫描报告、改造计划），**已加入 .gitignore，禁止提交**；
- `pre-commit` 中有 `forbid-internal-docs` 钩子兜底；
- 面向用户的文档（README、CHANGELOG、SECURITY、模块说明）随代码一起提交并保持同步。

## 行为变更

- 修复缺陷时尽量保持外部行为不变；确需改变（如"显式课程列表无匹配改为报错"）时：
  1. 在提交信息中标注 `Behavior: ...`；
  2. 在 `CHANGELOG.md` 的 Changed/Fixed 中记录；
  3. 补充回归测试锁定新行为。

## 测试

- 解析器测试使用 `tests/fixtures/html/` 的静态 HTML，不访问外网；
- 题库 provider 测试用 monkeypatch 拦截 HTTP；
- 引擎契约测试直接起本地线程服务器；
- 慢测试标记 `@pytest.mark.slow`，默认不跳过但请保持秒级。
