# TokenRouter MVP 产品需求文档 (PRD)

> 最后更新：2026-04-16 | 版本：v1.0

---

## 1. 产品概述

### 1.1 产品名称
TokenRouter MVP

### 1.2 产品定位
TokenRouter 是 LLM 调用层的结构整合者，作为个人开发者调用大模型的中转站：
- 统一接口：提供 OpenAI 兼容的 API 接口
- 多厂商适配：MVP v0.1 先接入 DeepSeek V3.2，架构预留扩展位，支持后续无缝切换模型
- 智能缓存优化：通过结构收敛最大化厂商侧 KV Cache 命中率
- 简单管理：提供 API Key 管理、用量统计和计费查询

### 1.3 目标用户
- 个人开发者
- 小团队开发
- 个人项目或类似 OpenClaw Agent 的产品

---

## 2. Problem Statement

个人开发者在使用多种大模型时面临两大核心痛点：

1. **成本太高**：单独调用各个厂商的大模型 API 费用昂贵，无法有效利用厂商的缓存优惠机制

2. **多厂商切换太麻烦**：需要维护多个 API Key、处理不同的请求格式、管理不同的认证方式

个人开发者需要使用 OpenAI 协议对接各种模型，有频繁切换模型的需求，主要用于个人项目或类似 OpenClaw Agent 的产品。

---

## 3. Solution

构建一个 TokenRouter API 服务，作为个人开发者调用大模型的中转站：

1. **统一接口**：提供 OpenAI 兼容的 API 接口，开发者只需修改 base URL 和 API Key 即可使用
2. **多厂商适配**：MVP v0.1 先接入 DeepSeek V3.2，架构层面通过 `OutboundAdapter` 注册表预留 Anthropic / OpenAI 等扩展位，支持后续无缝切换模型
3. **智能缓存优化**：通过结构收敛最大化厂商侧 KV Cache 命中率，显著降低调用成本
4. **简单管理后台**：提供 API Key 管理、用量统计和计费查询功能

---

## 4. User Stories

1. 作为个人开发者，我想用我的 OpenAI SDK 直接调用 TokenRouter，这样我不需要修改代码就能切换到多个厂商
2. 作为个人开发者，我想在一个请求中切换不同的模型，这样可以对比不同模型的效果
3. 作为个人开发者，我想通过 TokenRouter 降低我的 API 调用成本，这样我可以在相同预算下做更多实验
4. 作为个人开发者，我想查看我的 API 用量统计，这样我可以了解我的消费情况和成本节省
5. 作为个人开发者，我想管理我的 API Keys，这样我可以为不同的项目使用不同的 Key
6. 作为个人开发者，我想使用流式调用，这样我可以获得更好的实时体验
7. 作为个人开发者，我想使用函数调用功能，这样我可以构建 Agent 类的应用
8. 作为个人开发者，我想获得厂商原生的所有功能（如 Anthropic 的 thinking、cache_control），这样我不会因为使用网关而损失能力
9. 作为个人开发者，我想让相同的请求能够复用响应（去重），这样我可以进一步节省成本
10. 作为个人开发者，我想有简单的健康检查接口，这样我可以监控服务状态
11. 作为个人开发者，我想查看支持的模型列表，这样我可以知道有哪些模型可用
12. 作为个人开发者，我想我的请求能够快速响应（延迟增加 < 100ms），这样我的应用体验不会受影响
13. 作为个人开发者，我想有详细的 API 文档和示例代码，这样我可以快速集成
14. 作为个人开发者，我想看到我的成本节省数据，这样我可以知道使用 TokenRouter 带来的实际价值
15. 作为个人开发者，我想服务有测试覆盖和性能数据，这样我可以放心使用

---

## 5. Implementation Decisions

### 5.1 技术栈

#### 后端技术栈

| 层级 | 技术 | 版本 | 选型理由 |
|------|------|------|---------|
| 后端语言 | Go | 1.22+ | 高并发、单二进制、编译型语言 |
| Web 框架 | Gin | - | 轻量高性能、中间件生态完善 |
| ORM | GORM | - | Go 主流 ORM、自动迁移 |
| 数据库 | PostgreSQL | 16 | ACID、JSON 支持、成熟生态 |
| 缓存 | Redis | 7 | 高性能 KV 存储、Pub/Sub |
| 时序扩展 | TimescaleDB | - | PostgreSQL 原生扩展、时序查询优化 |
| 消息队列 | NATS | - | 轻量高性能、Go 原生集成 |
| 容器化 | Docker | - | 标准化部署 |
| 编排 | Kubernetes | - | 弹性伸缩、服务发现 |
| 监控 | Prometheus + Grafana | - | 云原生监控标准 |
| 日志 | Zap + Loki | - | 结构化日志 + 日志聚合 |
| CI/CD | GitHub Actions | - | 与代码仓库集成 |

#### 前端技术栈（Phase 2）

| 层级 | 技术 | 版本 | 选型理由 |
|------|------|------|---------|
| 框架 | Next.js | 14+ | App Router、SSR、API Routes 一体化 |
| UI 组件库 | shadcn/ui | latest | AI 友好、无样式组件 |
| 样式方案 | Tailwind CSS | 3.4+ | 原子化 CSS、快速实现设计规范 |
| 状态管理 | Zustand | 4+ | 轻量简单，管理后台无需复杂状态 |
| 数据请求 | TanStack Query | 5+ | 缓存、自动刷新，简化 API 调用 |
| 图表库 | Recharts | 2+ | React 原生、轻量，适合监控面板 |
| 表单验证 | React Hook Form + Zod | - | 类型安全的表单验证 |

### 5.2 核心架构

- **单体架构**（MVP 阶段）
- **无状态设计**
- **处理流水线**：
  ```
  Inbound → Chunker → Arranger → Canonicalizer → Cache Injector → Hasher → Dedup → Outbound → Proxy
  ```

### 5.3 核心模块

#### Inbound Adapter 层
- **MVP**：只实现 `OpenAIAdapter`，支持 OpenAI 兼容格式入站
- **预留接口设计**：支持后期添加更多原生入站适配器
- **注册表模式**：通过 `InboundAdapter` 接口 + Registry 模式支持动态注册

#### Outbound Adapter 层
- **MVP v0.1**：实现 `DeepSeekAdapter`（基于 OpenAI 兼容协议），预留 `AnthropicAdapter` / `OpenAIAdapter` 空壳
- **预留接口设计**：支持后期添加更多厂商适配器
- **注册表模式**：通过 `OutboundAdapter` 接口 + Registry 模式支持动态注册

#### 其他核心模块
- **Chunker**：静态四分块（System/Tool/History/Query）
- **Arranger**：固定顺序排列、块级处理
- **Canonicalizer**：确定性 JSON 序列化
- **Cache Injector**：MVP v0.1 对 DeepSeek / OpenAI 透传；`Injector` 接口已预留，后续直接添加 Anthropic `cache_control` 注入
- **Hasher**：前缀哈希 + 完整哈希计算
- **Dedup**：非流式请求去重
- **Proxy**：HTTP/SSE 代理转发
- **Billing Engine**：双层计费记录
- **Auth Middleware**：API Key 认证
- **Rate Limit Middleware**：速率限制

### 5.4 核心接口

#### 当前 MVP 接口
- **POST /v1/chat/completions**：OpenAI 兼容的聊天接口（MVP 唯一入站接口）
- **GET /v1/models**：模型列表
- **GET /health**：健康检查
- **GET /metrics**：Prometheus 指标
- **管理后台 API**：API Key 管理、用量统计

#### 预留扩展接口（Phase 2）
- **POST /v1/messages**：Anthropic Messages API 原生接口
- **POST /v1beta/models/{model}:generateContent**：Google Gemini 原生接口
- **其他厂商原生端点**：按需求添加

### 5.5 优先级排序

- **P0（必须有）**：Inbound/Outbound Adapter、Chunker、Arranger、Canonicalizer、Proxy、基础认证
- **P1（应该有）**：Cache Injector、Hasher、Dedup、Billing、速率限制、用量统计
- **P2（可以有）**：管理后台界面、高级监控、动态缓存算法（Phase 2）

---

## 6. Testing Decisions

### 6.1 测试原则

- 测试外部行为，不测试实现细节
- 测试驱动开发（TDD），先写测试再写代码
- 所有核心模块必须有单元测试
- 必须有集成测试覆盖完整链路
- 必须有端到端测试使用真实 API Key（小流量）

### 6.2 测试模块

| 模块 | 测试重点 | 最低覆盖率 |
|------|---------|-----------|
| Chunker | 各种 messages/tools 组合的切分正确性 | 80% |
| Arranger | System 合并、Tool 排序、History 截断 | 80% |
| Canonicalizer | 等价输入输出字节一致 | 必须 100% |
| Hasher | 相同输入输出相同，不同输入几乎不碰撞 | 80% |
| Outbound Adapters | Block → JSON 的正确还原 | 70% |

### 6.3 验收标准

- 完成 50 个子 Agent 测试工程师的验收
- 所有单元测试通过
- 所有集成测试通过
- 端到端测试通过 DeepSeek V3.2
- P99 延迟增加 < 100ms（不含厂商响应时间）
- KV Cache 命中率 > 40%（通过 DeepSeek `prompt_cache_hit_tokens` 度量）
- 至少 1 个真实用户在生产环境跑通

---

## 7. Out of Scope

以下内容不在本次 MVP 范围内，但预留了扩展接口：

- Anthropic 原生入站接口（/v1/messages）
- Google Gemini 原生入站接口
- 动态缓存算法（Observer/Clusterer/动态模板池）
- 智能路由（成本最优路由）
- 语义缓存（基于 embedding 的近似匹配）
- 对话历史托管（session 状态）
- 流式请求去重
- 商业化功能（支付、发票、订阅）
- 团队/组织管理
- SSO 认证
- 审计日志
- 高级分析和报表

---

## 8. 成功标准（MVP 验收）

以下条件**全部满足**，方可宣布 MVP 完成：

- [ ] 支持 OpenAI 格式入站，DeepSeek V3.2 出站（架构已预留 Anthropic / OpenAI 扩展位）
- [ ] 前缀哈希一致性验证：两个结构相同但来源不同的请求，前缀哈希一致
- [ ] 并发非流式相同请求能触发去重复用
- [ ] P99 延迟增加 < 100ms（不含厂商响应时间）
- [ ] KV Cache 命中率 > 40%（通过 DeepSeek `prompt_cache_hit_tokens` 度量）
- [ ] 至少 1 个真实用户在生产环境跑通
- [ ] 完成 50 个子 Agent 测试工程师的验收
