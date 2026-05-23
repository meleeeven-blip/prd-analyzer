# 方案文档：AI Native PRD → 研发任务智能拆解

## 1. 问题陈述

### 1.1 当前工作流

```
PM 写 PRD (Word/Confluence)
    ↓ 
需求评审会 (1-2小时)
    ↓
Tech Lead 人工拆解任务 (2-4小时/PRD)
    ↓
录入 Jira/Linear (30-60分钟)
    ↓
开发开始 → 发现歧义 → 再次沟通
```

**总耗时**：一份中等复杂度 PRD 从接收到任务录入 Jira，通常需要 4-8 小时人力投入，且质量依赖 Tech Lead 个人经验。

### 1.2 核心痛点

| 痛点 | 量化影响 |
|------|---------|
| PRD 歧义导致需求变更 | 30-40% 的项目延期源于需求不清 |
| 需求中期变更成本 | 开发中修复成本是需求阶段的10-100x |
| Tech Lead 时间分配 | 20-30% 时间用于非创造性的文档转化 |

### 1.3 根本原因

PRD 是**非结构化自然语言**，而 Jira 任务需要**结构化可执行定义**。当前完全依赖人的经验完成这一转化，存在：标准不统一，歧义检测依赖经验，以及处理流程复杂的问题。
---

## 2. AI Native 改造方案

### 2.1 设计原则

- **AI 完成**：结构化解析、歧义检测、任务草稿生成、工时初估
- **人负责**：确认/修改歧义答案、审查任务合理性、最终优先级决策

### 2.2 改造后工作流

```
PM 提交 PRD (Markdown / 纯文本)
    ↓ [AI介入点1: 需求提取 + 歧义检测] < 60秒
结构化需求列表 + 歧义报告 → PM 答复澄清问题 (异步, 无需评审会)
    ↓ [AI介入点2: 任务生成]
任务草稿 (含验收标准 + 工时估算 + 风险标注 + 依赖关系)
    ↓ [人工审查] 15-30分钟
Tech Lead 审查 + 调整 + 确认
    ↓
JSON 导出 / Markdown 报告（可手动导入 Jira/Linear）
```

**改造后耗时（预估）**：人力从 4-8 小时降至 0.5-1 小时

### 2.3 技术方案选型

#### 模型选择：阿里百炼 DashScope + deepseek-v4-flash

使用阿里百炼（Bailian）平台的 OpenAI 兼容接口，默认模型为 `deepseek-v4-flash`：

| 维度 | 选型 | 理由 |
|------|------|------|
| 默认模型 | `deepseek-v4-flash` | 百炼免费额度可用，推理速度快，中文理解良好 |
| 结构化输出 | Tool Use（OpenAI function calling） | 强制 schema 合规，避免字符串解析 |

#### 为什么选 Function Calling

| 方案 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| Function calling | 强制结构化输出，Pydantic 直接验证 | 需要设计 tool schema | **选择** |
| 返回 JSON 字符串 | 简单 | 格式易出错，需手动解析，截断难以发现 | × |
| 微调专属模型 | 定制化高 | 成本高，需大量训练数据 | × |
| 规则引擎 + NLP | 可解释性强 | 无法处理非结构化输入的多样性 | × |

#### 为什么两阶段分析

单次分析让 AI 同时完成"理解需求"和"生成任务"两个目标，会导致 prompt 过于复杂，输出质量下降。分成两个独立的 API 调用：

1. **Phase 1**：专注理解——需求提取（功能/非功能/约束）+ 歧义识别
2. **Phase 2**：以 Phase 1 结果为上下文，专注生成任务（含验收标准、工时估算、风险等级、依赖关系）

每个阶段的 prompt 和 tool schema 更精准，输出质量更高，也更容易分阶段调试。

---

## 3. MVP 实现范围

### 3.1 MVP 包含

**CLI 工具（`main.py`）**
- 接受 Markdown PRD，输出结构化 JSON + Markdown 报告
- `--verbose` 显示任务详情，`--jira` 输出 Jira 兼容格式
- 终端展示歧义报告、任务列表（含风险色彩标注）

**Web 界面（`web_app.py` + `static/index.html`）**
- FastAPI 后端：文件上传 → AI 分析 → 内存存储
- 单页前端：拖拽上传、左侧历史列表、右侧标签页报告
- 支持深色/浅色主题切换
- 报告三标签页：需求（按类型分组 + 优先级徽章）/ 歧义（含澄清问题）/ 任务（含验收标准、风险、工时）
- 一键导出 JSON 和 Markdown

**评测框架（`evaluate.py`）**
- 对比 AI 输出与人工标注 ground truth，量化三项核心指标
- 默认使用 LLM-as-Judge 语义裁判
- 支持任意 PRD 和 GT 文件（`--prd`、`--gt` 参数），自动按命名约定推断 GT
- 保存带时间戳的评测报告

**主要测试案例**
- `complex_prd.md` + GT：购物车 / 结账订单场景
- `points_prd.md` + GT：积分系统场景
- `tokenrouter_prd.md` + GT：真实开源项目PRD

---

## 4. 核心数据模型

```python
PRDAnalysisResult
├─ prd_title: str
├─ requirements: List[Requirement]
│   ├─ id, type (functional/non_functional/constraint)
│   ├─ description, priority (high/medium/low)
│   └─ source_section
├─ ambiguities: List[Ambiguity]
│   ├─ id, location, issue
│   └─ clarifying_question
├─ tasks: List[Task]
│   ├─ id, title, description
│   ├─ acceptance_criteria (恰好2条)
│   ├─ effort_estimate, risk_level
│   └─ dependencies, related_requirements
└─ summary: AnalysisSummary
    ├─ total_requirements, functional_count, non_functional_count
    ├─ ambiguity_count, total_tasks
    └─ estimated_total_effort
```

---

## 5. 效果指标与评估方法

### 5.1 核心指标

| 指标 | 定义 | 目标值 | 评测方法 |
|------|------|------|---------|
| 需求覆盖率 | AI提取需求 与 GT 语义匹配比例 | ≥ 80% | evaluate.py（LLM-as-Judge） |
| 歧义检测率（显性） | AI发现显性歧义 / GT 显性歧义总数 | ≥ 80% | evaluate.py（LLM-as-Judge） |
| 歧义检测率（隐性） | AI发现隐性歧义 / GT 隐性歧义总数 | ≥ 40% | evaluate.py（LLM-as-Judge） |
| 任务完整度 | 含必填字段的任务比例 | 100% | 结构化 schema 验证 |
| 处理速度 | 端到端分析耗时 | < 90s | 计时器 |

### 5.2 LLM-as-Judge 评测原理

Token-F1 匹配在中文场景下有固有局限：措辞不同但语义等价的句子 F1 趋近于 0。因此默认使用 LLM 语义裁判：

```
对每条 GT 条目：
  将 GT 描述 + AI 全部候选文本 → 发送给 deepseek-v4-flash
  让模型判断"候选列表中是否存在语义等价的条目"→ YES / NO
```

代价：每次评测额外消耗约（GT需求数 + GT歧义数）次 API 调用。
收益：准确率显著高于字符串匹配，能识别措辞完全不同但意思相同情况。

### 5.3 Ground Truth 设置

```
tests/fixtures/
├─ complex_prd.md               # 电商购物车/结账/订单场景
├─ complex_prd_ground_truth.json  # 23需求 + 13歧义
├─ points_prd.md                # 积分系统场景
├─ points_prd_ground_truth.json
├─ tokenrouter_prd.md           # 真实开源项目（LLM API网关）
└─ tokenrouter_prd_ground_truth.json  # 22需求 + 8歧义
```

评估命令：

```powershell
$env:DASHSCOPE_API_KEY = "sk-..."
# 使用默认 PRD（complex_prd.md）
python evaluate.py --verbose

# 使用其他 PRD（自动推断同名 GT 文件）
python evaluate.py --prd tokenrouter_prd.md --verbose --save
```

### 5.4 实测结果（complex_prd.md，LLM-as-Judge）

| 指标 | 目标 | 实测结果 |
|------|------|---------|
| 需求覆盖率 | ≥ 80% | ≥ 87% |
| 歧义检测率（显性） | ≥ 80% | 80% |
| 歧义检测率（隐性） | ≥ 40% | ≥ 50% |
| 任务完整度 | 100% | 100% |
| 处理速度 | < 90s | 约 30-60s |

---

## 6. 可 扩展路径

```
Stage 1 (MVP, 当前)
├─ CLI 工具（main.py）
├─ Web 界面（web_app.py + index.html）
├─ PRD → JSON + Markdown 闭环
├─ 量化评测框架（evaluate.py）
└─ 三套 Ground Truth 夹具

Stage 2
├─ Jira/Linear API 直连
├─ 持久化存储（当前为内存，重启丢失）
└─ 支持 .docx / PDF 格式导入

Stage 3
├─ 历史 PRD 向量库（RAG）
│   └─ "类似购物车 PRD 上次有这些歧义..."
├─ 估算校准（用历史实际工时修正估算）
└─ PM 实时歧义警告（Confluence 插件）

Stage 4
└─ 闭环学习：实际开发数据反哺估算模型
```
