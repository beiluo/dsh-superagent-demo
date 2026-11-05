# A 股投资决策本体 — 设计说明

> 版本：1.11.0 · 设计日期：2026-11 · 规范源：`ontology/**/*.ttl`

本文说明本体“为什么这样建模”、每层使用了哪些 W3C 构造、跨层链路如何工作，以及当前实现的边界。
1.1、1.9、1.10 与 1.11 的领域清单分别见 [expansion-1.1.md](expansion-1.1.md)、
[expansion-1.9.md](expansion-1.9.md)、[expansion-1.10.md](expansion-1.10.md) 与
[expansion-1.11.md](expansion-1.11.md)。
自然语言标签与定义在 Turtle 中；本文是设计说明，不是本体的替代物。

---

## 0. 目标与非目标

### 目标

1. 用 **RDF** 表达 A 股投资决策相关的公司、证券、行情、财报、风险、决策、组合与证据实例。
2. 用 **RDFS/OWL 2** 定义稳定的领域词汇、层次、domain/range、基数与身份约束。
3. 用 **SKOS** 管理行业、主题、风格三套可独立演进的分类方案。
4. 用 **SWRL** 表达可执行的筛选、风险、止损、集中度与合规规则。
5. 用 **OWL-S** 描述一个可解释、可调用、需要人工批准的决策服务。
6. 用 **ODRL 2.2** 表达数据使用、决策报告消费与订单意图执行的政策。
7. 提供一个无需后端、可检索、可分层浏览的静态页面。
8. 让每个判断都能回溯到：数据 → 证据 → 规则 → 服务 → 政策 → 人工复核。

### 非目标

- 不做实时行情接入、交易执行或账户管理；
- 不做完整 OWL 2 DL 一致性证明或 SWRL 推理引擎；
- 不提供真实投资建议、评级或目标价；
- 不复刻官方行业分类，也不复用 FIBO 本体文本；
- 不把 ODRL 政策等同于法律合同或访问控制的实际执行。

---

## 1. 需求与能力问题

### 1.1 核心能力问题

| 编号 | 能力问题 | 对应构造 |
| --- | --- | --- |
| CQ01 | 哪些公司同时满足高 ROE、低 PE、正利润且非 ST？ | SWRL R01、`FinancialReport`、`Valuation` |
| CQ02 | 哪些公司的资产负债率过高且利息保障倍数不足？ | SWRL R02、`debtRatio`、`interestCoverage` |
| CQ03 | 当前决策的建议、目标价、止损价和风险等级是什么？ | `InvestmentDecision`、`Recommendation`、`RiskAssessment` |
| CQ04 | 某项决策引用了哪些证据、理由和政策？ | `basedOn`、`hasRationale`、`governedBy` |
| CQ05 | 哪些持仓权重超过组合的单票集中度上限？ | SWRL R06、`Position`、`positionWeight` |
| CQ06 | 某项决策服务需要哪些输入、输出和前置条件？ | OWL-S Profile / Process |
| CQ07 | 哪些 ODRL 政策禁止将决策报告分发给非合格投资者？ | ODRL Prohibition、Constraint |
| CQ08 | 各行业一级概念下有哪些子概念？ | SKOS `broader` / `narrower` |
| CQ09 | 哪些 SWRL 规则处于 active 状态，责任人是谁？ | `RuleArtifact` 元数据 |
| CQ10 | 哪些投资决策缺少风险评估，需要完整性修复？ | OWL 限制 + SPARQL `FILTER NOT EXISTS` |

完整 SPARQL 见 [`docs/competency-questions.rq`](competency-questions.rq)。

### 1.2 验收标准

- 7 个 Turtle 模块可以被独立解析，聚合入口能声明全部 imports；
- 每个类和属性具备中文/英文标签与自然语言定义；
- 每条决策示例具备标的、建议、理由、风险、证据、服务、政策、合规检查与期限；
- 每条 SWRL 规则变量安全、引用已定义术语、body/head 非空；
- OWL-S 服务有 profile、process、grounding，且步骤可枚举；
- 每条 ODRL 政策有 uid、profile、规则和约束；
- 页面可以检索、过滤、查看详情，并在手机端无横向溢出；
- 校验脚本返回 0，页面无 JavaScript 运行时错误。

---

## 2. FIBO 参考了什么

FIBO（Financial Industry Business Ontology）由 EDM Council 维护，采用模块化领域本体、
OWL 2、规范化标签与定义，并强调可追溯、可复用与可演进。它把金融领域拆成多个模块
（例如 Foundations、Business Entities、Financial Business and Commerce、Securities、
Indices and Indicators、Market Data 等），每个模块有自己的 IRI、版本和依赖关系。

本项目借鉴的是**方法**，不是术语：

| FIBO 做法 | 本项目的对应 |
| --- | --- |
| 按领域边界分模块 | 七层各一个 Turtle 文件，聚合入口统一 imports |
| 稳定的规范 IRI | `https://beiluo.github.io/dsh-superagent-demo/ontology/a-share#` |
| 定义优先，标签完整 | 每个类/属性都有中英标签和 `rdfs:comment` |
| OWL 2 表达结构约束 | 限制、基数、属性特征、键、不相交 |
| SKOS 管理分类 | 行业、主题、风格三套 ConceptScheme |
| 元数据与版本 | `owl:versionInfo`、`owl:versionIRI`、规则/政策版本 |
| 可追溯 | 决策绑定证据、规则、服务、政策与合规检查 |

**未复用** FIBO 的类、IRI、文本或本体文件。“FIBO-inspired”只描述设计方法；本项目不是
FIBO 的官方扩展，也不受 FIBO 治理机构背书。

---

## 3. 总体架构

```text
                         ┌──────────────────────────────┐
                         │  ontology/a-share.ttl        │
                         │  aggregate owl:Ontology      │
                         │  owl:imports × 7 modules     │
                         └──────────────┬───────────────┘
                                        │
        ┌───────────────┬───────────────┼───────────────┬────────────────┐
        │               │               │               │                │
   ┌────▼─────┐   ┌─────▼──────┐   ┌────▼─────┐   ┌─────▼──────┐   ┌─────▼──────┐
   │ RDFS     │   │ OWL 2      │   │ SKOS     │   │ SWRL       │   │ OWL-S      │
   │ schema   │◄──│ axioms     │   │ taxonomy │   │ rules      │   │ service    │
   └────┬─────┘   └─────┬──────┘   └────┬─────┘   └─────┬──────┘   └─────┬──────┘
        │               │               │               │                │
        └───────────────┴───────┬───────┴───────────────┴────────────────┘
                                │
                         ┌──────▼───────┐        ┌──────────────────┐
                         │ RDF instances│        │ ODRL policies    │
                         │ companies…   │        │ data / decision  │
                         └──────────────┘        │ / trade guard    │
                                                 └──────────────────┘
```

依赖方向：

- `rdfs` 定义词汇；
- `owl` 导入 `rdfs`，增加公理；
- `skos` 独立定义分类，不依赖 OWL 类；
- `rdf` 使用 `rdfs`/`skos` 的术语，提供实例；
- `swrl` 导入 `owl`，规则引用词汇与实例属性；
- `owl-s` 导入 `owl` 与 OWL-S 1.2 本体，服务引用领域类；
- `odrl` 导入 `owl` 与 ODRL 2.2 本体，政策引用资产、参与方与决策。

---

## 4. IRI、命名空间与版本

### 4.1 命名空间

| 前缀 | IRI | 用途 |
| --- | --- | --- |
| `ash:` | `https://beiluo.github.io/dsh-superagent-demo/ontology/a-share#` | 类与属性 |
| `ashd:` | `...#/data#` | 实例、服务、规则、政策、参与方 |
| `ashs:` | `...#/skos#` | SKOS 概念与方案 |
| 聚合本体 | `...#/a-share` | 版本与 imports |

> 命名空间使用项目预期的 GitHub Pages 基址。当前仓库中的 Turtle 文件是规范源；
> 页面与文件可以在本地或任意静态托管上提供。部署到该基址后即可获得可解引用 IRI。

### 4.2 模块 IRI

```text
.../a-share/rdf
.../a-share/rdfs
.../a-share/owl
.../a-share/skos
.../a-share/swrl
.../a-share/owl-s
.../a-share/odrl
```

每个模块都声明 `owl:Ontology` 与 `owl:versionInfo "1.11.0"`；聚合入口声明
`owl:versionIRI .../a-share/1.11.0`。

### 4.3 版本策略

- **major**：删除/重命名公共 IRI、改变类或属性语义、改变规则后件含义；
- **minor**：新增类、属性、规则、政策、概念；保持既有语义兼容；
- **patch**：仅标签、注释、示例、页面或校验脚本修正。

规则与政策各自有 `ash:ruleVersion` / `ash:policyVersion`、`ash:ruleOwner`、
`ash:reviewDate`，与本体版本解耦，便于单独审计。

---

## 5. RDF 层：实例图

文件：`ontology/rdf/instances.ttl`（25,176 条三元组）

### 5.1 表达方式

使用 Turtle 1.1 的 IRI、前缀、字面量、语言标签、数据类型与 RDF collection。
实例图包括：

- 交易所与板块：SSE、SZSE、BSE；主板、创业板、科创板、北交所；
- 上市公司与 A 股证券；
- 年度财务报告；
- 行情快照与估值快照；
- 宏观指标；
- 证据、数据源、公告；
- 风险因子与风险评估；
- 投资者画像、策略、组合与持仓；
- 投资决策、理由、合规检查、公司事件。

### 5.2 示例决策链

```text
ashd:decision-huachen-2026q4
  a ash:InvestmentDecision ;
  ash:decisionId "DEC-2026-HC-001" ;
  ash:aboutSecurity ashd:sec-huachen-a ;
  ash:hasRecommendation ashd:rec-buy ;
  ash:hasRationale ashd:rationale-huachen ;
  ash:hasRiskAssessment ashd:risk-huachen ;
  ash:basedOn ashd:evidence-huachen-report, ashd:evidence-huachen-quote ;
  ash:generatedBy ashd:svc-ashare-decision ;
  ash:governedBy ashd:policy-decision-use, ashd:policy-research-data ;
  ash:hasComplianceCheck ashd:check-huachen ;
  ash:decidedFor ashd:profile-balanced ;
  ash:hasHorizon ashd:horizon-medium ;
  ash:decisionDate "2026-10-31"^^xsd:date ;
  ash:validUntil "2026-12-31"^^xsd:date .
```

这不是一个“结论表”，而是一张可遍历的决策证据图。

### 5.3 数据真实性

所有实例均为**合成示例**：

- 公司、证券代码、价格、财务数据、公告、政策、决策均为演示；
- 不对应真实证券，不构成投资建议；
- 页面和 README 均标注这一点。

---

## 6. RDFS 层：词汇与定义

文件：`ontology/rdfs/schema.ttl`（4,165 条三元组）

### 6.1 类层次

顶层类：

```text
ash:Entity
├── ash:MarketParticipant
│   ├── ash:ListedCompany
│   ├── ash:Investor
│   │   └── ash:QualifiedInvestor
│   ├── ash:ServiceProvider
│   │   └── ash:DataProvider
│   └── ash:Regulator
├── ash:FinancialInstrument
│   ├── ash:Security
│   │   └── ash:Stock
│   │       └── ash:AShare
│   └── ash:Index
├── ash:MarketStructure
│   ├── ash:Exchange
│   └── ash:MarketSegment
├── ash:InformationObject
│   ├── ash:FinancialReport → AnnualReport / InterimReport
│   ├── ash:MarketQuote
│   ├── ash:Valuation
│   ├── ash:MacroIndicator
│   ├── ash:CorporateEvent → DividendEvent / RegulatoryEvent
│   ├── ash:Disclosure / ResearchReport / NewsItem / Evidence
│   └── ash:Signal → RiskSignal / OpportunitySignal
├── ash:DecisionObject
│   ├── ash:InvestmentDecision
│   ├── ash:DecisionRationale
│   ├── ash:Recommendation
│   ├── ash:InvestmentHorizon
│   ├── ash:Portfolio / Position
│   ├── ash:InvestmentStrategy
│   ├── ash:InvestorProfile
│   ├── ash:ComplianceCheck
│   └── ash:AuditRecord
└── ash:Risk
    └── Market / Credit / Liquidity / Operational /
        Compliance / Concentration / Model / ESG
```

此外有规则推断类（`ValueCandidate`、`HighFinancialRisk`、`ConcentrationBreach`、
`AuditableDecision` 等）以及 `AssessmentResult`、`DecisionService`、`DecisionPolicy`、
`RuleArtifact`、`DataSource`、`CompetencyQuestion` 等支撑类。

### 6.2 属性

- 317 个对象属性；
- 494 个数据属性；
- 每个属性有 `rdfs:domain`、`rdfs:range` 和中英文标签；
- 典型属性：
  - `ash:hasSecurity` / `ash:issuedBy`；
  - `ash:primaryIndustry` / `ash:hasThemeExposure`；
  - `ash:hasFinancialReport` / `ash:hasMarketQuote` / `ash:hasValuation`；
  - `ash:aboutSecurity` / `ash:hasRecommendation` / `ash:hasRationale` / `ash:basedOn`；
  - `ash:hasRiskAssessment` / `ash:hasRiskFactor` / `ash:hasRiskLevel`；
  - `ash:holdsPosition` / `ash:positionIn` / `ash:positionWeight`；
  - `ash:generatedBy` / `ash:governedBy` / `ash:hasComplianceCheck`；
  - 1.1 扩展：`ash:tracksIndex` / `ash:underlyingAsset` / `ash:orderFor` / `ash:approvedBy` /
    `ash:hasShareholder` / `ash:hasFactorExposure` / `ash:hasAnalystEstimate`。

### 6.3 RDFS 语义

RDFS 推断主要依赖：

- `rdfs:subClassOf`：公司、证券、风险类型、决策对象层次；
- `rdfs:subPropertyOf`（少量）；
- `rdfs:domain` / `rdfs:range`：数据与关系的基本类型约束；
- `rdfs:label` / `rdfs:comment`：人类可读标签与定义。

`domain`/`range` 在 RDFS 中是推断规则，不是“拒绝写入”的约束；真正的结构约束在 OWL 层，
运行时的输入校验还需要 SHACL 或应用层 schema。

> 说明：RDFS 层用 `owl:Class` / `owl:ObjectProperty` / `owl:DatatypeProperty` 声明类与属性，
> 目的是让 OWL 层可以无 punning 地叠加。纯 RDFS 消费者仍只依赖 `rdfs:subClassOf`、
> `rdfs:subPropertyOf`、`rdfs:domain` 和 `rdfs:range`；这组公理在 RDFS 语义下同样成立。

---

## 7. OWL 2 层：公理与结构约束

文件：`ontology/owl/ontology.ttl`（1,089 条三元组）

### 7.1 类限制

223 条 `owl:Restriction`，代表性约束：

| 类 | 约束 |
| --- | --- |
| `ListedCompany` | `hasSecurity some Security`；`primaryIndustry min 1 skos:Concept` |
| `AShare` | `tradesOn exactly 1 MarketSegment` |
| `Security` | `listedOn exactly 1 Exchange` |
| `FinancialReport` | `reportsOn some ListedCompany`；`reportPeriod exactly 1` |
| `MarketQuote` | `quoteOf some Security`；`lastPrice exactly 1`；`dataAsOf exactly 1` |
| `Valuation` | `valuationOf some Security`；`peTtm exactly 1` |
| `InvestmentDecision` | `aboutSecurity min 1 Security`；`hasRecommendation exactly 1`；`hasRationale exactly 1`；`hasRiskAssessment exactly 1`；`decidedFor exactly 1`；`hasHorizon exactly 1`；`governedBy min 1 DecisionPolicy`；`hasComplianceCheck min 1` |
| `DecisionRationale` | `rationaleText exactly 1`；`hasEvidence min 1` |
| `RiskAssessment` | `assessesSecurity exactly 1`；`riskScore exactly 1`；`hasRiskLevel exactly 1` |
| `Portfolio` | `followsStrategy exactly 1`；`hasBenchmark max 1` |
| `Position` | `positionIn exactly 1`；`positionWeight exactly 1`；`avgCost exactly 1` |
| `InvestorProfile` | `riskTolerance exactly 1`；`maxSingleWeight exactly 1` |
| `Recommendation` | `actionCode exactly 1` |
| `ComplianceCheck` | `checksDecision exactly 1`；`passed exactly 1` |
| `Fund` | `managedBy exactly 1 FundCompany`；`fundCode exactly 1`；`hasFundFee min 1` |
| `ETF` | `tracksIndex exactly 1 Index` |
| `ConvertibleBond` | `underlyingAsset exactly 1 AShare`；`conversionPremium exactly 1` |
| `Order` | `orderFor exactly 1 Security`；`placedBy exactly 1 Investor`；订单字段各 1 |
| `Approval` | `approves exactly 1 InvestmentDecision`；`approvedBy exactly 1 MarketParticipant` |

### 7.2 属性特征与逆属性

- `FunctionalProperty`：`decisionId`、`confidence`、`targetPrice`、`stopLoss`、
  `riskScore`、`positionWeight`、`peTtm`、`reportPeriod` 等；
- `TransitiveProperty`：`hasParentCompany`、`hasSubsidiary`；
- `SymmetricProperty`：`relatedParty`；
- 逆属性：`hasSecurity`/`issuedBy`、`listedOn`/`lists`、`hasFinancialReport`/`reportsOn`、
  `hasMarketQuote`/`quoteOf`、`hasValuation`/`valuationOf`、`hasRiskAssessment`/`assessesDecision`、
  `holdsPosition`/`positionOf` 等。

### 7.3 键与身份

`owl:hasKey`：

- `ListedCompany`：`companyCode`；
- `Security`：`securityCode` + `listedOn`；
- `Exchange`：`exchangeCode`；
- `FinancialReport`：`reportsOn` + `reportPeriod`；
- `MarketQuote`：`quoteOf` + `dataAsOf`；
- `Valuation`：`valuationOf` + `dataAsOf`；
- `InvestmentDecision`：`decisionId`。

键在本体中表达身份判断；是否在运行时强制唯一性，仍取决于数据平台与写入流程。

### 7.4 不相交

20 组 `owl:AllDisjointClasses`：

- 市场参与者子类；
- `Security` / `Index`；
- 信息对象子类；
- 决策对象子类；
- 风险子类；
- `Exchange` / `MarketSegment`。

这些公理帮助发现“同一实例被错误地放进互斥类别”的建模问题。

### 7.5 一致性边界

本仓库运行 OWL RL 闭包测试，不运行 OWL 2 DL 完整 reasoner。原因：

- Java 运行时不在本仓库依赖中；
- SWRL 规则不属于 OWL 2 DL 本体，需要独立规则引擎；
- 生产环境可按需接入 HermiT、ELK、Pellet 或商业 reasoner。

因此 README 与本文只声明“按 OWL 2 结构构造并进行 OWL RL 闭包测试”，不声明完整 DL 证明。

---

## 8. SKOS 层：二十二套概念方案

文件：`ontology/skos/taxonomy.ttl`（1,979 条三元组）

### 8.1 方案

| 方案 | 概念数 | 用途 |
| --- | --- | --- |
| `ashs:scheme-industry` | 44 | 一级行业 + 二级行业 |
| `ashs:scheme-theme` | 10 | 跨行业投资主题 |
| `ashs:scheme-style` | 6 | 价值/成长/红利/质量/动量/低波 |
| `ashs:scheme-asset-class` | 21 | A 股、ETF/LOF、债券、衍生品、REITs、现金等资产类别 |
| `ashs:scheme-factor` | 12 | 价值、成长、质量、动量、低波、红利、规模、盈利等因子 |
| `ashs:scheme-trading-playbook` | 20 | 首板、连板、反包、低吸、退潮、政策/业绩/并购催化等短线剧本 |
| `ashs:scheme-emotion-cycle` | 6 | 启动、发酵、高潮、结束、反复、冰点 |
| `ashs:scheme-seat-style` | 8 | 营业部/机构、一日游/波段/锁仓/加码/做T/通道 |
| `ashs:scheme-skill-topic` | 20 | 龙虎榜、打板、低吸、接力、情绪、竞价、复盘、风控等技能主题 |
| `ashs:scheme-decision-stage` | 8 | 账户快照、风险预算、买卖点、仓位、约束、执行、复盘、规则迭代 |
| `ashs:scheme-position-status` | 5 | 持有、加仓、减仓、已平仓、冻结 |
| `ashs:scheme-sizing-method` | 4 | 固定比例、ATR、等权、凯利上限 |
| `ashs:scheme-review-verdict` | 5 | 过程正确、过程待改进、规则需修订、结果含运气/体现能力 |
| `ashs:scheme-decision-level` | 4 | 战略配置、战术配置、交易执行、复盘迭代 |
| `ashs:scheme-opportunity-stage` | 4 | 启动、确认、延续、衰退 |
| `ashs:scheme-judgment-scenario` | 2 | 非持仓、已持仓 |
| `ashs:scheme-judgment-decision` | 6 | 买入、持有、加仓、减仓、卖出、观望 |
| `ashs:scheme-volume-price-pattern` | 13 | 8 种量价行为 + 1 个组合父概念 + 4 个组合序列 |
| `ashs:scheme-auction-behavior` | 8 | 高开、低开、抢筹、衰退、弱转强、强转弱、封单增强、封单衰减 |
| `ashs:scheme-intraday-behavior` | 8 | 主动拉升、冲高回落、回踩承接、横盘换手、突破加速、跌破失守、尾盘抢筹、尾盘兑现 |
| `ashs:scheme-behavior-action` | 7 | 建仓、加仓、持有、减仓、止盈、止损、观望 |
| `ashs:scheme-verification-result` | 4 | 逻辑成立、逻辑减弱、逻辑失效、待验证 |

合计 225 个概念。

### 8.2 构造

- `skos:ConceptScheme`、`skos:hasTopConcept`、`skos:topConceptOf`；
- `skos:prefLabel`（中/英）、`skos:altLabel`、`skos:notation`；
- `skos:definition`、`skos:scopeNote`、`skos:note`；
- `skos:broader` / `skos:narrower`（双向声明，便于独立遍历）；
- `skos:related`（跨行业/主题关联）；
- `skos:inScheme`。

### 8.3 为什么不把行业建成 OWL 类

行业分类是“对公司的分类判断”，不是公司存在的前提条件；分类标准也会调整。把行业建成 OWL 类会导致：

- 分类调整引发类层次变更；
- 外部标准对齐困难；
- 多分类/多标准并存时产生类爆炸；
- 公司实例的类型不稳定。

用 SKOS 后，`ash:primaryIndustry` 的 range 是 `skos:Concept`，分类可独立版本化。需要强约束时，
可在 SHACL 中检查“概念必须属于某个 scheme”。

### 8.4 分类不是官方标准

行业结构参考公开行业分类的常见层级，但**不是**申万、证监会或任何官方分类的完整复刻。
生产使用应替换为获得授权的分类标准，并保留来源与版本。

---

## 9. SWRL 层：规则

文件：`ontology/swrl/rules.ttl`（13,379 条三元组）

### 9.1 语法选择

使用 SWRL 的 RDF 具体语法：

- `swrl:Imp`：规则；
- `swrl:body` / `swrl:head`：RDF list；
- `swrl:ClassAtom` / `swrl:IndividualPropertyAtom` / `swrl:DatavaluedPropertyAtom`；
- `swrl:BuiltinAtom` + `swrlb:`；
- `swrl:Variable`。

SWRL 规范同时定义了抽象语法与 XML 具体语法；本仓库采用 RDF 具体语法，以便与 OWL 图合并。
每条规则同时带 `ash:RuleArtifact` 元数据：编号、严重程度、优先级、状态、版本、责任人、生效日、
适用类和读取属性。

同一文件还包含规则库 V2.0 的 60 条 `ash:DecisionRule` 规范规则。它们不是 `swrl:Imp`，不自动执行；
每条规则带类别、适用范围、前置条件、输入、观测、触发/反向/否决证据、状态机路径、后续动作、
失效机制、参数占位、典型场景、反例、验证方法和置信度依据。它们与 SWRL 规则共享
`ash:RuleArtifact` 身份和同一套分类/状态/证据/输出契约，详见 [expansion-1.11.md](expansion-1.11.md)。

### 9.2 规则清单

| 编号 | 规则 | 前件摘要 | 后件 | 严重程度 |
| --- | --- | --- | --- | --- |
| R01 | 价值候选筛选 | 公司有年报、证券有估值；ROE ≥ 15、PE ≤ 20、净利润 > 0、非 ST | `ValueCandidate` | medium |
| R02 | 高财务风险识别 | 资产负债率 ≥ 70、利息保障倍数 < 2 | `HighFinancialRisk` | high |
| R03 | ST 股票池排除 | `isST = true` | `ExcludedFromUniverse` | high |
| R04 | 退市风险排除 | `delistingRisk = true` | `ExcludedFromUniverse` | high |
| R05 | 持仓止损触发 | 持仓成本 × 0.8 ≥ 最新价 | `StopLossTriggered` | high |
| R06 | 单票集中度超限 | 任一持仓权重 > 0.10 | `ConcentrationBreach` | high |
| R07 | 限制名单合规复核 | 决策标的 `isRestricted = true` | `RequiresComplianceReview` | high |
| R08 | 可审计决策完整性 | 有风险评价、理由、证据、政策 | `AuditableDecision` | medium |
| R09 | 低流动性证券识别 | 换手率 < 0.5%、总市值 < 50 亿元 | `IlliquidSecurity` | high |
| R10 | 成长候选筛选 | 营收增速 ≥ 25%、利润增速 ≥ 20%、PE > 40 | `GrowthCandidate` | medium |
| R11 | 高风险买入二次复核 | `actionCode = BUY` 且 `riskScore ≥ 60` | `RequiresSecondReview` | high |
| R12 | ETF 跟踪误差超限 | 基金份额 `trackingError > 2.0` | `TrackingErrorBreach` | medium |
| R13 | 可转债高溢价 | `conversionPremium > 30.0` | `ConvertibleRich` | medium |
| R14 | 未审批订单阻断 | `orderStatus = PENDING` | `TradeBlocked` | high |
| R15 | 基金净流出风险 | `netFlowPct < -5.0` | `FundOutflowRisk` | high |
| R16 | 游资席位净买入 | 龙虎榜净买 > 5000 万且存在 hot-money 席位 | `HotMoneyInflow` | medium |
| R17 | 连板动量 | 连板 ≥ 3、炸板 ≤ 1、封单 > 5000 万 | `MomentumSignal` | medium |
| R18 | 短线过热 | 换手率 > 15% 且连板 ≥ 3 | `OverheatRisk` | high |
| R19 | 炸板风险 | 连板期间炸板 ≥ 2 次 | `BoardBreakRisk` | high |
| R20 | 中期趋势向上 | MA20 > MA60 且营收增速 ≥ 20% | `MediumTermTrend` | medium |
| R21 | 主题催化信号 | 主题热度 > 80 且存在新闻催化 | `EventDrivenSignal` | medium |
| R22 | 竞价弱转强 | 预期溢价 < 0、实际溢价 > 0、竞价额 > 500 万 | `WeakToStrong` | medium |
| R23 | 龙虎榜混合共识 | 净买 > 5000 万且游资/机构混合 | `HotMoneyInflow` | medium |
| R24 | 情绪冰点 | 高度 ≤ 2 且亏钱效应 > 赚钱效应 | `EmotionFreeze` | high |
| R25 | 一日游风险 | 游资席位一日游比例 > 60% | `OneDayTripRisk` | high |
| R26 | 回撤超限 | 交易日志最大回撤 > 10% | `DrawdownBreach` | high |

### 9.2.1 1.7 规则扩展（R27–R76）

1.7 从 50 个技能页与原话中继续提炼了 50 条短周期规则，按类别组织：

| 类别 | 规则 | 代表判断 |
| --- | --- | --- |
| 市场环境 | R27–R32 | 趋势分数、市场宽度、成交额决定进攻/防守/空仓 |
| 情绪周期 | R33–R37 | 炸板率、主题升温/降温判断高潮、退潮 |
| 题材与龙头 | R35–R39, R65–R66 | 主题排名、龙头高度、扩散度确认主线 |
| 竞价 | R40–R43 | 竞价溢价、跳空、量比判断强/弱承接 |
| 打板/低吸/反包/接力/突破 | R42–R51, R56 | 封单、换手、量比、断板、买一强势 |
| 龙虎榜/游资 | R52–R56 | 净买、一日游比例、买一卖一 |
| 趋势/基本面 | R57–R61 | 均线、营收增速、业绩超预期、新闻催化 |
| 监管/仓位/执行/复盘 | R62–R76 | 监管风险、仓位、单笔风险、执行偏离、回撤、连续亏损 |

规则仍是开放世界 Horn 规则，不自动下单；阈值是示例，生产需外置参数版本。

### 9.3 规则边界

SWRL 基于开放世界与一阶 Horn 逻辑，本项目刻意不表达：

- **否定即失败**：无法从“没有风险评估”推出“决策不合规”；该问题用 SPARQL
  `FILTER NOT EXISTS` 做完整性检查。
- **聚合**：SWRL 不做组合权重求和、行业权重汇总；这些在组合引擎中完成。
- **时间窗口**：规则只比较当前快照，不做“连续 5 日跌破”等时间序列判断。
- **冲突消解**：R06 与 R07 同时命中时，由外部合规流程决定处理顺序；ODRL 政策提供冲突策略，
  但 SWRL 不内建优先级。
- **阈值治理**：当前阈值是示例常量；生产应外置为参数图，并记录参数版本。

这些边界不是缺陷，而是为了让规则保持可验证、可解释、可审计。

---

## 10. OWL-S 层：服务

文件：`ontology/owl-s/service.ttl`（895 条三元组）

### 10.1 三个视角

| OWL-S 视角 | 本项目的表达 |
| --- | --- |
| Profile | 服务名称、描述、分类、输入、输出、前置条件、类别 |
| Process Model | 3 个 `CompositeProcess`：决策服务 7 步，生命周期服务 8 步，交易认知服务 7 步 |
| Grounding | 3 个 `WsdlGrounding`，共 22 个 `WsdlAtomicProcessGrounding` + WSDL 操作名 |

### 10.2 七步流程

```text
01 数据接入与质量校验
02 因子与估值计算
03 风险与流动性评估
04 SWRL 规则推理
05 组合与约束优化
06 合规与适当性检查
07 决策报告生成
```

- 输入：证券池、投资者画像、决策基准日、市场数据包、组合与合规约束；
- 输出：投资决策、风险评估、决策理由、订单意图（不是订单）；
- 前置条件：数据新鲜度、投资者适当性、ODRL 政策有效、证券不在限制名单；
- 人工批准：`ash:humanApprovalRequired true`，服务不直接连接交易通道；
- Grounding：WSDL 文档、服务、端口、操作名均为示意，不指向生产系统。

### 10.2.1 生命周期服务（1.9）

`svc-trade-lifecycle` 把账户与风控纳入服务契约：

```text
01 账户与持仓快照 → 02 风险预算检查 → 03 买卖点与触发条件 → 04 仓位测算
→ 05 约束与审批 → 06 订单意图 → 07 执行与复盘 → 08 规则迭代
```

输入为账户与持仓状态、组合风险预算、行情/风险快照和交易政策；输出为交易计划、订单意图、
执行质量、交易后复盘和规则修订。前置条件新增“风险预算使用率低于 100%、单笔风险不超过
riskPerTradeLimit、预计单票权重不超过 maxSingleNameWeight”。

### 10.2.2 交易认知服务（1.10）

`svc-trading-cognition` 把五引擎判断体系写成服务契约：

```text
01 市场认知 → 02 个股认知 → 03 事件认知 → 04 机会识别
→ 05 交易判断 → 06 行为管理 → 07 结果验证
```

输入为认知标的、行情/风险快照、账户与持仓状态和交易政策；输出为市场认知、个股认知、
事件认知、机会评估、交易判断、行为规则和结果验证。前置条件新增“反向证据逐条审查、判断包含
失效条件、非持仓与已持仓使用不同流程、判断版本变化记录触发证据”。

### 10.3 规范状态

OWL-S 1.2 是 W3C Member Submission（2004-11-22），不是 W3C Recommendation。本仓库显式记录
这一点，并在页面与 README 中标注。生产实现可选择更现代的 OpenAPI/AsyncAPI 描述，同时保留
OWL-S 作为语义服务契约。

---

## 11. ODRL 层：政策

文件：`ontology/odrl/policies.ttl`（607 条三元组）

### 11.1 政策清单

| 政策 | 类型 | 目标 | 核心规则 |
| --- | --- | --- | --- |
| `policy-research-data` | `odrl:Set` | 行情与财务数据包 | 允许 read/derive/aggregate；约束 purpose=research、spatial=CN、dateTime<2027-01-01、count≤12；义务 attribute/delete；禁止 distribute/commercialize |
| `policy-decision-use` | `odrl:Agreement` | 投资决策报告 | 允许 read/use/reproduce；约束 purpose、recipient isA QualifiedInvestor、dateTime；义务 inform/obtainConsent/attribute；禁止分发给非合格投资者；补救 reviewPolicy |
| `policy-trade-guard` | `odrl:Set` | 订单意图 | 允许 execute 当且仅当 humanApproval=true 且 compliancePassed=true；禁止 humanApproval=false 的执行；义务 inform/reviewPolicy |
| `policy-ai-analysis` | `odrl:Agreement` | AI 辅助分析 | 允许 read/use/reproduce；约束 purpose、recipient isA QualifiedInvestor；禁止绕过人工审批执行订单；义务 attribute/reviewPolicy |
| `policy-hot-money-data` | `odrl:Set` | 龙虎榜/游资数据 | 允许 read/derive；约束 purpose/recipient；禁止自动执行订单；义务 attribute/reviewPolicy |
| `policy-trade-lifecycle` | `odrl:Agreement` | 风险预算、交易计划、复盘 | 允许 read/use/derive；约束预算使用率 < 100%；禁止未审批或预算超限时执行；义务标注来源并完成复盘 |
| `policy-trading-cognition` | `odrl:Agreement` | 交易判断、机会评估、结果验证 | 允许用于投资决策支持；禁止反向证据未审查、市场风险偏好过低或未人工批准时执行；义务标注来源并完成结果验证 |

### 11.2 关键构造

- `odrl:Policy` 子类 `odrl:Set` / `odrl:Agreement`；
- `odrl:uid`、`odrl:profile`、`odrl:conflict odrl:prohibit`；
- `odrl:permission` / `odrl:prohibition` / `odrl:obligation`；
- `odrl:action`、`odrl:target`、`odrl:assigner`、`odrl:assignee`；
- `odrl:constraint` + `odrl:leftOperand` / `odrl:operator` / `odrl:rightOperand`；
- `odrl:duty`、`odrl:consequence`、`odrl:remedy`；
- `odrl:hasPolicy` 关联资产。

### 11.3 Profile 扩展

`humanApproval` 与 `compliancePassed` 不是 ODRL Core 的左操作数。本仓库在
`ashd:odrl-profile` 中显式声明：

```turtle
ashd:leftOperand-humanApproval a odrl:LeftOperand ;
    skos:prefLabel "人工批准状态"@zh, "human approval"@en .
```

这是 ODRL 允许的 profile 扩展方式。它们不是“私有字段”，而是有 IRI、有定义的扩展术语。

### 11.4 执行边界

ODRL 政策是**声明式**的。本仓库：

- 检查政策结构；
- 在页面展示权限/禁止/义务；
- 在决策上通过 `ash:governedBy` 建立引用；
- **不**实现 ODRL evaluator、访问控制或自动阻止交易。

生产环境应把政策接入 API gateway、数据访问层、订单前置校验与审计系统。

---

## 12. 跨层决策走查

以 `ashd:decision-huachen-2026q4` 为例：

1. **RDF**：华辰智造、A 股证券、2025 年报、2026-10-30 行情/估值、风险评价、理由、证据。
2. **RDFS**：这些实例使用 `ListedCompany`、`AShare`、`AnnualReport`、`InvestmentDecision` 等词汇。
3. **OWL**：决策恰好有一个建议、一个理由、一个风险评价、至少一个标的、至少一个合规检查；
   证券恰好上市于一个交易所；公司至少有一个行业概念。
4. **SKOS**：公司 `primaryIndustry` 指向“高端制造”，并关联“人工智能”“低空经济”等主题。
5. **SWRL**：
   - R01 推断公司为 `ValueCandidate`（ROE 18.2、PE 19.8、净利润正、非 ST）；
   - R06 推断组合 `ConcentrationBreach`（华辰持仓权重 12% > 10%）；
   - R08 推断决策 `AuditableDecision`（有风险评价、理由、证据、政策）。
6. **OWL-S**：决策由 `svc-ashare-decision` 生成；服务 profile 声明输入输出，process 声明七步流程，
   grounding 声明示意 WSDL 操作。
7. **ODRL**：决策受 `policy-decision-use` 与 `policy-research-data` 约束；报告只向合格投资者提供，
   数据用于研究目的，订单意图必须人工批准。
8. **页面**：从实体搜索到详情、从证据链到政策，所有引用都可点击/追溯。

这条链就是“可审计决策”与“一个建议字段”的区别。

---

## 13. 决策生命周期（1.9）

1.9 把“决策”拆成可推理的层级，而不是只增加一个建议字段：

1. **账户与持仓状态**：`Account`、`AccountState`、`PositionState`、`PositionLot`、`CashMovement`
   记录现金、购买力、可卖数量、成本、浮盈亏与资金流水；
2. **组合风险预算**：`RiskBudget`、`RiskBudgetAllocation`、`RiskLimit`、`RiskUtilization`、
   `PortfolioRiskSnapshot`、`RiskContribution` 记录总风险资本、单笔/单票/行业/回撤/VaR 限额；
3. **买卖点与仓位联动**：`TradePlan` → `EntryPlan`/`ExitPlan`、`PriceLevel`、`TradeTrigger`、
   `hasTradeSizing`、`PositionSizing`、`OrderIntent` 把买点、止损、目标、数量、预计权重与风险金额写进同一计划；
4. **执行到复盘闭环**：`ExecutionQuality`、`DecisionOutcome`、`PostTradeReview`、`ReviewFinding`、
   `LessonLearned`、`PerformanceAttribution`、`RuleRevision` 把成交、结果、发现、经验与规则修订回写。

`DecisionCycle` 串起上述阶段；`DecisionContext` 固定决策时点的账户、预算、风险和市场状态。
新增 OWL-S 服务 `svc-trade-lifecycle` 以八步流程表达生命周期，原有 `svc-ashare-decision` 仍是
“从数据到投资决策”的七步服务。新增 ODRL 政策 `policy-trade-lifecycle` 把风险预算、人工批准
和复盘义务写成可检查约束。详见 [expansion-1.9.md](expansion-1.9.md)。

### 13.1 交易认知扩展（1.10）

1.10 回应“为什么值得买、买入后什么情况下继续持有或卖出的判断体系”问题，新增五引擎认知层：

1. **市场认知**：`MarketCognition`、`SectorCognition` 记录市场趋势、广度、情绪、流动性、
   风险偏好、短线生态与板块趋势/资金/扩散/龙头/题材持续性；
2. **个股认知**：`StockCognition` 组合趋势阶段、价格结构、`VolumePriceBehavior`、
   `AuctionBehavior` 与 `IntradayBehavior`；
3. **事件认知**：`EventCognition` 判断事件真实性、业务相关性、是否已反映、板块共振与价格确认；
4. **机会评估**：`OpportunityAssessment` 汇总支持证据、反向证据、机会阶段与
   `RiskRewardAssessment`，不做加权评分；
5. **交易判断**：`TradingJudgment` 按 `non_position`/`held` 两套流程形成结论，配套
   `BehaviorRule`、`JudgmentRevision` 与 `OutcomeVerification`。

`AnalysisCase` 把五个引擎串成一个可追溯案例；新增 OWL-S 服务 `svc-trading-cognition`
（七步：市场认知 → 个股认知 → 事件认知 → 机会识别 → 交易判断 → 行为管理 → 结果验证）与
ODRL 政策 `policy-trading-cognition`。Agent 新增 `evaluate_cognition`，与
`evaluate_trade` 分工：前者判断机会与持仓逻辑，后者检查计划能否执行。详见
[expansion-1.10.md](expansion-1.10.md)。

### 13.2 规则库 V2.0（1.11）

1.11 把 Issue #25 的 60 条 A 股规则库 V2.0 编码进本体，不把它们做成加权评分器：

1. **职责分层**：`RuleCategory` 与 8 个 `DecisionRule` 子类表达 OP/VP/AUC/MKT/EVT/POS/RSK/EVA
   的职责、顺序与越权边界；60 条规则通过 `belongsToRuleCategory` 归入类别。
2. **统一状态机**：`RuleState`、`RuleStateMachine`、`RuleStateTransition` 定义 9 个状态与
   允许迁移；`RuleStateChange` 记录实际迁移的时间戳、触发证据、反向证据和数据版本。
3. **输出契约**：`RuleOutput` / `RuleRun` 要求至少输出 rule_id、security_id、as_of、timeframe、
   position_state、state、触发/支持/反向/缺失证据、参数版本、有效期、后续动作与置信度依据。
4. **证据与数据质量**：`RuleEvidence` 的触发/支持/反向/缺失子类，加上 7 条
   `DataQualityConvention`，覆盖价格、成交、时间、横截面、缺失、事件去重与幸存者偏差。
5. **参数占位**：每条规则有 `RuleParameter`，保存待回测的初始参数、参数版本和分层校准说明；
   参数状态为 `initial`，不是已证明有效的最优值。
6. **规则关系与调用顺序**：`ruleNextRule`、`ruleRelatedRule` 和 6 类 `RuleRelation`
   表达前置、支持、冲突、否决、后续与评估关系；SWRL 仍是可执行子集，规范规则不会自动下单。

示例运行 `rule-run-op-001-20261105` 展示 CANDIDATE 输出，`rule-run-rsk-007-20261105`
展示交易制度字段缺失时的 DATA_INSUFFICIENT 边界。详见 [expansion-1.11.md](expansion-1.11.md)。

## 14. 校验与测试

### 14.1 结构校验

`scripts/validate.py` 使用 `rdflib` 与 `owlrl`：

- 解析 7 个 Turtle 文件；
- 检查聚合入口 imports 与 `dcterms:conformsTo`；
- 检查类/属性的中文标签、domain/range；
- 检查 OWL 限制、key、AllDisjointClasses 引用；
- 检查 SKOS 方案、顶层概念、broader/narrower 互逆；
- 检查 SWRL 规则 body/head、变量安全、内建支持；
- 检查 OWL-S profile/process/grounding 结构；
- 检查 ODRL 政策 uid/profile/规则/约束；
- 检查示例决策字段完整性；
- 解析 28 条 SPARQL 查询；
- 运行 OWL RL 闭包。

### 14.2 当前结果

```text
modules: 7
triples: 52810
classes: 389
object properties: 349
data properties: 554
SKOS concepts: 225
SWRL rules: 169
decision rules (V2.0): 60
OWL-S services: 3
ODRL policies: 7
OWL RL closure: 37929 -> 80057 triples (42128 inferred)
warnings: 0
```

### 14.3 页面测试

使用 Firefox + Playwright 做冒烟检查：

- 页面标题与数据快照加载；
- 4,375 个实体、229 条规则（169 条 SWRL + 60 条 V2.0）、22 个流程步骤、7 项政策渲染；
- 搜索 `InvestmentDecision` 返回 1 条；
- 点击实体详情显示 8 条 OWL 限制；
- 规则严重程度/规则库筛选、政策 tab、概念树、示例 tab 交互正常；
- 短线面板：6 个 KPI、4 步剧本、3 张方法论卡、情绪六阶段、R16–R26 规则、游资科技短线决策；
- 技能目录：50 个技能、821 个章节、20 个主题、1,327 条短原话可在 Explorer 检索；
- 图谱四种模式：核心全景 51 节点、全部类 389 节点、决策链 47 节点/带标签边、SKOS 225 节点；
- 图谱缩放、图例隐藏/恢复、节点聚焦、跳转 Explorer/SKOS 均正常；
- 桌面与 390px 手机视口无横向滚动、无 console error；
- 截图见 `docs/evidence/`。

### 14.4 未覆盖

- OWL 2 DL 完整一致性；
- SWRL 规则执行与冲突消解；
- ODRL 政策执行；
- 数据接入、清洗、时效性；
- 真实交易/合规流程。

---

## 15. 页面实现

### 15.1 数据流

```text
Turtle modules
   │ rdflib
   ▼
scripts/build_data.py
   ├── assets/js/data.js        （window.ASH_DATA）
   └── assets/data/ontology.json
          │
          ▼
index.html + assets/js/app.js
```

页面不直接解析 Turtle，避免在浏览器引入大型 RDF 解析器；Turtle 仍是唯一规范源。

### 15.2 信息架构

1. Agent 对话区：服务端工具循环或规则模式，回答附带本体证据；
2. Ontology Explorer（默认首屏）：搜索、类型筛选、来源层筛选、实体详情；技能目录与原话摘录也在同一检索与详情中呈现；
3. 整体本体图谱：核心全景、全部类、决策链、SKOS 分类；
4. SKOS 概念树 + 概念详情；
5. 规则库（SWRL + 规则库 V2.0）：严重程度/关键词筛选与规则详情。

页面导航只保留 Agent、浏览、图谱、分类与规则五个入口；短线、OWL-S、ODRL、示例与方法不再单独成页，相关服务与政策实体仍可在 Ontology Explorer 中检索和查看。

### 15.3 图谱实现

图谱使用原生 SVG 与自实现力导向布局，不引入 D3 或图表库：

- **核心全景**：51 个核心类节点，保证可读性；虚线为 `rdfs:subClassOf`，实线为对象属性关系；按 7 个领域簇着色；
- **全部类**：389 个类节点，用于查看完整扩展域；
- **决策链**：19 个核心类的手工布局，边标签显示对象属性，适合讲解决策路径；
- **SKOS 分类**：225 个概念，按二十二套 ConceptScheme 着色，边为 `broader`；
- **交互**：滚轮缩放、拖拽平移、图例筛选、节点聚焦、`标签`开关；点击节点在右侧显示类/概念详情；
- **联动**：详情中的“在 Explorer 中打开”跳转到实体浏览器；“在 SKOS 分类中查看”跳转到概念树；
- **响应式**：移动端默认展示 19 节点的决策链，仍可切换到 51 节点核心全景、389 节点全部类并缩放查看；
- **规模评估**：图谱下方固定展示类/属性/概念/三元组规模，并明确“参考实现而非 FIBO 级行业本体”。

图谱节点与边全部来自 `DATA.classes`、`DATA.objectProperties`、`DATA.concepts`，没有手工维护的第二份图数据。

### 15.4 可访问性与响应式

- 跳至主要内容链接、可见焦点、语义化按钮/aria 标签；
- 详情面板在手机端为全屏抽屉，Esc 关闭；
- 尊重 `prefers-reduced-motion`；
- 表格在小屏可横向滚动；
- 页面无外部字体/CDN 依赖。

### 15.5 Agent 层（服务端）

Agent 是页面之外的独立服务端，避免把 LLM key 放进静态产物：

- **前端**：`assets/js/agent.js` 只调用公开的 `POST /api/agent/analyze`；`agent-config.js`
  只保存公开的 `apiBase`，不含任何密钥。
- **本体访问**：`server/ontology.py` 用 rdflib 读取 `ontology/**/*.ttl`，构建公司、证券、财报、
  行情估值、风险、决策、证据、合规、组合与政策的紧凑事实；不依赖浏览器快照。
- **规则**：`server/rules.py` 对 R01—R11 做确定性评估；阈值与 `ontology/swrl/rules.ttl` 的示例常量
  一致，`tests/test_rules.py` 直接从 SWRL body 提取字面量校验。
- **工具循环**：LLM 模式只暴露 `load_company_data`、`describe_ontology`、`sparql_query` 三项能力；
  `server/tools.py` 的其余固定分析工具只在规则回退模式使用。LLM 只能看到能力结果，不能访问环境变量。
- **问题驱动的查询**：`server/query.py` 把规则模式问题中的业务条件翻译成属性路径，支持跨公司筛选、
  证据链遍历、组合/ODRL 约束检查和 what-if 规则重算；每次调用返回 `queryPath`，前端据此
  展示实际路径，而不是固定报表流程。
- **开放查询层**：`server/sparql.py` 让 Agent 自己生成只读 SPARQL。`load_company_data` 只负责
  把真实 A 股事实加载进运行时图，不返回分析；`describe_ontology` 提供类、属性、前缀和示例查询；
  `sparql_query` 执行 `SELECT`/`ASK`，拒绝更新、`CONSTRUCT`/`DESCRIBE`、`SERVICE` 与 `FROM`，
  并限制查询长度、返回行数和字面量大小。LLM 可以多轮“生成→执行→修正”；固定分析工具不在
  LLM 的工具面中，调用会返回 `tool_not_available`。
- **回退**：没有 `LLM_API_KEY` 或上游失败时，`server/agent.py` 用固定工具生成确定性 Markdown，
  页面明确显示“规则模式”，不会把上游错误或密钥返回浏览器。
- **边界控制**：CORS 白名单、每 IP 分钟/小时限流、每日额度、请求体上限、并发上限、静态文件白名单；
  静态服务只挂载 `assets/`、`ontology/`、`docs/` 与 `index.html`，不暴露 `.env`、`server/` 或 `.git`。

### 15.6 Agent 驱动的本体查询与规则模式回退

单股问答很容易退化成固定报表；本版本把 LLM 的“用本体”改为由模型自己生成查询，固定工具只保留
在确定性回退路径：

- **自由图查询**：`load_company_data` 加载真实事实后，`describe_ontology` 返回类/属性/前缀与示例，
  `sparql_query` 执行 Agent 生成的只读查询；覆盖任意关系、聚合、路径和否定条件，例如
  “哪些决策缺少风险评估”“每家公司分别有几条证据”。规则也从 `ash:RuleArtifact` 读取后对照事实，
  不依赖预计算的固定报表。
- **规则模式跨公司筛选**：`query_ontology` 接收字段/运算符/阈值，映射到
  `hasFinancialReport→roe`、`hasSecurity→hasValuation→peTtm` 等属性路径，叠加行业与 SWRL 规则条件；
  筛选结果保留每条命中的属性路径。`universe=real` 用真实 A 股行情单页样本做横截面筛选，
  只覆盖行情/估值字段，不伪装成年报级全市场扫描。
- **规则模式证据链**：`trace_evidence` 从公司/决策/规则/政策沿 `aboutCompany`、`basedOn`、`governedBy`、
  `hasRiskAssessment`、`hasSource` 等显式谓词遍历，输出节点、边、数据日期、来源和版本；反向遍历
  只用于 `aboutCompany` 等逆关系，避免通过共享政策把其他决策混进同一证据链。
- **规则模式组合与政策约束**：`check_constraints` 读取 R06/R07/R11 阈值与 ODRL trade-guard 约束，
  对拟议权重、人工批准、合规检查逐项给出通过/未通过/待确认状态。
- **规则模式 what-if**：`simulate_scenario` 在内存事实副本上修改指标并重跑确定性规则，对比前后状态；
  不写回 Turtle，也不声称是预测。
- **查询路径**：每次能力结果带 `queryPath`，`AgentResult.queryPath` 汇总事实加载、图式读取、SPARQL
  步骤；前端“本体查询路径”面板直接展示，包括 Agent 生成的查询。规则模式同样返回固定工具的步骤。

这些是原型：真实筛选只读取行情单页样本；ODRL 检查只覆盖政策中已显式建模的上下文约束；
证据链不推断未建模的因果关系。LLM 模式的查询是只读的，不能做 what-if 重算；情景问题只说明假设
与规则阈值，确定性 what-if 与固定约束检查仍由规则模式的工具完成。

部署、密钥轮换与 GitHub Pages 接入见 [`agent.md`](agent.md)。

---

## 16. 治理、版本与变更流程

### 16.1 变更类型

| 变更 | 要求 |
| --- | --- |
| 新增类/属性 | 增加中英标签、定义、domain/range；更新校验阈值；重建页面 |
| 修改规则后件 | 视为 major；需规则责任人、复核记录、示例回归 |
| 调整阈值 | 记录参数版本、影响分析、回测/合规评审 |
| 新增政策 | 定义 uid/profile、规则、约束、复核日期、负责人 |
| 调整分类 | 更新 SKOS 方案版本；检查引用概念的公司/决策 |
| 修改页面 | 重建数据、跑浏览器冒烟、更新截图 |

### 16.2 审计字段

- 本体：`owl:versionInfo`、`owl:versionIRI`、`dcterms:created/modified`；
- 规则：`ruleId`、`ruleVersion`、`ruleOwner`、`ruleStatus`、`ruleEffectiveFrom`；
- 政策：`policyVersion`、`policyStatus`、`reviewDate`；
- 决策：`decisionId`、`decisionDate`、`validUntil`、`generatedBy`、`hasComplianceCheck`。

### 16.3 生产化建议

1. 用 SHACL 增加写入时数据质量约束；
2. 用 OWL 2 DL reasoner 做本体一致性回归；
3. 用 SWRL/Drools 或规则引擎执行规则，并记录推理轨迹；
4. 用 ODRL evaluator 接入数据访问与订单前置检查；
5. 用版本化图数据库/三元组存储保存历史快照；
6. 对规则阈值做参数化、回测与审批；
7. 对决策报告做人工复核与留痕。

---

## 17. 已知限制

1. 没有完整 OWL 2 DL 一致性证明；OWL RL 闭包不等价于 DL 一致性。
2. 没有内置 SWRL 引擎；规则可读、可校验，但不在本仓库执行。
3. OWL-S grounding 是示意端点，不是可调用服务。
4. ODRL 政策是声明，不执行访问控制。
5. 示例数据、阈值、评级、目标价均为合成，不构成投资建议。
6. 行业分类是演示结构，不是官方分类。
7. 决策示例中的 `confidence`、`targetPrice`、`stopLoss` 仅用于展示字段绑定，不是模型输出。
8. 页面是静态快照；修改 Turtle 后必须重建数据。

---

## 18. 参考资料

### W3C

- RDF 1.1 Concepts and Abstract Syntax — <https://www.w3.org/TR/rdf11-concepts/>
- RDF 1.1 Turtle — <https://www.w3.org/TR/turtle/>
- RDF Schema 1.1 — <https://www.w3.org/TR/rdf-schema/>
- OWL 2 Overview — <https://www.w3.org/TR/owl2-overview/>
- OWL 2 Structural Specification — <https://www.w3.org/TR/owl2-syntax/>
- OWL 2 Mapping to RDF Graphs — <https://www.w3.org/TR/owl2-mapping-to-rdf/>
- SKOS Reference — <https://www.w3.org/TR/skos-reference/>
- SKOS Primer — <https://www.w3.org/TR/skos-primer/>
- SWRL: A Semantic Web Rule Language — <https://www.w3.org/Submission/SWRL/>
- OWL-S: Semantic Markup for Web Services — <https://www.w3.org/Submission/OWL-S/>
- OWL-S 1.2 Overview — <https://www.daml.org/services/owl-s/1.2/overview/>
- ODRL Information Model 2.2 — <https://www.w3.org/TR/odrl-model/>
- ODRL Vocabulary and Expression 2.2 — <https://www.w3.org/TR/odrl-vocab/>

### FIBO

- EDM Council FIBO — <https://spec.edmcouncil.org/fibo/>
- OMG EDMC-FIBO — <https://www.omg.org/spec/EDMC-FIBO/>

### 工具

- RDFLib — <https://rdflib.readthedocs.io/>
- OWL-RL — <https://github.com/RDFLib/OWL-RL>
- Playwright — <https://playwright.dev/>
