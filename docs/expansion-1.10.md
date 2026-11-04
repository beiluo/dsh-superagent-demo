# 1.10 交易认知扩展：五引擎判断体系

> 版本：1.10.0 · 对应 Issue [#22](https://github.com/beiluo/dsh-superagent-demo/issues/22) · 日期：2026-11
>
> 本文说明为什么把「市场认知 → 机会识别 → 交易判断 → 行为管理 → 结果验证」落进现有系统，
> 它和 1.9 的决策生命周期有什么差异，以及哪些边界仍然没有改变。

## 1. 这次要解决的问题

1.9 已经把决策拆成账户、风险预算、买卖点、仓位、执行与复盘，但回答“一只股票为什么值得买、
买入之后什么情况下继续持有或卖出”时，仍有两个缺口：

1. **认知维度还是分散的**：市场状态、板块轮动、个股趋势、量价、竞价、事件和风险收益各自有类，
   但没有一条从“环境是否允许交易”到“机会是否成立”再到“判断是否改变”的链路。
2. **买入与持仓共用执行检查**：`evaluate_trade` 在已有决策后检查买点、权重、预算和审批，
   但它不判断机会阶段，也不区分“非持仓寻找买入机会”和“已持仓判断是否继续持有”。

1.10 因此不新增更多分析指标，而是新增一层**判断结构**：五个引擎、两套场景流程、一条证据优先的
判断链，以及可版本化的判断记录。

## 2. 五个引擎不是五个 Agent

| 引擎 | 职责 | 主要输出 |
| --- | --- | --- |
| 市场认知引擎 | 市场趋势、广度、情绪、流动性、风险偏好、短线生态；板块趋势、资金、扩散、龙头、题材持续性 | `MarketCognition`、`SectorCognition` |
| 个股认知引擎 | 趋势方向与阶段、价格位置、关键位、价格结构、波动、趋势质量、量价行为、竞价与盘中行为 | `StockCognition`、`VolumePriceBehavior`、`AuctionBehavior`、`IntradayBehavior` |
| 事件认知引擎 | 事件真实性、业务相关性、是否已被反映、板块共振、价格确认、反向证据 | `EventCognition` |
| 交易机会引擎 | 机会结构、机会阶段、支持证据、反向证据、确认条件与风险收益 | `OpportunityAssessment`、`RiskRewardAssessment` |
| 交易决策引擎 | 分场景形成买入/持有/加仓/减仓/卖出/观望，给出失效条件、行为规则、版本与验证 | `TradingJudgment`、`BehaviorRule`、`JudgmentRevision`、`OutcomeVerification` |

五个引擎的输出被同一个 `AnalysisCase` 串起来，而不是各生成一份报告。一个案例对应一只证券、
一个交易场景和一个数据截止日；判断更新时保留旧版本与触发证据。

## 3. 两条场景流程

### 3.1 非持仓：寻找买入机会

1. 市场是否允许交易；
2. 哪个板块/题材在变化，个股是否获得共振；
3. 趋势、价格结构、量价、竞价与盘中行为是否形成机会结构；
4. 机会是否被成交、板块或事件确认；
5. 反向证据是否逐条审查；
6. 胜率依据、盈亏比、仓位与失效条件是否匹配；
7. 买入、等待还是放弃。

### 3.2 已持仓：管理已有交易

1. 回顾原始买入逻辑；
2. 原始逻辑是否仍然成立；
3. 趋势、量价、板块、事件与市场风险是否变化；
4. 是否触发止损、止盈、减仓或加仓条件；
5. 重新评估剩余上涨空间与潜在风险；
6. 持有、加仓、减仓还是卖出。

持仓管理的原则不是“因为之前买了所以继续持有”，而是“当前继续持有仍然具有正向预期价值”；
卖出也不是“跌了几个点”，而是原始逻辑失效或风险收益关系发生变化。

## 4. 判断链：机会结构 → 证据验证 → 反向证据 → 风险收益

1.10 **不做加权评分**。市场 20 分 + 量价 20 分 + 板块 20 分的方式会把否决性条件稀释成
可被其他分数抵消的数字。判断链是：

```text
机会结构识别
  → 多维证据验证（市场、板块、个股、量价、竞价/盘中、事件）
  → 反向证据审查（逐条说明处置，而不是只扣分）
  → 风险收益评估（胜率依据、盈亏比、仓位、失效条件、成本）
  → 分场景结论
```

硬性门槛可以否决机会：市场风险偏好过低、机会阶段已衰退、反向证据未审查、盈亏比不足、
原始持仓逻辑失效或触发止损。被否决时输出“观望/减仓/卖出”，并说明是哪条证据导致。

## 5. 结构化判断记录

`TradingJudgment` 记录 Issue #22 要求的字段：

| 字段 | 本体属性 |
| --- | --- |
| 股票 | `judgmentOfSecurity` |
| 交易场景 | `hasJudgmentScenario` + `judgmentScenarioCode` |
| 市场状态 | `judgmentMarketState` |
| 个股状态 | `judgmentStockState` |
| 核心机会 | `judgmentCoreOpportunity` |
| 支持证据 | `judgmentBasedOn` |
| 反向证据 | `judgmentCounterEvidence` |
| 机会阶段 | `OpportunityAssessment → hasOpportunityStage` |
| 胜率依据 | `RiskRewardAssessment → winRateBasis` + `winRateSampleSize` |
| 盈亏比 | `expectedRewardRiskRatio` |
| 交易计划 | `judgmentHasPlan → TradePlan` |
| 决策 | `hasJudgmentDecision` + `judgmentDecisionCode` |
| 失效条件 | `judgmentInvalidation` |

`JudgmentRevision` 记录“是什么新事件、新证据改变了之前的判断”：`revisionOfJudgment`、
`revisionFromVersion`、`revisionToVersion`、`revisionReason`、`revisionChangedField`、
`revisionTriggerEvidence`。`OutcomeVerification` 记录结果验证：收益、最大不利/有利偏移、
逻辑是否仍成立、经验教训，并可用 `verificationEvidence` 指回市场证据。

## 6. 与 1.9 的差异

| 维度 | 1.9 现状 | 1.10 新体系 |
| --- | --- | --- |
| 决策入口 | `InvestmentDecision` + `DecisionCycle` | `AnalysisCase` 把五个引擎输出串成一个案例 |
| 判断对象 | 一条投资决策/建议 | 可版本化的 `TradingJudgment`，含场景、证据、阶段与失效条件 |
| 买入与持仓 | 共用 `evaluate_trade` 的执行检查 | `non_position` 与 `held` 两套流程与门槛 |
| 分析维度 | 市场、板块、趋势、量价、竞价、事件、风险收益各自有类 | 七个维度被组织成同一条判断链 |
| 评分方式 | 规则命中/执行检查 | 机会结构 → 证据验证 → 反向证据 → 风险收益，无加权总分 |
| 反向证据 | `DecisionRationale.counterArgument` 文本 | `opportunityCounterEvidence` + `judgmentCounterEvidence` + `counterEvidenceReviewed` |
| 判断变化 | 决策周期/复盘事后记录 | `JudgmentRevision` 在判断变化时记录触发证据与变更字段 |
| 结果验证 | `DecisionOutcome` + `PostTradeReview` | `OutcomeVerification` 直接验证判断逻辑，而不只看盈亏 |
| 行为管理 | `EntryPlan`/`ExitPlan` 的买卖点与触发条件 | `BehaviorRule` 覆盖建仓、加仓、持有、减仓、止盈、止损、观望与优先级 |
| Agent | `evaluate_trade` 检查执行约束 | 新增 `evaluate_cognition`，按五引擎输出判断、行为规则与验证 |
| 服务 | `svc-trade-lifecycle` 八步生命周期 | 新增 `svc-trading-cognition` 七步认知流程 |
| 政策 | `policy-trade-lifecycle` 风险预算与复盘 | 新增 `policy-trading-cognition`：反向证据、市场否决、人工批准与版本义务 |

**保留不变的部分**：

- 1.9 的账户、持仓、风险预算、买卖点、订单意图、执行质量、结果与复盘仍是执行层，不被替换；
- 1.8 的市场状态、板块轮动、竞价、量价、主题生命周期等类被复用；
- `evaluate_trade` 继续回答“计划是否可执行”，`evaluate_cognition` 回答“机会是否成立、判断是什么”；
- 所有数据仍是合成示例，不连接真实行情、账户或交易通道。

## 7. 本体与规则变化

本版本新增：

- 26 个类：5 个认知引擎、`AnalysisCase`、市场/板块/个股/事件/量价/竞价/盘中/机会/风险收益/
  判断/行为规则/判断修订/结果验证，以及 6 个规则推断状态；
- 59 个对象属性、99 个数据属性；
- 8 套 SKOS 方案、52 个概念：机会阶段、交易场景、判断结论、量价行为（含 4 个组合序列）、
  竞价行为、盘中行为、行为动作、结果验证结论；
- 8 条 SWRL 规则：

| 编号 | 规则 | 触发条件 | 推断 |
| --- | --- | --- | --- |
| R162 | 市场风险偏好否决 | `marketRiskAppetiteScore < 30` | `MarketVeto` |
| R163 | 风险收益不足 | `expectedRewardRiskRatio < 2.0` | `RiskRewardInsufficient` |
| R164 | 反向证据未审查 | `counterEvidenceCount ≥ 1` 且 `counterEvidenceReviewed = false` | `JudgmentIncomplete` |
| R165 | 衰退期买入阻断 | 机会阶段 `decline` 且判断为 `buy` | `EntryBlocked` |
| R166 | 判断版本已更新 | `revisionToVersion > revisionFromVersion` | `JudgmentUpdated` |
| R167 | 结果证伪逻辑 | `verificationLogicStillValid = false` | `LogicInvalidated` |
| R168 | 持仓逻辑失效 | 场景 `held` 且 `judgmentLogicStillValid = false` | `ExitRequired` |
| R169 | 机会阶段衰退 | `opportunityStageCode = decline` | `OpportunityInvalidated` |

同时新增 OWL-S 服务 `svc-trading-cognition`（七步：市场认知 → 个股认知 → 事件认知 → 机会识别 →
交易判断 → 行为管理 → 结果验证）和 ODRL 政策 `policy-trading-cognition`，把反向证据审查、
市场否决、人工批准与结果验证写成声明式约束。

## 8. 示例：两个场景

### 8.1 游资科技：非持仓，寻找买入机会

- 市场：震荡修复、局部上涨、风险偏好 55、短线生态连板 3/晋级率 45%/炸板率 22%；
- 板块：AI 主题核心扩散，个股为核心跟随；
- 个股：上升加速、高位、放量突破后缩量回踩、竞价弱转强、RSI 68/换手 18.4%；
- 事件：AI 政策真实且相关，板块共振、价格确认，但已部分被预期；
- 反向证据 2 条（高位过热、政策部分兑现），已审查；
- 风险收益：样本 42、3 日胜率 57%、盈亏比 2.08、计划风险 1.96 万元；
- 判断：v2 买入（小仓位试错），失效条件为跌破 18.50、竞价量比 < 1.5、龙头断板或放量滞涨；
- 行为规则：建仓、加仓、减仓、止盈、止损、观望；
- 结果验证：首日收益 4.2%、最大不利偏移 -1.2%，逻辑成立；
- 判断修订：11-02 首版观望 → 11-03 竞价弱转强与板块扩散后改为买入。

### 8.2 华辰智造：已持仓，判断是否继续持有

- 持仓：权重 12%、成本 31.20、现价 36.80、可卖 90,000 股；
- 市场与板块：震荡修复、高端制造 + AI 仍强但内部分化；
- 个股：中期上升延续，但下午放量跌破 MA20 36.50（最低 36.20，尾盘收回 36.80）；
- 事件：订单增长真实且相关，但已部分反映、价格未确认；
- 机会阶段：衰退；
- 反向证据 2 条（放量跌破、单票权重 12% 超过 10% 硬限额），已审查；
- 风险收益：样本 68、20 日胜率 61%、盈亏比 2.75、目标仓位 10%；
- 判断：v2 减仓至 10%，原始中期逻辑未完全失效，但量价转弱与集中度硬限额要求降低暴露；
- 行为规则：持有、减仓、加仓、止盈、止损；
- 结果验证：当日收益 -0.8%、最大不利偏移 -2.1%，逻辑减弱；
- 判断修订：上午 v1 持有 → 下午放量跌破 + 权重超限后 v2 减仓。

## 9. Agent 能力

确定性规则模式新增 `evaluate_cognition`：

- 读取 `AnalysisCase`、市场/板块/个股/事件/机会/风险收益/判断/行为规则/修订/验证；
- 做 18 项检查（市场 3、机会 5、事件 2、风险收益 3、判断 4、验证 1）；
- 输出计算结论、本体记录结论、是否一致、阻断/提示、五步流水线、行为规则与版本变化；
- 对非持仓与已持仓使用不同门槛：非持仓要求机会阶段为确认/延续、盈亏比 ≥ 2.0；
  已持仓检查原始逻辑、止损、集中度与盈亏比，权重超限时输出减仓。

可以这样问：

- **按市场认知 → 机会识别 → 交易判断 → 行为管理 → 结果验证的体系分析游资科技**
- **华辰智造还值得继续持有吗？**
- **游资科技现在有买入机会吗？**
- **华辰智造上午持有、下午为什么改成减仓？**
- **这次交易判断的反向证据和失效条件是什么？**

LLM 模式仍只用 `load_company_data`、`acquire_data`、`describe_ontology` 和 `sparql_query`，
由模型自己查询 1.10 的新类；没有把判断硬编码成 LLM 工具。

## 10. 校验结果

```text
triples: 47,958
classes: 363
object properties: 317
data properties: 494
SKOS concepts: 225
SWRL rules: 169
OWL-S services: 3
ODRL policies: 7
```

`scripts/validate.py`、`pytest` 与页面快照均在本版本更新；校验脚本仍只做 OWL RL 闭包与结构检查，
不声明 OWL 2 DL 完整一致性。

## 11. 仍然不是交易系统

1.10 仍然是**决策支持本体**，不是行情终端、账户管理系统或交易系统：

- 市场、板块、个股、量价、竞价、事件、判断、行为与验证数据都是合成示例；
- 胜率依据是示例样本库，不是可实盘复现的回测结果；
- 风险收益门槛、风险偏好门槛与行为优先级是演示常量，生产环境应外置为可版本化参数；
- `BehaviorRule` 只表达条件，不自动下单；`OrderIntent` 仍需人工批准；
- OWL-S 端点和 WSDL 操作名是示意；ODRL 政策是声明式约束，校验脚本不执行政策决策；
- OWL 2 DL 一致性、SWRL 执行和真实数据接入仍需要外部工程实现。

扩展原则不变：先有业务含义、能力问题、数据源和约束，再增加节点；不以节点数作为验收标准。
