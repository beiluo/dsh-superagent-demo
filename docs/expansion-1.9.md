# 1.9 决策层扩展：从“规则清单”到可推理的决策生命周期

> 版本：1.9.0 · 对应分支：`agent/decision-layer-be9e6c1280f0` · 日期：2026-11

这次扩展直接回应“作为决策本体还远远不够”的反馈。1.9 不再只增加公司、行情和规则，
而是把**决策本身**拆成可推理的层级：

1. **账户与持仓状态**：决策前先知道账户有多少钱、能买多少、持仓可卖多少、成本和浮盈亏；
2. **组合风险预算**：把总风险资本、单笔风险、单票/行业上限、回撤和 VaR 变成可检查的限额；
3. **买卖点与仓位联动**：把买点、止损、目标、预计权重、数量和风险金额写进同一份交易计划；
4. **执行到复盘的闭环**：成交滑点、结果、复盘发现、经验教训和规则修订回写到下一轮决策。

## 1. 扩展前后

| 指标 | 1.8 | 1.9 | 增量 |
| --- | ---: | ---: | ---: |
| 三元组 | 40,574 | 44,372 | +3,798 |
| 类 | 294 | 337 | +43 |
| 对象属性 | 167 | 258 | +91 |
| 数据属性 | 284 | 395 | +111 |
| 个体 | 2,355 | 2,410 | +55 |
| SKOS 概念 | 147 | 173 | +26 |
| SWRL 规则 | 151 | 161 | +10 |
| OWL-S 服务 | 1 | 2 | +1 |
| ODRL 政策 | 5 | 6 | +1 |
| 能力问题 | 10 | 20 | +10 |
| OWL RL 闭包 | 60,963 | 69,413 | +8,450 |

## 2. 决策层级

新增 `scheme-decision-level`，把决策分为：

| 层级 | 含义 | 主要对象 |
| --- | --- | --- |
| 战略配置 | 资产类别、行业与风格的中长期比例 | `Portfolio`、`InvestmentStrategy` |
| 战术配置 | 行业、主题与个股权重调整 | `InvestmentDecision`、`RiskBudget` |
| 交易执行 | 买卖点、数量、价格与订单意图 | `TradePlan`、`PositionSizing`、`OrderIntent` |
| 复盘迭代 | 结果评价、发现、经验与规则修订 | `PostTradeReview`、`ReviewFinding`、`RuleRevision` |

`DecisionCycle` 把一次决策的 `AccountState` → `RiskBudget` → `InvestmentDecision` →
`TradePlan` → `Order`/`Trade` → `DecisionOutcome` → `PostTradeReview` 串成可追溯周期；
`DecisionContext` 固定决策时点的账户、预算、组合风险与市场状态。

## 3. 账户与持仓状态

| 类 | 作用 |
| --- | --- |
| `Account` / `SecuritiesAccount` | 账户编号、状态、币种、所属投资者与组合 |
| `AccountState` | 现金、可用资金、冻结资金、购买力、总资产快照 |
| `PositionState` | 数量、可卖数量、冻结数量、市值、最新价、浮盈亏、持有天数 |
| `PositionLot` | 建仓批次、成本与日期，支持 FIFO、分批止盈 |
| `CashMovement` | 入金、出金、买入、卖出、分红与费用流水 |

关键关系：`Account holdsPortfolio Portfolio`、`Account hasAccountState AccountState`、
`Position hasPositionState PositionState`、`Position hasPositionLot PositionLot`。
这些状态不是属性值，而是带 `dataAsOf` 的快照，因此可以保留历史并支持复盘。

## 4. 组合风险预算

| 类 | 作用 |
| --- | --- |
| `RiskBudget` | 总风险资本、已用/剩余、使用率、单笔风险、单票/行业/回撤/VaR 限额 |
| `RiskBudgetAllocation` | 把预算分配到证券或策略，记录额度、已用与使用率 |
| `RiskLimit` | 单票权重、单笔风险、总预算、最大回撤、VaR 等硬/软限额 |
| `RiskUtilization` | 某一时点的使用率与 NORMAL/WARNING/BREACH/HALT 状态 |
| `PortfolioRiskSnapshot` | 波动率、VaR95、预期损失、Beta、跟踪误差、HHI、最大回撤 |
| `RiskContribution` | 单一持仓或行业的风险贡献与边际贡献 |

示例组合风险预算 80 万元，已用 62 万元（77.5%），剩余 18 万元，单笔风险 2 万元，
单票上限 10%。华辰智造当前权重 12%，单票限额使用率 120%，因此新增买入被阻断，
减仓计划才是可执行的修复动作。

## 5. 买卖点与仓位联动

`TradePlan` 是交易计划的抽象类，`EntryPlan` 和 `ExitPlan` 分别表达买入与卖出计划：

```text
InvestmentDecision → hasTradePlan → EntryPlan
EntryPlan → hasEntryPrice → EntryPrice(35.00)
          → hasStopPrice  → StopPrice(30.50)
          → hasTargetPrice→ TargetPrice(45.00)
          → hasPositionSizing → PositionSizing(20000 股, 预计权重 20.5%, 风险 1.8 万元)
          → hasOrderIntent → OrderIntent(BUY 20000 @35.00, PENDING_APPROVAL)
```

`PositionSizing` 记录测算方法、数量、权重变化、预计权重与风险金额；
`MarketSingleNameWeight`（`RiskBudget`）与 `projectedWeight` 一起完成“加仓后是否会超限”的
前置检查，而不是等成交后才发现超限。`TradeTrigger` / `EntryTrigger` / `ExitTrigger`
把价格、技术、基本面和再平衡条件写成可查询对象。

## 6. 执行到复盘的闭环

| 阶段 | 类 | 关键字段 |
| --- | --- | --- |
| 执行 | `Trade` + `ExecutionQuality` | 成交价、数量、滑点、成交率、延迟、市场冲击 |
| 结果 | `DecisionOutcome` | 已实现收益、盈亏、持有期、最大不利/有利偏移 |
| 复盘 | `PostTradeReview` | 过程评分、结果评分、结论、完成/截止日、逾期天数 |
| 发现 | `ReviewFinding` | 类型、严重程度、建议、重复出现次数 |
| 经验 | `LessonLearned` | 经验内容、改进行动、状态 |
| 归因 | `PerformanceAttribution` | 配置、选择、择时、成本或运气 |
| 修订 | `RuleRevision` | 修订哪条规则、理由、生效日、状态 |

示例闭环：2026-11 华辰减仓 → 滑点 12 bps、收益 15.8%、持有 200 天 → 复盘发现
“R06 只看当前权重、漏掉加仓后预计权重”（重复 2 次）→ 经验“交易前强制检查 projectedWeight”
→ 规则修订 `RR-2026-001`，生效后新增 R154 预计权重规则。

## 7. 新增规则

| 编号 | 规则 | 前件 | 后件 |
| --- | --- | --- | --- |
| R152 | 风险预算超限 | `riskBudgetUtilization ≥ 100` | `RiskBudgetExceeded` |
| R153 | 单笔风险超限 | `riskAmount > riskPerTradeLimit` | `PositionSizingBreach` |
| R154 | 预计权重超限 | `projectedWeight > maxSingleNameWeight` | `EntryBlocked` |
| R155 | 购买力不足 | `plannedNotional > buyingPower` | `BuyingPowerInsufficient` |
| R156 | 止损价触发 | `stateLastPrice ≤ stopPrice` | `StopPriceBreached` |
| R157 | 目标价到达 | `stateLastPrice ≥ targetPrice` | `TakeProfitReached` |
| R158 | 执行滑点超限 | `slippageBps > 50` | `ExecutionSlippageBreach` |
| R159 | 复盘逾期 | `reviewOverdueDays ≥ 5` | `ReviewOverdue` |
| R160 | 重复高严重度发现 | `findingSeverity = high 且 occurrenceCount ≥ 2` | `RuleRevisionRequired` |
| R161 | 硬性限额暂停交易 | `riskLimitHard = true 且 riskUtilizationPct ≥ 100` | `TradingHalted` |

SWRL 仍然只做单调推理；数据新鲜度、冲突处理、时间窗口和人工审批仍由外部工程逻辑执行。

## 8. 服务与政策

新增 OWL-S 服务 `svc-trade-lifecycle`，八步流程：

```text
账户快照 → 风险预算 → 买卖点 → 仓位测算 → 约束审批 → 订单意图 → 执行复盘 → 规则迭代
```

原有 `svc-ashare-decision` 保留为“从数据到投资决策”的七步服务；两个服务共享 profile 分类，
但生命周期服务明确把账户、预算、交易计划和复盘纳入输入/输出。

新增 ODRL 政策 `policy-trade-lifecycle`：

- 风险预算使用率必须低于 100%，且交易计划只能用于投资决策支持；
- 人工批准为 false 时禁止执行订单意图；
- 风险预算使用率达到 100% 时禁止执行交易计划；
- 义务包括标注来源和完成交易后复盘。

## 9. Agent 能力

确定性规则模式新增 `evaluate_trade` 工具，直接读取 1.9 的账户、预算、计划、成交与复盘：

- 买入结论：当前权重、预计权重、单笔风险、购买力、风险预算使用率、硬性限额、人工审批；
- 卖出结论：可卖数量（T+1 与冻结扣除）、止损/目标价、限制名单、人工审批；
- 限制清单：单票、单笔、购买力、预算、审批与减仓例外；
- 闭环：执行质量、结果、复盘发现与规则修订。

可以这样问：**华辰智造的买点、卖点和仓位限制是什么？**
**组合的风险预算还剩多少？** **这次减仓为什么被阻断？**

LLM 模式仍然只用 `load_company_data`、`describe_ontology` 和 `sparql_query`
三项能力，由模型自己查询新增类；不需要把新工具硬编码进 LLM。

## 10. 示例与校验

新增示例：

- 账户 `ACC-2026-001`：现金/购买力 85 万元，总资产 3,680 万元；
- 三条持仓状态：华辰 12%、宁源 5%、景康 3%，含可卖数量、浮盈亏与持有天数；
- 组合风险预算、四项限额、两项使用率、风险快照与三项风险贡献；
- 四份华辰交易计划：加仓（受阻）、减仓至 10%（就绪）、止损止盈（生效）、10 月减仓（已成交）；
- 执行质量、决策结果、复盘、发现、经验、归因与规则修订；
- 决策周期与决策上下文。

校验结果：

```text
A-share ontology validation passed.
  modules: 7
  triples: 44372
  classes: 337
  object properties: 258
  data properties: 395
  SKOS concepts: 173
  SWRL rules: 161
  OWL-S services: 2
  ODRL policies: 6
  OWL RL closure: 34487 -> 69413 triples (34926 inferred)
  warnings: 0
```

`make test`：121 passed。

## 11. 仍然不是交易系统

1.9 仍然是**决策支持本体**，不是账户管理系统或交易系统：

- 账户、持仓、成交、预算和复盘都是合成示例，不连接券商或真实账户；
- `OrderIntent` 只表示等待人工确认的意图，不发送委托；
- OWL-S 端点和 WSDL 操作名是示意；
- ODRL 政策是声明式约束，校验脚本不执行政策决策；
- OWL 2 DL 一致性和 SWRL 执行仍需要外部推理机；
- 风险预算阈值、单票上限和滑点阈值是演示常量，生产环境应外置为可版本化参数。

扩展原则不变：先有业务含义、能力问题、数据源和约束，再增加节点；不以节点数作为验收标准。
