# 1.11 规则库 V2.0：从 60 条业务规范到可浏览的本体

> 版本：1.11.0 · 对应 Issue [#25](https://github.com/beiluo/dsh-superagent-demo/issues/25) · 日期：2026-11
>
> 本文说明如何把 A 股投资决策规则库 V2.0 的 60 条规则、职责分层、统一状态机、证据口径和参数占位
> 编码进本体，以及这些内容与既有 SWRL 规则、页面和 Agent 的边界。

## 1. 这次要解决的问题

Issue #25 给出的是一份完整的规则业务规范，而不是 60 个阈值。它要求每条规则都能说明：

- 识别什么市场现象；
- 在什么市场环境、持仓状态、周期和证券范围内适用；
- 需要哪些输入、观察哪些维度；
- 什么条件触发，哪些证据支持或反驳，什么条件直接否决；
- 处于统一状态机的哪个状态，如何失效、过期或重新建立实例；
- 触发后调用哪些规则，参数初值是什么，如何验证有效性。

因此 1.11 不把 60 条规则简单加权成一个总分，也不把新闻标题或价格形态直接变成交易指令。
规则输出的是**状态与证据**，风险层和授权层仍拥有最终约束力。

## 2. 本版本增量

| 指标 | 1.10 | 1.11 | 增量 |
| --- | ---: | ---: | ---: |
| 三元组 | 47,958 | 52,810 | +4,852 |
| 类 | 363 | 389 | +26 |
| 对象属性 | 317 | 349 | +32 |
| 数据属性 | 494 | 554 | +60 |
| 个体 | 2,480 | 2,619 | +139 |
| SKOS 概念 | 225 | 225 | 0 |
| SWRL 规则 | 169 | 169 | 0 |
| 规则库 V2.0 规则 | 0 | 60 | +60 |
| OWL-S 服务 | 3 | 3 | 0 |
| ODRL 政策 | 7 | 7 | 0 |
| OWL RL 闭包 | 37,236 → 78,339 | 37,929 → 80,057 | +1,721 推断三元组 |

## 3. 60 条规则与职责分层

规则按 8 类职责组织，类别不是打分权重：

| 类别 | 条数 | 职责 | 越权边界 |
| --- | ---: | --- | --- |
| OP 机会结构 | 10 | 识别可交易的价格结构与机会形态 | 不独立决定仓位 |
| VP 量价证据 | 8 | 判断价格变化是否得到成交行为支持 | 不单独产生买入信号 |
| AUC 竞价证据 | 6 | 识别开盘前供需与预期变化 | 不把竞价强弱等同全天趋势 |
| MKT 市场环境 | 7 | 判断系统性风险、情绪与板块背景 | 不用板块热度替代个股判断 |
| EVT 事件证据 | 6 | 判断事件真实性、传导路径和兑现状态 | 不把新闻标题直接当利好 |
| POS 持仓管理 | 8 | 管理持仓延续、减仓、止盈和加仓 | 不绕过风险预算与交易约束 |
| RSK 风险约束 | 7 | 过滤不可承受的风险与不合规交易 | 不预测价格方向 |
| EVA 结果评估 | 8 | 验证规则、决策和执行是否有效 | 不用单笔盈亏证明规则好坏 |
| **合计** | **60** |  |  |

本体映射：

- 每个类别是 `ash:RuleCategory` 个体，带 `categoryCode`、`categoryResponsibility`、
  `categoryBoundary`、`categoryOrder` 和对应的 `DecisionRule` 子类；
- 每条规则是 `ash:DecisionRule` / 类别子类 / `ash:RuleArtifact` 个体，带 `ruleId`、双语标签、
  定义、适用范围、前置条件、输入、观测、触发、反向证据、否决、状态机路径、后续动作、失效机制、
  参数说明、典型场景、反例、验证方法和置信度依据；
- 规则用 `belongsToRuleCategory` 归入类别，用 `ruleNextRule` / `ruleRelatedRule` 指向相关规则。

## 4. 统一状态机

9 个状态：

`NOT_OBSERVED` → `WATCHING` → `CANDIDATE` → `TRIGGERED` → `CONFIRMED`；
同时存在 `CONFLICTED`、`INVALIDATED`、`EXPIRED`、`DATA_INSUFFICIENT`。

`RuleStateMachine` 定义允许状态，`RuleStateTransition` 定义 23 条允许迁移；`RuleStateChange`
记录实际迁移的 `changeAt`、`changeFrom`、`changeTo`、触发证据、反向证据和数据版本。
失效态和过期态是终止态；重新出现时必须建立新的信号实例，不能无依据地从失效回到确认。
关键输入缺失时输出 `DATA_INSUFFICIENT`，不得把缺失解释为没有风险或没有信号。

## 5. 输出契约

`RuleOutput` / `RuleRun` 要求每次运行至少输出：

```text
rule_id, security_id, as_of, timeframe, position_state, state,
trigger_evidence[], supporting_evidence[], contrary_evidence[], missing_data[],
parameters_version, valid_until, next_actions[], source_refs[], confidence_basis
```

示例：

- `rule-run-op-001-20261105`：华辰智造日线突破，输出 `CANDIDATE`，
  包含触发证据（收盘越过压力区）、支持证据（成交额改善）、反向证据（板块走弱）、
  缺失数据（缺分钟路径）、参数版本、有效期和后续动作；
- `rule-run-rsk-007-20261105`：交易制度字段缺失，输出 `DATA_INSUFFICIENT`，
  不默认放行；展示硬约束前检查的数据不足边界。

## 6. 证据与数据质量约定

新增 `RuleEvidence` 的四个子类：`TriggerEvidence`、`SupportingEvidence`、
`ContraryEvidence`、`MissingData`。7 条 `DataQualityConvention` 覆盖：

1. 价格口径统一（复权口径、执行价用真实未复权价）；
2. 成交口径统一（来源、单位、是否含集合竞价）；
3. 时间口径统一（收盘确认、盘中临时、竞价/连续竞价不混用）；
4. 横截面比较（同一交易日、同一市场范围、合理行业/主题样本）；
5. 数据缺失输出 `DATA_INSUFFICIENT`；
6. 事件去重（转载、快讯、解读关联到同一事件实体）；
7. 幸存者偏差（回测包含退市、停牌、风险警示和历史成分变更）。

## 7. 参数占位

每条规则有一个 `RuleParameter` 个体，保存：

- 参数名称与待回测的初始范围/表达式；
- 参数版本，例如 `OP-001-cn-equity-2026-01`；
- 状态 `initial` 与“待回测、不是收益承诺”的注记；
- 按流动性、波动率、板块和市场状态分层校准的说明。

参数是占位，不是生产参数。策略运行时必须固定参数版本，禁止静默修改阈值；
参数调整必须保留旧版本、修改原因、样本外表现与回滚条件。

## 8. 与 SWRL、Agent 和页面的关系

- **SWRL**：仍是可执行 Horn 子集；V2.0 规则是业务规范，不自动执行，也不产生订单。
- **Agent**：`ash:RuleArtifact` 仍可被 `store.rules()` 读取；规则卡片展示规范字段，
  Agent 回答可以引用规则编号，但不会把规范规则当作已触发信号。
- **页面**：规则区新增“规则库 V2.0”筛选，共 229 条（169 条 SWRL + 60 条规范规则）；
  规范卡片展示 TRIGGER、SCOPE、类别、状态机、证据、参数占位和“在浏览器中查看”。
- **不改变既有语义**：1.10 的五引擎认知、1.9 的决策生命周期、1.8 的短线规则继续保留；
  规则库只是把业务规范、状态与证据口径接入同一套 IRI。

## 9. 校验与实际结果

```text
A-share ontology validation passed.
  modules: 7
  triples: 52810
  classes: 389
  object properties: 349
  data properties: 554
  SKOS concepts: 225
  SWRL rules: 169
  OWL-S services: 3
  ODRL policies: 7
  OWL RL closure: 37929 -> 80057 triples (42128 inferred)
  warnings: 0
```

`make test` 同时覆盖服务端 API、规则阈值、查询、证据、约束、真实数据、LLM 回退与密钥扫描。

## 10. 边界

1. 60 条规则的阈值仍是待验证初始参数，不是最优值或收益承诺；
2. 规范规则不替代 SWRL 推理引擎，也不替代交易日历、涨跌停、T+1 和订单撮合；
3. 事件真实性、竞价逐时点路径、历史成分和供应商字段口径仍需外部数据验收；
4. 规则冲突、状态迁移和参数校准仍需历史回放与样本外测试；
5. 任何单条规则、单个 Agent 或多数意见都不能绕过风险预算、交易授权与交易所规则校验。
