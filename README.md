# AI PRD Analyzer — MVP

> 📄 方案文档与复盘文档见 [`docs/`](./docs/) 目录

> **AI Native 组织工作流改造** | 场景：研发团队 PRD → 研发任务智能拆解

一个命令行工具，将产品需求文档（PRD）输入，自动输出：
- 结构化需求列表（功能 / 非功能 / 约束）
- 歧义检测报告（含澄清问题，供 PM 答复）
- 带验收标准、工时估算、风险等级的开发任务清单（JSON，可导入 Jira/Linear）

---

## 问题背景

在大多数研发团队，PRD到任务拆解是一个高度人工、质量不稳定的环节：

| 痛点 | 影响 |
|------|---------|
| PRD 充斥自然语言歧义 | 研发理解偏差，需求返工 |
| 每份 PRD 需花 2-4 小时拆解 | 高价值人力浪费 |
| 歧义在开发中期才暴露 | 返工成本是需求阶段的 10x |

本工具让 AI 完成 80% 的机械工作，人只需审查和决策。

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

在[阿里云百炼控制台](https://bailian.console.aliyun.com/)获取 API Key（格式：`sk-...`）。

```bash
# macOS / Linux
export DASHSCOPE_API_KEY=sk-...

# Windows PowerShell
$env:DASHSCOPE_API_KEY = "sk-..."
```

### 3. 运行分析

```bash
# 基本用法
python main.py --prd tests/fixtures/complex_prd.md

# 保存到指定文件
python main.py --prd my_prd.md --output tasks.json

# 显示详细任务内容
python main.py --prd my_prd.md --verbose

# 同时输出 Jira 格式
python main.py --prd my_prd.md --jira --output tasks_with_jira.json
```

### 示例输出（终端）

```
╭─────────────────────────────────────────╮
│ AI PRD Analyzer                         │
│ File: complex_prd.md  (2,341 chars)     │
╰─────────────────────────────────────────╯

✓ Analysis complete: E-Commerce Shopping Cart & Checkout
  Requirements : 12 (functional: 9, non-functional: 3)
  Ambiguities  : 5
  Tasks        : 8
  Total effort : 3-4 weeks

⚠ Ambiguities — clarify with PM before sprint start:

  [AMB-001] Checkout Flow — Guest Checkout
    Issue    : Guest checkout is marked "to be decided" with no resolution
    Question : Should guest checkout be supported in this phase? If yes, what data must be collected?

  [AMB-002] Payment Methods
    Issue    : Only credit card is confirmed; PayPal/Apple Pay status unclear
    Question : Which payment methods beyond credit card should be supported at launch?

  ...

┌─────────────────────────────────────────────────────────────┐
│                 Generated Development Tasks                  │
├──────────┬─────────────────────────────────┬────────┬───────┤
│ ID       │ Title                           │ Effort │ Risk  │
├──────────┼─────────────────────────────────┼────────┼───────┤
│ TASK-001 │ Implement cart data model       │ 1 day  │ low   │
│ TASK-002 │ Add/remove/update cart items    │ 2 days │ low   │
│ TASK-003 │ Integrate Stripe payments       │ 3-5 d  │ high  │
│ ...      │ ...                             │ ...    │ ...   │
└──────────┴─────────────────────────────────┴────────┴───────┘

Output saved → output.json
```

---

## 运行测试

```bash
# 所有单元测试（不需要 API Key，使用 mock）
pytest tests/ -v -m "not integration"

# 集成测试（需要真实 API Key）
pytest tests/ -v -m integration

# 查看测试覆盖率
pytest tests/ -v -m "not integration" --tb=short
```

---

## 输出格式说明

`output.json` 包含以下结构：

```json
{
  "prd_title": "E-Commerce Shopping Cart",
  "requirements": [
    {
      "id": "REQ-001",
      "type": "functional",
      "description": "Users can add products to cart",
      "priority": "high",
      "source_section": "Shopping Cart"
    }
  ],
  "ambiguities": [
    {
      "id": "AMB-001",
      "location": "Checkout Flow",
      "issue": "Guest checkout not specified",
      "clarifying_question": "Should guest checkout be supported?"
    }
  ],
  "tasks": [
    {
      "id": "TASK-001",
      "title": "Implement cart data model and persistence",
      "description": "Design and implement the cart schema...",
      "acceptance_criteria": [
        "Cart persists across sessions via database",
        "Cart correctly handles concurrent modifications"
      ],
      "effort_estimate": "1-2 days",
      "risk_level": "low",
      "dependencies": [],
      "related_requirements": ["REQ-001", "REQ-002"]
    }
  ],
  "summary": {
    "total_requirements": 12,
    "functional_count": 9,
    "non_functional_count": 3,
    "ambiguity_count": 5,
    "total_tasks": 8,
    "estimated_total_effort": "3-4 weeks"
  }
}
```

---

## 效果指标

| 指标 | 目标 | 测量方式 |
|------|------|---------|
| 需求覆盖率 | ≥ 80% | AI提取需求数 / 人工标注需求数 |
| 歧义检测率 | ≥ 70% | AI检测歧义数 / 预置歧义数 |
| 任务完整度 | 100% | 每个任务含 title + criteria + estimate |
| 处理时间 | < 60s | 端到端 PRD 分析耗时 |

---

## 技术架构

```
main.py (CLI / typer + rich)
    └─ src/analyzer.py
           ├─ Phase 1: extract_requirements (Claude tool use)
           │     └─ 返回: requirements[] + ambiguities[]
           └─ Phase 2: generate_tasks (Claude tool use)
                 └─ 返回: tasks[] + effort estimate
    └─ src/task_generator.py
           ├─ to_json() — Pydantic → JSON
           ├─ to_jira_format() — Jira 兼容格式
           └─ get_dependency_order() — 拓扑排序
    └─ src/models.py — Pydantic 数据模型
```

**关键设计决策：**
- **Tool use**：强制返回 JSON schema 合规的结构，避免解析自然语言
- **两阶段分析**：需求提取与任务生成分开，让每个阶段的 prompt 更专注
- **Prompt caching**：系统提示使用 `cache_control: ephemeral`，批量处理多份 PRD 时降低 token 成本
- **Pydantic 验证**：输出在进入业务逻辑前即被类型校验，快速失败

---

## 扩展路径

- **Stage 2**：对接 Jira / Linear API，一键创建 issue
- **Stage 3**：历史 PRD 向量化存储，自动引用类似项目的经验教训
- **Stage 4**：PM 在提交 PRD 前的实时歧义警告（IDE 插件 / Slack Bot）


