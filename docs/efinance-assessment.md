# efinance 接入评估：能补哪些 A 股数据，是否直接引入

> 评估日期：2026-11-04 · 对象：[`Micro-sheep/efinance`](https://github.com/Micro-sheep/efinance)
> v0.5.9（commit `c8fd370`，2026-07-17）· 对照：`server/marketdata.py`（本体 1.2）

**结论：数据面值得借鉴，运行时库不建议直接引入。** efinance 是东方财富公开接口的便利封装，
不是新的持牌数据源；它能把可获取的 A 股数据从“行情 / 估值 / 年报”扩展到“五档快照、资金流、
龙虎榜、板块、股东、季度业绩、指数成分、逐笔”等，但直接装进 FastAPI 会带来已验证的部署阻塞、
超时与口径风险。建议**取其接口配方，用现有 `httpx` 适配器重写**；efinance 仅作为研究/离线工具。

---

## 0. 先给结论

| 问题 | 结论 |
| --- | --- |
| 是否更全面？ | **是。** 新增 10 类以上 A 股数据，覆盖短线、资金、股东、横截面业绩等现有适配器没有的维度。 |
| 是否更快？ | **有条件。** 批量行情/全市场横截面显著更快；单股重复查询不如现有 TTL 缓存。 |
| 是否新的数据源？ | **否。** 与现有适配器同源，都是东方财富公开网页接口；不解决授权、限流和 SLA。 |
| 是否直接接入？ | **不建议。** 非 root 容器导入失败、pandas/numpy 体积、180 秒超时、无缓存、口径不一致等。 |
| 最值得先接什么？ | `sealAmount`（解锁 R17）、龙虎榜净买、资金流、板块、批量行情。 |
| 仍解决不了什么？ | 龙虎榜席位明细、新闻催化、完整三张报表、持牌数据授权。 |
| 推荐路线 | **方案 B + C**：把 5 个高价值接口吸收进现有适配器；efinance 只放进研究用可选依赖。 |

---

## 1. 研究对象与方法

### 1.1 版本与维护状态

| 项目 | 值 |
| --- | --- |
| 版本 | `efinance==0.5.9` |
| 最新提交 | `c8fd370a3109b2d14a121e3a32a86e9c8354b01b`（2026-07-17，修复搜索接口） |
| 许可证 | MIT（代码）；README 同时声明“仅供学习交流，不得用于商业用途” |
| GitHub | 4,125 stars / 761 forks / 152 open issues |
| 测试 | **仓库没有自动化测试**，只有 4 个示例 notebook |
| 维护节奏 | 小规模个人维护，2024–2026 年间断更新；接口变更靠 issue 反馈 |

版本较新，但“有维护”不等于“有 SLA”。它没有测试套件，东方财富接口一变，回归只能靠用户发现。

### 1.2 代码结构

```text
efinance/
├── stock/     # 16 个公开函数，1,537 行
├── fund/      # 17 个公开函数，939 行
├── bond/      # 10 个公开函数，413 行
├── futures/   # 4 个公开函数，231 行
├── common/    # 行情/K 线/资金流/基础信息的共用 getter
├── shared/    # requests session、搜索缓存、TickFlow 错误提示
├── config/    # 包内缓存目录、连接数
└── utils/     # 搜索、代码转换、DataFrame 数值化
```

`stock` 的公开能力包括：基础信息、实时行情（全市场/多股）、日/周/月/分钟 K 线、五档快照、
历史与当日资金流、十大流通股东、报告期列表、全市场季度业绩、股东户数、龙虎榜、指数成分、
IPO 审核、成交明细、所属板块。

### 1.3 依赖与运行方式

安装 `efinance==0.5.9` 会带入：

```text
requests, tqdm, pandas, retry, multitasking, jsonpath, rich, beautifulsoup4
```

本次实测环境（Python 3.12.3）解析到 `pandas 3.1.0`、`numpy 2.5.4`；`efinance` 本身约 580 KB，
但包含依赖的虚拟环境约 **133 MB**（pandas 55 MB、numpy 33 MB）。冷启动 `import efinance`
约 **0.43 秒**，进程峰值 RSS 约 **81 MB**（含 pandas）。

efinance 没有上界约束 pandas，安装当天就会拿到 pandas 3.x；核心函数能跑，但会输出
`Pandas4Warning`（`inplace`、`to_datetime` 等弃用项）。这对一个长期运行的服务是额外的不确定性。

### 1.4 实测方法

```bash
git clone --depth 1 https://github.com/Micro-sheep/efinance /tmp/efinance-study
uv venv /tmp/efinance-venv --python 3.12
uv pip install --python /tmp/efinance-venv/bin/python efinance==0.5.9 httpx

# 逐函数计时、记录行数/列名/异常
/tmp/efinance-venv/bin/python /tmp/probe_efinance.py

# 现有适配器同口径对照：600519 的行情、估值、年报、短线
/tmp/efinance-venv/bin/python /tmp/probe_current.py
```

采样标的：贵州茅台 `600519`（主板、年报完整）、宁德时代 `300750`、五粮液 `000858`；
横截面使用 `get_all_company_performance()` 返回的 5,574 只股票。

**环境限制：** 本机对东方财富 `push2.eastmoney.com/api/qt/clist/get` 返回 301/空响应，
现有适配器的 `screen()` 与 efinance 的 `get_realtime_quotes()` 都失败。因此“全市场行情”
一项只能确认**接口存在、代码路径完整**，不能确认本次网络下可用；其余函数均实测成功。
另外，采样时没有遇到正在涨停的股票，封单金额公式做了字段级验证，未做盘中涨停的端到端验证。

---

## 2. 数据覆盖对照

图例：✅ 已有/可用；◐ 部分；❌ 没有。

| 数据集 | 现有 `marketdata.py` | efinance | 本体/运行时 | 判断 |
| --- | --- | --- | --- | --- |
| 单股实时行情 | ✅ 价格、涨跌幅、成交量、换手、市值、PE/PB | ✅ 同上 + 量比、成交额、流通市值、五档 | `MarketQuote` | 可补字段 |
| 五档盘口/涨跌停价/均价 | ❌ | ✅ `get_quote_snapshot` | `MarketQuote` + `LimitUpStreak` | **高价值** |
| 全市场行情 | ◐ `screen()` 单页 ≤200，仅行情/估值 | ◐ 代码支持约 5,500 行；本环境 clist 失败 | `screen` / 横截面 | 待复测 |
| 日 K | ✅ 最近 80 日 | ✅ 全历史、前/后复权 | `ma5/20/60` | 低（已有） |
| 周/月/分钟 K | ❌ | ✅ 1/5/15/30/60 分钟、周、月 | 未映射 | 研究 |
| 历史/当日资金流 | ❌ | ✅ 日级 + 分钟级 | `FundFlow` 类已存在，运行时未映射 | 中 |
| 龙虎榜 | ❌ | ✅ 聚合净买额、买卖额、上榜原因 | `DragonTigerList` | **高价值**（但不足 R16） |
| 所属板块/概念 | ❌ | ✅ 34 个板块（行业/概念/指数/风格） | SKOS 主题 | 中 |
| 十大流通股东 | ❌ | ✅ 最近 N 期 | `Shareholder` 类已存在 | 中（2.0c） |
| 股东户数 | ❌ | ✅ 全市场最新/指定报告期 | 股权域 | 中（2.0c，存在列错位） |
| 季度业绩（全市场） | ❌ | ✅ 5,574 行，营收/净利/EPS/ROE/毛利率 | `AnnualReport` 不能直接复用 | 中（2.0a，口径不同） |
| 年报 + 财务指标 | ✅ 营收/净利/ROE/ROA/负债率/利息保障/经营现金流 | ◐ 可查年报期业绩；无负债率/利息保障/完整现金流 | `AnnualReport` | **保留现有** |
| 指数成分/权重 | ❌ | ✅ `get_members` | 2.0d | 低 |
| IPO 审核状态 | ❌ | ✅ | 2.0f | 低 |
| 逐笔成交 | ❌ | ✅ 最近交易日明细 | 2.0d | 低 |
| 龙虎榜席位明细 | ❌ | ❌ 只有聚合，没有营业部 | ODRL 政策已提及 | **仍缺** |
| 新闻/公告催化 | ❌ | ❌ | 2.0f | **仍缺** |
| 基金/债券/期货 | ❌ | ✅ 净值、持仓、可转债、期货行情等 | 辅助资产 | 研究 |

**一句话：efinance 补的是“短线 + 资金 + 股东 + 横截面”，不是“财报深度”。** 现有适配器的
年报链路（`RPT_LICO_FN_CPD` + `RPT_F10_FINANCE_MAINFINADATA`）仍然不可替代；efinance 的
`get_all_company_performance()` 用的是同一族 `RPT_LICO_FN_CPD`，但取的是**季度累计**，
没有负债率、利息保障倍数和完整现金流。

---

## 3. 实测：覆盖、时延与失败模式

### 3.1 单函数结果

| 调用 | 结果 | 耗时 | 备注 |
| --- | --- | ---: | --- |
| `get_quote_snapshot('600519')` | 37 字段五档快照 | 0.20 s | 含涨停价、买一价/量 |
| `get_base_info('600519')` | 12 字段 | 0.22 s | PE 为“动态”，净利为当期累计 |
| `get_quote_history('600519', beg='20260101')` | 201 行 × 13 列 | 0.15 s | 前复权，日线 |
| `get_latest_quote(['600519','300750'])` | 2 行 × 20 列 | 0.17 s | 一次请求 |
| `get_latest_quote(50 只)` | 50 行 | 0.14 s | 一次请求，批量优势明显 |
| `get_history_bill('600519')` | 120 行 | 0.11 s | 日级资金流 |
| `get_today_bill('600519')` | 120 行 | 0.08 s | 分钟级资金流 |
| `get_belong_board('600519')` | 34 行 | 0.04 s | 行业/概念/指数/风格混在一起 |
| `get_top10_stock_holder_info('600519', 1)` | 10 行 | 1.27 s | 2 + N 次请求，无超时 |
| `get_daily_billboard()` | 89 行 | 0.51 s | 最近榜单日 |
| `get_members('000300')` | 300 行 | 0.34 s | 指数成分与权重 |
| `get_deal_detail('600519', 1000)` | 1,000 行 | 0.14 s | 逐笔 |
| `get_all_company_performance()` | **5,574 行** | 2.26 s | 全市场季度业绩 |
| `get_latest_holder_number()` | **5,578 行** | 1.09 s | 全市场股东户数 |
| `get_realtime_quotes()` | **失败** | 0.52 s | `push2 clist` 301/空响应（环境） |

### 3.2 与现有适配器的同口径对比

现有适配器 `fetch('600519')`：**5 次请求、0.97 秒**（冷启动）；第二次起命 TTL 缓存，**0 秒**。
单股 3 只冷启动约 1.89 秒；50 只按同一路径约 30 秒量级。

efinance 单股拆成多个函数时，冷启动合计约 1–2.7 秒，且**没有行情/财务缓存**；但它的批量
接口是另一个量级：50 只行情一次请求 0.14 秒。对“多股对比/横截面”场景，这是实打实的加速；
对“同一只股票反复分析”，现有缓存更快。

### 3.3 三个口径差异（600519，同一时刻）

| 字段 | 现有适配器 | efinance | 含义/风险 |
| --- | --- | --- | --- |
| 最新价 | 1471.87 | 1471.87 | 一致 |
| 成交量 | 3,230,200 股 | 32,302（手） | **单位差 100 倍** |
| PE | 22.39（TTM，f164） | 21.41（动态，f162/f9） | **不是同一口径，不能直接替换** |
| 净利润 | 823.20 亿（2025 年报） | 644.67 亿（2026 Q3 累计） | **报告期不同** |
| ROE | 32.53（2025 年报） | 24.47（2026 Q3 累计） | **报告期不同** |
| 行业 | 白酒Ⅱ | 白酒Ⅱ | 一致 |
| 总市值 | 1.83996 万亿 | 1.83996 万亿 | 一致 |

这组对比说明：efinance 的字段不是“同名字段可直接覆盖”，接入前必须做口径映射和字段命名
（例如把动态 PE 命名为 `peDynamic`，而不是塞进 `peTtm`）。

### 3.4 部署阻塞：非 root 容器导入失败（已验证）

Dockerfile 先以 root 安装依赖，再 `USER appuser`。efinance 在 **import 时**执行：

```python
DATA_DIR = HERE / "../data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
```

wheel 不包含 `efinance/data`，而 `site-packages` 属于 root、`appuser` 不可写。模拟只读
`site-packages` 后得到：

```text
PermissionError: [Errno 13] Permission denied: '.../efinance/config/../data'
```

这不是理论风险：按当前 Dockerfile 直接 `pip install efinance` 并启动，容器会在导入阶段失败。
需要在镜像里预建可写目录并 `chown`，或改包内缓存路径（上游 issue #204 仍未提供环境变量）。

### 3.5 全市场批量的失败模式

`get_latest_quote` 以 50 只为一组可以稳定返回；但把 5,574 只全部批量拉取时，前 2,000 只
约 6.5 秒完成，随后在某一组分片卡住（底层 session 超时 180 秒、带重试）。这说明：

- 批量接口能显著加速，但**不能无上限地扫全市场**；
- efinance 没有请求预算/超时参数，失败会拖住调用线程；
- 生产环境必须自己加并发上限、超时和熔断。

---

## 4. 能补什么：按对现有规则的价值排序

### 4.1 `sealAmount`：最直接的价值，解锁 R17

`get_quote_snapshot()` 提供 `涨停价`、`买1价`、`买1数量`（手）。当 `最新价 == 涨停价` 时：

```text
封单金额 = 买1数量（手） × 100 × 涨停价
```

这是当前适配器唯一能立刻补齐、且能改变规则结果的字段：

- `short_term.sealAmount` 现在恒为 `None`，R17 因此永远“无法评估”；
- 补上后，只要该股当前处于涨停，R17 的“连板天数 / 炸板次数 / 封单金额”三项就齐了；
- 非涨停时没有封单，建议写 `None` 而不是 `0`，否则 R17 会把“没有封单”误判成“封单为 0”，
  产生假的“未触发”；
- 历史封单无法从日 K 重建，只能覆盖“当前/最近快照”时点。R17 的语义需要明确为
  “截至快照时点”，不能假装是历史每日封单。

**结论：高价值、低风险，建议第一阶段做。**

### 4.2 龙虎榜净买：能补字段，但不能单独解锁 R16

`get_daily_billboard()` 返回 `龙虎榜净买额`、买卖额、上榜原因、解读等。两个关键问题：

1. **同一股票同一天可能有多条记录**（不同上榜原因），净买额不同。实测：
   - `000599`：+4,886 万（连续涨幅偏离）与 +2,574 万（日振幅）两条；
   - `002086`：+227 万（日涨幅偏离）与 −3,707 万（连续涨幅偏离）两条。
   直接求和或取第一条都会失真，必须定义“按原因去重/取主因/取最大绝对值”的规则并写进代码。
2. **R16 还要求游资席位数**（`hotMoneySeatCount`）。efinance 只有聚合净买，没有营业部席位明细，
   所以补上 `dragonTigerNetBuy` 后 R16 仍然会输出“缺少龙虎榜净买入或游资席位数据”。

**结论：中高价值。** 可用于展示和证据链，但要真正解锁 R16，必须另找席位数据，或调整 R16
的判定条件（这是产品/规则决策，不应由数据接入顺手改掉）。

### 4.3 资金流：新增能力，不是规则修复

`get_history_bill()` / `get_today_bill()` 提供主力、大单、超大单、中单、小单净流入。本体已有
`ash:FundFlow` 类，但运行时映射没有写入，现有 R01–R21 也没有规则直接使用它。接入它需要：

- 在 `server/ontology.py` 增加 FundFlow 事实映射；
- 明确“日级/分钟级、累计/单日、单位元/万元”的口径；
- 如果要参与决策，再新增规则或把资金流作为证据字段。

**结论：中价值，适合第二阶段；不要为了“字段更多”先塞进快照而不使用。**

### 4.4 板块/概念：能做主题暴露，但做不了主题热度

`get_belong_board()` 一次返回 34 个板块，包含行业（白酒Ⅱ/Ⅲ）、地域、指数、风格、概念
（茅指数、沪股通、融资融券、电商概念等）。这可以补 `hasThemeExposure`，但：

- 板块名是东方财富自己的分类，和本体的 SKOS 概念不是一一对应，需要别名/映射表；
- 没有“主题热度分数”“生命周期阶段”，所以 R21 仍然缺 `themeHeatScore` 和 `hasNewsCatalyst`；
- 34 个板块里很多是风格/指数标签，不是“主题”，直接全部映射会污染 SKOS。

**结论：中价值，先做“行业/概念候选列表”，不要自动创建概念。**

### 4.5 股东、季度业绩、指数成分、逐笔

这些数据真实存在且可获取，但对应的是本体 2.0a/2.0c/2.0d 的建模工作，不是当前 1.2 运行时的
一个小补丁：

- 十大股东：`get_top10_stock_holder_info` 返回“6.783 亿”“54.00%”这类字符串，需要解析中文单位；
- 股东户数：`get_latest_holder_number` 存在**列错位 bug**（见 6.4），issue #230 仍打开；
- 季度业绩：是累计季度口径，不能覆盖年报字段；适合做全市场横截面筛选，不适合直接替换 `AnnualReport`；
- 指数成分/逐笔：属于 2.0d 交易与市场微观结构，当前规则没有消费方。

**结论：中低优先级，等本体对应模块落地后再接。**

### 4.6 efinance 仍然给不了的

- **龙虎榜营业部/席位明细**（R16 的 `hotMoneySeatCount`）；
- **新闻、公告、催化剂**（R21 的 `hasNewsCatalyst`）；
- **完整三张报表**（资产/负债/权益/收入/成本/现金流科目）；
- **持牌数据、SLA、商业使用授权**；
- **历史封单、历史五档**（只有当前快照）。

---

## 5. 接入方式：四种选项

| 方案 | 做法 | 覆盖率 | 工作量 | 运行时风险 | 结论 |
| --- | --- | --- | --- | --- | --- |
| A. 直接引入库 | `requirements.txt` 加 `efinance`，写 `EfinanceProvider` | 高 | 低 | **高** | 不推荐 |
| B. 吸收接口 | 用现有 `httpx` 重写 5 个高价值接口 | 中高 | 中 | 低 | **推荐** |
| C. 研究工具 | 可选 `requirements-research.txt`，只在本地/notebook 用 | 高 | 低 | 无（不进服务） | **推荐并行** |
| D. 旁路服务 | 独立容器/CLI 用 efinance，输出规范化 JSON | 高 | 中高 | 中 | 后续按需 |

### 5.1 为什么不直接选 A

除了 3.4 的 Docker 导入失败，还有一组运行时问题：

- **超时不可控**：全局 session 默认 `timeout=180`；`get_quote_snapshot`、`get_top10_stock_holder_info`、
  `get_members` 等直接用 `requests.get/post`，**没有 timeout**，可能永久挂住 FastAPI worker；
- **无缓存**：只有搜索词缓存（3 天）和进程内基础信息缓存；行情、K 线、资金流每次都打网络。
  现有适配器的 60 秒/6 小时/5 分钟 TTL 缓存反而更适合服务端；
- **全局副作用**：import 时安装 `SIGINT` handler、替换 `sys.excepthook`、关闭 urllib3 警告、
  在 Python ≥3.10 把全局 TLS cipher 设为 `ALL:@SECLEVEL=1`；K 线请求还 `verify=False`。
  这些会改变整个 FastAPI 进程的安全/退出行为；
- **HTTP 与代理**：多个接口用 `http://push2.eastmoney.com`、`http://datacenter-web.eastmoney.com`，
  且 session 默认信任环境代理。部分 http 接口直连失败、走代理可成功（clist 在两种方式下都不通）；现有适配器统一 https +
  `trust_env=False`，行为更可控；
- **数据形态**：中文列名 DataFrame/Series，字段随函数变化；没有统一的 `source/quality/asOf`；
- **无测试**：上游没有测试套件，接口变更无法提前发现；
- **限流风险**：全市场分页用默认 `ThreadPoolExecutor` 并发，多股 K 线最多 50 并发；issue 中
  有大量“被限流/超时”反馈（#206、#208、#215、#229、#235）。在一个公开 Web 服务里放大请求量，
  比现在更容易被封。

### 5.2 推荐方案 B：吸收 5 个接口，不引入 pandas

保留现有 `MarketDataProvider` 接口和 `httpx` 错误/缓存/超时模式，按 efinance 的 endpoint
参数重写解析。建议的第一阶段范围：

1. **封单金额**：`hsmarketwg.eastmoney.com/api/SHSZQuoteSnapshot` → `sealAmount`；
2. **龙虎榜净买**：`datacenter-web.eastmoney.com/api/data/v1/get` + `RPT_DAILYBILLBOARD_DETAILS`
   → `dragonTigerNetBuy`（按日期+代码去重，规则写清楚）；
3. **资金流**：`push2his.eastmoney.com/api/qt/stock/fflow/daykline/get` → 近 N 日主力净流入；
4. **板块**：`push2.eastmoney.com/api/qt/slist/get` → 行业/概念候选列表；
5. **批量行情**：`push2.eastmoney.com/api/qt/ulist.np/get` → 多股对比时一次取回报价。

实现要点：

- 全部走 `https`，复用 `EastmoneyProvider._get_json` 的超时、`trust_env=False`、错误码；
- 复用现有 TTL 缓存（封单/资金流 5 分钟，龙虎榜 1 小时，板块 6 小时）；
- 新字段保持可选，缺失写 `None`，不要让规则把“缺失”当成“0”；
- 单测用固定 JSON fixture，不依赖真实网络；真实数据测试保持在 `test_real_data.py` 的可选路径；
- efinance 的 endpoint 参数可参考，但代码按本项目风格重写；如直接复制片段，保留 MIT 版权声明。

预计是一个**单模块、几百行以内**的改动，不需要动 `requirements.txt`，也不需要改 Dockerfile。

### 5.3 方案 C：efinance 作为研究工具

如果团队要做探索性分析（基金持仓、可转债、期货、逐笔、全市场季度业绩），可以增加：

```text
requirements-research.txt   # efinance==0.5.9, pandas<3
```

只在本地 notebook / 一次性脚本里使用，配独立 venv；不要 import 到 `server/`。这样既拿到
efinance 的广度，又不把它的全局状态、pandas 和 180 秒超时带进生产服务。

### 5.4 方案 D：旁路服务（后续）

如果第二阶段确实需要基金/债券/期货/逐笔，建议单独容器或 CLI：

- 自己的 venv/镜像，预建可写缓存目录；
- 设置请求超时、并发上限、重试与熔断；
- 输出规范化 JSON（字段名、单位、asOf、source、quality），再由主服务消费；
- 不让 efinance 与 FastAPI 共享进程。

这比“在 `server/` 里 import efinance”更容易治理，但多一个部署单元；当前阶段不必做。

---

## 6. 字段映射与口径陷阱

如果未来仍要写 `EfinanceProvider`，下面这些必须在代码里显式处理，不能靠“同名字段”直接复制。

### 6.1 单位

| efinance 字段 | 现有字段 | 转换 |
| --- | --- | --- |
| `成交量`（手） | `volume`（股） | × 100 |
| `成交额`（元） | 未映射 | 直接使用，注意浮点精度 |
| `总市值` / `流通市值`（元） | `marketCap`（元） | 直接使用 |
| `涨跌幅` / `换手率`（百分数） | `changePct` / `turnoverRate`（百分数） | 直接使用 |
| `买1数量`（手） | `sealAmount` | × 100 × 买1价 |

### 6.2 估值口径

- efinance `get_base_info` 的“市盈率(动)”= `f162`，`get_realtime_quotes` 的“动态市盈率”= `f9`；
- 现有适配器的 `peTtm` 用 `f164`（TTM），缺失才回退 `f162`；
- 两者对亏损/负 PE 的处理也不同。**不要把动态 PE 写进 `peTtm`**；要么新增 `peDynamic`，
  要么继续用现有 TTM 口径。

### 6.3 报告期

- efinance 的 `净利润`、`ROE`、`营业收入` 来自最近报告期（实测 2026 Q3 累计），不是年报；
- 现有 `AnnualReport` 的 `roe`、`netProfit` 是年报口径，R01/R20 等规则的阈值按年报设计；
- 混用会让“ROE 24.47%”被当成“2026 年报 ROE”，从而改变 R01 的触发结果。

### 6.4 股东户数列错位（上游已知问题）

实测 600519：

```text
股东人数       278364
股东人数增减   -6.086287634445      # 实际是“百分比”
较上期变化百分比 -18040.0           # 实际是“户数增减”
```

上游 issue #230 仍打开。接入前必须按原始字段（`HOLDER_NUM_RATIO` / `HOLDER_NUM_CHANGE`）
重新映射，不能直接用中文列名。

### 6.5 龙虎榜去重

同股同日多条原因、净买额不同（见 4.2）。建议：

- 以 `(trade_date, code)` 为键；
- 先按“主因”优先级（连续涨幅偏离 > 日涨幅偏离 > 振幅 > 换手 > 其他）选一条；
- 或保留多条明细，但在快照里只暴露 `primaryNetBuy` + `reason`，不要求和。

R16 的阈值 5,000 万直接比较单个数值；多条原因求和会改变语义，需要产品/规则负责人确认。

### 6.6 板块分类

34 个板块混合了行业、地域、指数、风格、概念。映射到 SKOS 时至少要有：

- 白名单/类型过滤（只取行业、概念；排除指数/风格/地域）；
- 别名表（“白酒Ⅱ” → `ashs:industry-baijiu` 等）；
- 人工复核，不自动创建概念。

### 6.7 快照/时间

- `get_quote_snapshot` 的“时间”只有 `HH:MM:SS`，没有日期；日期要用本地交易日补齐；
- `get_latest_quote` 的“更新时间”用 `datetime.fromtimestamp`，依赖进程时区；容器通常 UTC，
  会与上海时间差 8 小时；
- 现有适配器统一 `Asia/Shanghai`，并有 `asOf` 字段；接入时要显式转换。

### 6.8 复权

`get_quote_history` 默认 `fqt=1`（前复权），与现有适配器一致；但 `beg` 默认 1900 年，
一次可能返回几千行。服务端要传 `beg`/`end`（或按最近 N 日过滤），不要用默认全历史。

---

## 7. 运行时与部署风险清单

| 风险 | 证据 | 影响 | 处理 |
| --- | --- | --- | --- |
| 非 root 容器导入失败 | 只读 `site-packages` 下 `PermissionError`；wheel 无 `data/` | 容器启动即失败 | 不引入库；或预建目录并 chown |
| 依赖体积 | 133 MB venv；pandas 55 MB、numpy 33 MB | 镜像/冷启动变大 | 不引入生产依赖 |
| 无超时 | session 180s；多处 `requests.get` 无 timeout | worker 挂起 | 用 httpx + 8s 超时重写 |
| 无缓存 | 行情/K 线每次打网络 | 重复查询慢、易限流 | 复用现有 TTL 缓存 |
| 全局 TLS 降级 | `DEFAULT_CIPHERS="ALL:@SECLEVEL=1"`、`verify=False` | 安全基线被削弱 | 不 import；httpx 默认校验 |
| 全局 SIGINT/excepthook | import 时安装 | 影响 uvicorn 退出/错误处理 | 不 import |
| HTTP/代理 | 多处 `http://`；信任环境代理 | 无代理环境失败/行为不一致 | 统一 https + `trust_env=False` |
| 并发/限流 | 全市场分页默认线程池；多股 K 线 50 并发 | 被封禁、超时 | 自建并发上限/预算 |
| pandas 3 兼容 | `Pandas4Warning`；无上界 | 未来升级断裂 | 研究工具锁 `pandas<3` |
| 无测试 | 仓库无 test 目录 | 接口变更无回归 | 自己写 fixture 测试 |
| 数据授权 | README“不得用于商业用途” | 生产使用有合规风险 | 生产换持牌数据商 |

---

## 8. 建议与分阶段计划

### 8.1 立即决策

1. **不要把 `efinance` 加进 `requirements.txt`**，也不要替换现有 `EastmoneyProvider`；
2. **保留现有年报/财务指标链路**，它是 efinance 给不了的；
3. 先做“接口吸收”，而不是“库接入”。

### 8.2 第一阶段（建议下一个 PR）

范围：一个模块、几百行以内，不改部署依赖。

- 在 `server/marketdata.py` 的 `_short_term` 中增加：
  - `sealAmount`（五档快照，涨停时计算，非涨停为 `None`）；
  - `dragonTigerNetBuy`（龙虎榜，按日期+代码去重，保留 `reason`）；
- 增加一个批量报价 helper（`ulist.np`），用于 `compare_companies` 的多股场景；
- 可选：资金流（`FundFlow`）和板块候选列表，先只写入快照，不参与规则；
- 新增 fixture 单测：涨停快照、非涨停快照、龙虎榜重复原因、接口超时/空响应；
- 更新 `docs/agent.md` 的字段说明（如果新增字段进入回答）。

验收：

- 600519 的 `fetch` 冷启动请求数控制在 9 次以内（当前 5 次 + 封单/龙虎榜/资金流/板块各 1 次），
  缓存命中后仍为毫秒级；
- 涨停 fixture 下 R17 从“无法评估”变为可评估；
- 非涨停/无榜单时字段为 `None`，R17/R16 仍能明确说明缺什么；
- 不新增运行时依赖，Dockerfile 不变，`pytest` 全绿。

### 8.3 第二阶段（本体 2.0a/2.0c 之后）

- 季度业绩全市场横截面（用于 `screen`，不覆盖年报）；
- 十大股东/股东户数（解析中文单位，修正列错位）；
- 指数成分/权重、逐笔（2.0d）。

### 8.4 第三阶段（按需）

- 研究用 efinance 可选依赖（`requirements-research.txt`，锁 `pandas<3`）；
- 或独立旁路服务，输出规范化 JSON；
- 生产环境仍应评估持牌数据商，efinance 只作为原型/研究工具。

### 8.5 不要做的事

- 不要把动态 PE 写进 `peTtm`；
- 不要把季度累计 ROE/净利写进年报字段；
- 不要对龙虎榜多条记录直接求和；
- 不要把“没有封单”写成 `0` 来让规则通过；
- 不要为了“更全面”引入 133 MB 依赖和全局 TLS 降级。

---

## 9. 未验证与限制

- **全市场行情未验证**：本机 `push2 clist` 返回 301/空响应，现有 `screen()` 也失败；
  efinance 的 `get_realtime_quotes()` 无法在本环境确认可用。
- **封单公式未做盘中涨停端到端验证**：采样时没有正在涨停的股票；字段（涨停价、买1价/量）
  已确认存在，公式简单，但仍建议在涨停日复测。
- **全市场批量未完成**：5,574 只分批拉取在约 2,000 只后卡住；这本身是风险证据，不是性能结论。
- **单样本时延**：所有耗时是单次采样，未做 P50/P95、并发和长时间限流测试。
- **Docker 未实际构建**：非 root 导入失败是用只读 `site-packages` 模拟的；结论成立，但未跑完整镜像。
- **数据准确性未独立核对**：未与交易所/持牌数据逐字段比对；efinance 无测试套件。
- **许可证**：MIT 是代码许可；README 的“不得用于商业用途”和数据源条款需法务确认，本文不构成法律意见。

---

## 附录 A：复现命令

```bash
# 1. 克隆与安装（研究环境）
git clone --depth 1 https://github.com/Micro-sheep/efinance /tmp/efinance-study
uv venv /tmp/efinance-venv --python 3.12
uv pip install --python /tmp/efinance-venv/bin/python efinance==0.5.9 httpx

# 2. 关键探测（临时脚本，不入库）
/tmp/efinance-venv/bin/python - <<'PY'
import time, efinance as ef
for name, fn in [
    ("snapshot", lambda: ef.stock.get_quote_snapshot("600519")),
    ("base", lambda: ef.stock.get_base_info("600519")),
    ("quote", lambda: ef.stock.get_latest_quote(["600519", "300750"])),
    ("kline", lambda: ef.stock.get_quote_history("600519", beg="20260101")),
    ("billboard", lambda: ef.stock.get_daily_billboard()),
    ("performance", lambda: ef.stock.get_all_company_performance()),
    ("holders", lambda: ef.stock.get_latest_holder_number()),
]:
    t = time.perf_counter()
    value = fn()
    rows = len(value) if hasattr(value, "__len__") else "-"
    print(f"{name:12s} {time.perf_counter() - t:6.2f}s rows={rows}")
PY

# 3. 现有适配器对照
PYTHONPATH=. /tmp/project-venv/bin/python - <<'PY'
import time
from server.marketdata import EastmoneyProvider
p = EastmoneyProvider()
for i in range(2):
    t = time.perf_counter()
    s = p.fetch("600519")
    print(f"fetch {i}: {time.perf_counter() - t:.3f}s", s.quote["lastPrice"], s.valuation["peTtm"])
PY

# 4. 非 root 只读 site-packages 导入模拟
mkdir -p /tmp/ro
cp -r /tmp/efinance-venv/lib/python3.12/site-packages/efinance /tmp/ro/efinance
rm -rf /tmp/ro/efinance/data
chmod -R a-w /tmp/ro/efinance
PYTHONPATH=/tmp/ro /tmp/efinance-venv/bin/python -c 'import efinance'   # PermissionError

# 5. 项目自检（docs-only 改动）
python scripts/check_no_secrets.py
python scripts/validate.py
pytest -q
```

## 附录 B：参考

- 仓库：<https://github.com/Micro-sheep/efinance>
- 文档：<https://efinance.readthedocs.io>
- 相关 issue：
  - #204 缓存目录无法用环境变量指定（与本项目 Docker 相关）
  - #230 `get_latest_holder_number` 股东人数/百分比列错位
  - #235 / #229 / #215 限流、超时
  - #245 搜索接口问题（0.5.9 有相关修复，issue 仍打开）
  - #246 复权因子接口需求
- 本项目相关文件：
  - `server/marketdata.py`（现有适配器）
  - `server/ontology.py`（运行时事实映射）
  - `server/rules.py`（R16–R21 阈值与缺失处理）
  - `ontology/rdfs/schema.ttl`（`FundFlow`、`Shareholder` 等类）
  - `ontology/odrl/policies.ttl`（龙虎榜/游资数据政策）
  - `docs/agent.md`（真实数据模式说明）
