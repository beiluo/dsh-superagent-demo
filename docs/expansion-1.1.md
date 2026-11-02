# 1.1 领域扩展说明

> 版本：1.1.0 · 对应分支：`agent/expand-a-share-ontology-a9c9d9ebdae6`

这次扩展直接回应“本体内容太少”的反馈。它不是给现有图加孤立节点，而是按 A 股投研/交易链补齐
**工具、公司行为、财务深度、因子/风险、交易与审批** 等缺口，并把新增内容接入 OWL、SKOS、SWRL、
ODRL、页面图谱与校验。

## 1. 扩展前后

| 指标 | 1.0 | 1.1 | 增量 |
| --- | ---: | ---: | ---: |
| 三元组 | 4,290 | 6,253 | +1,963 |
| 类 | 72 | 136 | +64 |
| 对象属性 | 46 | 90 | +44 |
| 数据属性 | 75 | 125 | +50 |
| 个体验证数据 | 76 | 100 | +24 |
| SKOS 概念 | 52 | 93 | +41 |
| SWRL 规则 | 11 | 15 | +4 |
| ODRL 政策 | 3 | 4 | +1 |
| 可浏览实体 | 336 | 564 | +228 |

## 2. 新增领域

### 2.1 基金、ETF 与资产类别

- `Fund`、`FundShare`、`ETF`、`LOF`、`ClosedEndedFund`、`MoneyMarketFund`、`BondFund`、`EquityFund`；
- 基金管理公司/基金经理/费用/资金流；
- 新增 `scheme-asset-class`：A 股、主板、创业板、科创板、北交所、ETF、LOF、公募/私募、货币/债券/股票基金、
  可转债、国债、信用债、回购、股指期货、商品期货、股票期权、REITs、现金。

### 2.2 固定收益与可转债

- `Bond` → `GovernmentBond` / `CorporateBond` / `ConvertibleBond`；
- `BondRating`、`BondCovenant`、`YieldCurve`；
- 票面利率、到期日、到期收益率、信用评级、转股溢价率、可转债标的。

### 2.3 衍生品

- `Derivative` → `FuturesContract` / `OptionContract`；
- `IndexFuture` / `CommodityFuture` / `StockOption`；
- 合约规格、保证金要求、合约乘数、行权价、到期日。

### 2.4 交易与市场微观结构

- `TradingCalendar` / `TradingSession` / `OrderBook` / `LimitState`；
- `Order` / `Trade` / `ExecutionReport` / `MarginAccount`；
- 订单方向、数量、价格、状态、成交价、成交数量、结算日、交易成本。

### 2.5 公司行为与股权

- `Shareholder` / `ControllingShareholder` / `OwnershipStructure`；
- `RelatedPartyTransaction` / `ShareRepurchase` / `EquityOffering` / `MergerAcquisition` / `LockupRelease`；
- 关联交易、回购金额、融资规模、解禁日期。

### 2.6 财务深度与研究预期

- `StatementLineItem` / `SegmentReport`；
- `AnalystEstimate` / `ConsensusEstimate` / `RatingAction`；
- 报表科目、分部名称、预测值、分析师目标价、评级代码。

### 2.7 因子、风险与组合

- `Factor` / `FactorExposure` / `RiskModel` / `ModelVersion`；
- `PortfolioConstraint` / `Backtest` / `TradeCost`；
- 新增 `scheme-factor`：价值、成长、质量、动量、低波、红利、规模、盈利、波动率、流动性、杠杆、估值。

### 2.8 ESG、数据治理与审批

- `ESGRating` / `ControversyEvent`；
- `DataLineage` / `ModelVersion` / `Approval`；
- 审批状态、数据版本、模型版本、ESG 分数。

## 3. 新增规则

| 编号 | 规则 | 前件 | 后件 |
| --- | --- | --- | --- |
| R12 | ETF 跟踪误差超限 | `trackingError > 2.0` | `TrackingErrorBreach` |
| R13 | 可转债高溢价 | `conversionPremium > 30.0` | `ConvertibleRich` |
| R14 | 未审批订单阻断 | `orderStatus = PENDING` | `TradeBlocked` |
| R15 | 基金净流出风险 | `netFlowPct < -5.0` | `FundOutflowRisk` |

新增示例数据会触发这些规则：ETF 跟踪误差 2.8、可转债溢价 34%、订单 PENDING、基金净流出 -6.2%。
SWRL 仍保持单调、无副作用；真实执行需要外部规则引擎。

## 4. 新增 ODRL 政策

`policy-ai-analysis`：AI 辅助分析仅用于投资研究，只向合格投资者提供；必须标注本体来源；
禁止绕过人工审批执行订单；合规官必须复核审计记录。该政策与现有数据/决策/订单三项政策共同构成
四层政策边界。

## 5. 页面与图谱

- 实体浏览器：564 个可浏览实体；
- 核心全景：51 个核心类 / 82 条关系（默认可读）；
- 全部类：136 个类 / 202 条关系；
- 决策链：19 个类 / 15 条带标签对象属性边；
- SKOS：93 个概念 / 5 个方案；
- 新增基金、债券、可转债、订单等实例，可在 Explorer 中检索。

## 6. 校验

```text
A-share ontology validation passed.
modules: 7
triples: 6253
classes: 136
object properties: 90
data properties: 125
SKOS concepts: 93
SWRL rules: 15
ODRL policies: 4
OWL RL closure: 4598 -> 12503 triples (7905 inferred)
warnings: 0
```

`make test`：43 passed（Agent 规则目录断言已改为兼容新增规则/政策）。

## 7. 仍然不是 FIBO 级

1.1 扩展把 A 股决策骨架做厚，但仍不是 FIBO 级行业本体。下一步优先级：

1. 真实数据源与授权分类标准对齐；
2. 完整三张报表科目、分部与分析师预期；
3. 组合优化、压力测试、回测与交易成本模型；
4. 订单生命周期、执行算法与合规审批；
5. 多市场（港股通、北交所）与跨境产品。

扩展原则仍然是：先有业务含义、能力问题、数据源和约束，再增加节点；不以节点数作为验收标准。
