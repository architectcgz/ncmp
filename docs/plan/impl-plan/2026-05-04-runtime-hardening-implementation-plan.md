# NCMP Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `ncmp` 当前 review 中暴露出的启动异常、配置耦合、HTTP 容错和限流重试问题，并补上最小可自动执行测试。

**Architecture:** 保持现有脚本式入口不做大重构，只把“配置解析”“HTTP 调用保护”“重试边界”“入口异常处理”从隐式行为改成显式约束。`score` 与 `refresh_cookie` 继续复用同一套基础设施，但分别声明各自必需配置，避免刷新流程再依赖旧 Cookie。

**Tech Stack:** Python 3.12, requests, unittest/mock, GitHub Actions

---

## Classification

- 任务类型：bugfix + hardening
- 复杂度：non-trivial
- 原因：跨多个模块改动，涉及配置边界、外部 HTTP 调用、重试策略、入口错误处理和测试组织

## Objective

- 修复入口脚本在配置失败时覆盖原始异常的问题
- 让 Cookie 刷新流程能在没有旧 Cookie 的场景下独立启动
- 为所有关键外部 HTTP 调用增加统一超时和基本响应校验
- 把评分限流处理改成有限次重试，避免递归卡死
- 补一层可自动执行的最小测试，覆盖本次修复的关键行为

## Non-goals

- 不改成 CLI 应用或全面重构为服务化架构
- 不引入新的第三方配置库或重试库
- 不对网易云 API 交互协议做功能扩展
- 不在这次任务里重写现有手工测试脚本的全部用途

## Inputs

- `docs/reviews/general/2026-05-04-project-review-ncmp.md`（主工作区 review 结论，作为实现输入）
- 当前代码结构：`main.py`、`refresh_cookie.py`、`src/core/**`、`src/utils/**`、`src/validators/**`

## Change Surface

- 入口与配置：
  - `main.py`
  - `refresh_cookie.py`
  - `src/utils/config.py`
- 任务执行与网络边界：
  - `src/core/bot.py`
  - `src/core/signer.py`
  - `src/core/tasks/cookie_refresh.py`
  - `src/core/tasks/daily.py`
  - `src/core/tasks/extra.py`
  - `src/validators/cookie.py`
  - `src/utils/github.py`
- 测试与文档：
  - `tests/**`
  - `README.md`

## Ownership / Boundary Notes

- `Config` 负责解析配置源和按场景校验必需项，不再把所有脚本绑死在同一组必填字段上。
- 各调用方负责声明自己需要的配置集。
- HTTP 超时与响应校验尽量收敛到少量公共方法，避免散落在每个调用点。
- `Signer` 独占评分重试策略，其他模块不重复实现限流处理。

## Slice Plan

### Slice 1: 配置与入口异常路径收敛

**Goal**
- 让 `main.py` / `refresh_cookie.py` 的异常路径不再覆盖原始错误
- 让 Cookie 刷新在无旧 Cookie 时也能启动

**Files**
- Modify: `main.py`
- Modify: `refresh_cookie.py`
- Modify: `src/utils/config.py`
- Test: `tests/test_runtime_hardening.py`

**Validation**
- `python3 -m unittest tests.test_runtime_hardening -v`
- `python3 -m compileall .`

**Review focus**
- 配置职责是否清晰
- 入口脚本是否还存在未初始化对象访问
- 刷新流程是否仍隐式依赖 `MUSIC_U` / `CSRF`

### Slice 2: 网络请求保护与限流重试

**Goal**
- 为关键 HTTP 调用补超时、状态校验和 JSON 解析保护
- 将 `Signer.sign()` 改成有限次循环重试

**Files**
- Modify: `src/core/bot.py`
- Modify: `src/core/signer.py`
- Modify: `src/core/tasks/daily.py`
- Modify: `src/core/tasks/extra.py`
- Modify: `src/validators/cookie.py`
- Modify: `src/utils/github.py`
- Test: `tests/test_runtime_hardening.py`

**Validation**
- `python3 -m unittest tests.test_runtime_hardening -v`
- `python3 -m compileall .`

**Review focus**
- 超时和异常消息是否足够可诊断
- 重试是否有上限且不会递归
- GitHub API 失败路径是否保留明确原因

### Slice 3: 文档与最小自动化验证对齐

**Goal**
- 让 README 和测试入口与真实行为一致
- 明确哪些脚本是手工检查，哪些是自动测试

**Files**
- Modify: `README.md`
- Modify: `tests/test_auto_score.py`（如需降级为手工 smoke script）
- Modify: `tests/test_refresh_cookie.py`（同上）
- Modify: `tests/test_pyncm_login.py`（同上）

**Validation**
- `python3 -m unittest tests.test_runtime_hardening -v`
- 文档静态检查以人工阅读为主

**Review focus**
- 文档是否准确描述配置要求
- 测试入口是否不再误导为自动回归测试

## Ordered Tasks

- [x] 建立新的自动化测试文件，先覆盖配置场景与重试上限行为
- [x] 修改 `Config`，支持按场景校验并增加刷新脚本所需配置加载路径
- [x] 调整 `main.py` / `refresh_cookie.py` 的初始化与异常处理顺序
- [x] 为关键 HTTP 交互补统一保护方法或最小公共包装
- [x] 把 `Signer.sign()` 改成有限次重试
- [x] 更新 README 与现有手工测试脚本说明
- [x] 跑最小充分验证并记录结果
- [x] 执行 review 并根据 findings 回环

## Compatibility / Rollback

- 兼容性：保留现有配置键名，不要求用户迁移配置文件结构
- 回退方式：单次回退到当前分支前一个提交即可恢复原行为
- 风险点：超时设置过短可能放大网络波动；需要使用保守默认值

## Plan Review

- 边界明确性：已明确 `Config` 只负责“读取 + 场景校验”，入口脚本声明必需配置，`Signer` 独占重试逻辑。
- 复用点：HTTP 保护逻辑收敛在少量辅助方法，避免每个调用点自行拼装。
- 结构收敛：这次既修行为也收敛配置边界，不留“先能跑、再补结构”的第二轮必做重构。
- 任务可执行性：每个 slice 都有明确改动面与对应验证命令，可直接按顺序落地。
