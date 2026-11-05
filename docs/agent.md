# 本体股票分析 Agent：部署与密钥配置

> **一句话：LLM key 只放在服务端环境变量里。GitHub Pages 是静态托管，永远不要、也不可能安全地保存 key。**

页面上的 Agent 是一个“前端 + 独立后端”的结构：

```text
GitHub Pages (static)                 Your server / Render (private env)
┌───────────────────────┐   HTTPS    ┌───────────────────────────────┐
│ index.html            │  ───────▶  │ POST /api/agent/analyze       │
│ assets/js/agent.js    │            │   ├─ OntologyStore (TTL)      │
│ 公开 API 地址，无密钥  │  ◀───────  │   ├─ SWRL rule evaluation     │
└───────────────────────┘   JSON     │   ├─ tool loop / rules mode   │
                                     │   └─ LLM_API_KEY (server env) │
                                     └──────────────┬────────────────┘
                                                    │ Authorization: Bearer …
                                                    ▼
                                          LLM API (OpenAI-compatible)
```

浏览器永远只看到公开的 API 地址和本体数据。它不会收到 `LLM_API_KEY`，也不会直接调用 LLM 供应商。

---

## 1. 为什么不能放在 GitHub Pages

GitHub Pages 把仓库里的文件原样发给每个访问者。任何写进 `index.html`、`assets/js/*.js`、
构建产物或提交历史里的 key，都等于公开。

因此本项目把密钥边界定在：

| 位置 | 可以放 key 吗 | 说明 |
| --- | --- | --- |
| `assets/js/agent-config.js` | **不可以** | 只放公开的 `apiBase` 地址 |
| `assets/js/agent.js` | **不可以** | 浏览器只调用自己的后端 |
| `index.html` / `data.js` | **不可以** | 静态产物全部公开 |
| 仓库 `.env` | **不可以提交** | `.gitignore` 已忽略；只用于本地 |
| 服务端环境变量 | **可以** | Render/Railway/Fly/Cloud Run/自己的服务器 |
| GitHub Actions secrets | 可以，但本仓库当前不需要 | 仅当 CI 要调用 LLM 时 |

`scripts/check_no_secrets.py` 会扫描被 git 跟踪的文本文件；`make validate` 会运行它，CI 也可以直接调用同一脚本。

---

## 2. 本地运行

```bash
make setup          # 创建 .venv 并安装依赖（uv）
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY；不填也能运行规则模式
make agent          # http://127.0.0.1:8000/
```

`make agent` 同时提供静态页面和 API，所以 `agent-config.js` 里的 `apiBase` 留空即可（同源）。

不配置 key 时，页面显示 **“规则模式 · 未配置 LLM key”**，Agent 仍会执行本体检索、
SWRL 信号评估和 Markdown 回答生成。配置 key 后重启服务，状态变为 **“LLM 已配置”**。

### 只启动静态页面

```bash
make serve          # http://127.0.0.1:8000/
```

这时页面可以浏览本体；Agent 会显示“Agent 服务未连接”，因为同源没有后端。这是预期行为。

---

## 3. LLM key 怎么配置

### 3.1 本地 `.env`

```dotenv
LLM_API_KEY=your-provider-key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

`.env` 已被 `.gitignore` 忽略。不要在聊天、Issue、PR 或截图里贴出真实 key。

### 3.2 部署平台环境变量

在托管平台的环境变量/Secret 面板里设置：

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `LLM_API_KEY` | LLM 模式必填 | 空 | 只存在服务端；空值自动进入规则模式 |
| `LLM_BASE_URL` | 否 | `https://api.deepseek.com/v1` | OpenAI-compatible 基址，最终调用 `/chat/completions` |
| `LLM_MODEL` | 否 | `deepseek-chat` | 模型名 |
| `LLM_ENABLED` | 否 | `true` | 设为 `false` 可强制规则模式 |
| `ALLOWED_ORIGINS` | 否 | 见 `.env.example` | 允许跨域调用 API 的浏览器 Origin |
| `TRUST_PROXY` | 否 | `false` | 平台设置 `X-Forwarded-For` 时设为 `true` |
| `RATE_LIMIT_PER_MINUTE` | 否 | `6` | 每 IP 每分钟请求上限 |
| `RATE_LIMIT_PER_HOUR` | 否 | `40` | 每 IP 每小时请求上限 |
| `DAILY_REQUEST_BUDGET` | 否 | `300` | 进程级每日总请求上限 |
| `MAX_QUESTION_CHARS` | 否 | `500` | 单次问题最大长度 |
| `AGENT_MAX_STEPS` | 否 | `6` | LLM 工具调用最大轮数；自由 SPARQL 的生成/修正需要更多轮 |
| `LLM_MAX_OUTPUT_TOKENS` | 否 | `1800` | 单次回答最大 token；多股对比需要更长输出 |
| `MARKET_DATA_ENABLED` | 否 | `true` | 是否启用真实 A 股查询；关闭后只保留示例公司 |
| `MARKET_DATA_TIMEOUT_SECONDS` | 否 | `8` | 真实行情请求超时 |
| `MARKET_DATA_QUOTE_TTL_SECONDS` | 否 | `60` | 行情缓存秒数 |
| `MARKET_DATA_FINANCIAL_TTL_SECONDS` | 否 | `21600` | 年报/财务指标缓存秒数 |
| `MARKET_DATA_SHORT_TERM_TTL_SECONDS` | 否 | `300` | 日线/均线/连板快照缓存秒数 |
| `ACQUISITION_ENABLED` | 否 | `true` | 是否允许 Agent 自驱抓取缺失公开数据 |
| `ACQUISITION_TIMEOUT_SECONDS` | 否 | `8` | 单个数据源请求超时 |
| `ACQUISITION_MAX_BYTES` | 否 | `2000000` | 单个响应体上限 |
| `ACQUISITION_ALLOWED_HOSTS` | 否 | 见代码 | 允许的公开金融域名后缀，逗号分隔 |

### 3.3 密钥轮换

1. 在 LLM 供应商控制台创建新 key；
2. 在托管平台更新 `LLM_API_KEY`，触发重新部署；
3. 确认 `/api/agent/status` 返回 `llm.configured = true`；
4. 在供应商控制台禁用旧 key。

如果 key 曾进入 git 历史，仅删除文件不够；需要轮换 key，并按 GitHub 文档清理历史。

---

## 4. 部署后端

### 4.1 Render（推荐，一键 Blueprint）

仓库根目录的 [`render.yaml`](../render.yaml) 是一个 Blueprint：

1. 在 Render 中新建 Blueprint，连接 `beiluo/dsh-superagent-demo`；
2. Render 读取 `render.yaml`，创建一个 Docker Web Service；
3. 在服务的 Environment 中设置 `LLM_API_KEY`（`sync: false` 不会把值写进仓库）；
4. 部署完成后访问 `https://<service>.onrender.com/api/health`；
5. 把后端地址写入 `assets/js/agent-config.js`：

   ```js
   window.ASHD_AGENT_CONFIG = Object.freeze({
     apiBase: "https://ashare-ontology-agent.onrender.com",
   });
   ```

6. 提交并等待 GitHub Pages 重新发布。这个地址是公开的，不是密钥。

如果使用自定义域名：更新 `ALLOWED_ORIGINS`，把新的页面 Origin 加进去。

### 4.2 Docker / 任意容器平台

```bash
docker build -t ashare-ontology-agent .
docker run --rm -p 8000:8000 --env-file .env ashare-ontology-agent
```

平台需要：

- 一个 HTTP 端口（`PORT` 环境变量，默认 8000）；
- 健康检查 `GET /api/health`；
- 设置 `TRUST_PROXY=true`（如果平台终止 TLS）；
- 把 `ALLOWED_ORIGINS` 设置为你的页面 Origin。

### 4.3 直接用自己的服务器

```bash
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

建议前面放 Nginx/Caddy 做 TLS，并限制请求体大小和连接数。`server/app.py` 自身已经有
请求体上限、CORS、限流和每日额度，但它们不能替代平台级防护。

---

## 5. 把 GitHub Pages 接到后端

GitHub Pages 不能运行 Python。它只负责静态页面：

- `index.html`
- `assets/js/agent-config.js`（公开 API 地址）
- `assets/js/agent.js`（调用 API）

`assets/js/agent-config.js` 的 `apiBase` 留空时：

- 同源部署（`make agent`）→ 自动调用 `/api/agent/*`；
- GitHub Pages → 页面显示“Agent 后端未连接”，并给出部署提示。

设置 `apiBase` 后，页面会跨域调用后端；后端的 `ALLOWED_ORIGINS` 必须包含
`https://beiluo.github.io`（或你的自定义域名）。

---

## 6. Agent 如何基于本体工作

### 6.1 LLM 模式：Agent 直接使用本体

Agent 不把整份 Turtle 塞进 prompt，也不使用固定的分析工具。LLM 模式只暴露四项通用能力：

| 能力 | 作用 |
| --- | --- |
| `load_company_data` | 把真实 A 股的公开行情、年报、估值与短线快照写入运行时本体图；只返回公司标识、来源与日期，不返回分析结论 |
| `acquire_data` | 当本体图缺少可获取的短线公开数据（龙虎榜净买入/席位、封单、连板、炸板）时，由 Agent 自己抓取、校验并写入运行内存本体；也可用声明式 `source` 接入其它公开接口 |
| `describe_ontology` | 读取类、对象属性、数据属性、命名空间前缀与示例查询；可按 `focus` 检索 |
| `sparql_query` | 执行 Agent 自己生成的只读 SPARQL，支持任意图模式、聚合、路径与否定条件 |

所有本体查询都由模型生成：公司/财报/行情/估值用属性路径，规则从 `ash:RuleArtifact` 读
`ruleIf`/`ruleThen` 后对照事实，证据链用反向遍历，组合与 ODRL 政策用图查询。模型可以多轮
“生成→执行→按结果修正”，最多 `AGENT_MAX_STEPS` 轮。服务端对生成查询做这些限制：

- 只接受 `SELECT` 与 `ASK`；`INSERT`/`DELETE`/`LOAD`/`CLEAR` 等更新和 `CONSTRUCT`/`DESCRIBE` 被拒绝；
- 禁止 `SERVICE` 与 `FROM`，不会从查询里访问远程端点或加载外部文件；
- 查询最长 4,000 字符，单次最多返回 50 行，长字面量会截断；
- 执行失败只返回安全错误、可用前缀和 `describe_ontology` 提示，不返回 traceback；
- 工具面在服务端固定为上面四项；模型调用 `get_company_analysis`、`check_constraints` 等隐藏工具会得到
  `tool_not_available`，不会被执行。

数据缺失时，LLM 先从 `load_company_data` 的 `missingData` 知道缺哪些短线字段，再调用
`acquire_data` 抓取并写入本体；写入后仍用 SPARQL 查询事实。`acquire_data` 只读公开 HTTPS
金融接口，不修改仓库中的 Turtle 文件。

### 6.2 规则模式：确定性回退

没有 key 或 LLM 调用失败时，服务端使用下面这些固定工具生成可复现的 Markdown 回答。它们不出现在
LLM 的工具列表里：

| 工具 | 作用 |
| --- | --- |
| `list_companies` | 列出本体中的合成公司与示例决策 |
| `get_company_analysis` | 企业、证券、财报、行情估值、短线快照、风险、决策、证据、合规与 R01–R21 规则信号；支持真实 A 股 |
| `screen_companies` | 对本体中已有公司执行 SWRL 规则筛选 |
| `compare_companies` | 2–5 只股票的本体同口径对比：统一字段 + R01–R21 + 指标 RDF 路径与证据 |
| `query_ontology` | 问题驱动的跨公司筛选：业务字段→属性路径、行业、规则条件、排序；`universe=real` 扫真实行情单页样本 |
| `trace_evidence` | 从公司/决策/规则/政策展开证据链，保留数据日期、来源与版本 |
| `check_constraints` | R06/R07/R11 与 ODRL trade-guard 的人工批准、合规检查前置条件 |
| `evaluate_trade` | 账户与持仓状态、组合风险预算、买点/卖点/仓位、预计权重、购买力、T+1 可卖、执行质量与复盘闭环；检查 R152–R161 |
| `simulate_scenario` | 在内存事实副本上改指标并重跑规则，对比 what-if 前后状态 |
| `get_portfolio_analysis` | 组合持仓、R05 止损、R06 集中度 |
| `get_rule` | 规则 IF/THEN、阈值、责任人、当前触发对象；同时支持 V2.0 的 OP/VP/AUC/MKT/EVT/POS/RSK/EVA 规范规则，返回类别、状态机、后续动作与参数占位 |
| `get_policies` | ODRL 权限/禁止/义务 |
| `search_ontology` | 类、属性、个体、概念、规则、政策、服务检索 |

`query_ontology` 的多条筛选条件按 AND 组合，`positionWeight` 用 0-1 小数；`universe=real` 时只接受
`peTtm`、`pb`、`marketCap`、`turnoverRate`、`changePct`，读取行情接口单页最多 200 只，不做全市场
年报级扫描。自由生成的 SPARQL 与规则模式的工具结果都使用同一个 `queryPath` 结构，前端“本体
查询路径”会显示实际执行的事实加载、图式读取与查询。

服务端从 `ontology/**/*.ttl` 读取规范源（rdflib），规则阈值与
`ontology/swrl/rules.ttl` 中的示例常量保持同步，并由 `tests/test_rules.py` 校验。

真实 A 股查询先用 `server/marketdata.py` 的公开数据适配器取数，再把快照映射成运行时
RDF 事实（公司、证券、年报、行情、估值、SKOS 行业）；LLM 模式只负责加载，后续分析全部由
SPARQL 完成。

### 6.3 两种模式

- **LLM 模式**：工具循环，最多 `AGENT_MAX_STEPS` 轮；模型只看到 `load_company_data`、
  `describe_ontology`、`sparql_query`，所有本体查询由模型自己生成。
- **规则模式**：没有 key 或 LLM 调用失败时，服务端用固定工具做确定性检索，再生成 Markdown
  回答；不生成 SPARQL，保持可复现的固定路径。LLM 失败会自动回退，不会把上游错误原文返回给浏览器。

### 6.4 输出

`POST /api/agent/analyze` 返回：

```json
{
  "requestId": "…",
  "mode": "llm",
  "dataMode": "example",
  "model": "deepseek-chat",
  "answer": "Markdown…",
  "summary": null,
  "citations": [
    {"id": "company-huachen", "iri": "…", "label": "华辰智造", "kind": "individual"}
  ],
  "steps": [
    {"tool": "load_company_data", "label": "加载公司事实到本体图", "status": "ok"},
    {"tool": "sparql_query", "label": "执行 Agent 生成的只读 SPARQL", "status": "ok"}
  ],
  "queryPath": [
    {"tool": "load_company_data", "label": "加载公司事实到本体图", "steps": []},
    {
      "tool": "sparql_query",
      "label": "执行 Agent 生成的只读 SPARQL",
      "steps": [
        {"kind": "select", "label": "执行 Agent 生成的只读 SPARQL", "detail": "SELECT …"},
        {"kind": "scan", "label": "扫描图模式并绑定变量", "detail": "变量: company、label"},
        {"kind": "result", "label": "返回查询结果", "detail": "返回 4 行"}
      ]
    }
  ],
  "execution": {
    "mode": "llm",
    "model": "deepseek-chat",
    "systemPrompt": {"hidden": true, "chars": 1500},
    "messages": [
      {"role": "user", "content": "分析华辰智造"},
      {
        "role": "assistant",
        "content": "",
        "toolCalls": [
          {
            "id": "call_1",
            "name": "load_company_data",
            "arguments": {"company": "华辰智造"}
          }
        ],
        "round": 1
      },
      {
        "role": "tool",
        "toolCallId": "call_1",
        "name": "load_company_data",
        "label": "加载公司事实到本体图",
        "arguments": {"company": "华辰智造"},
        "ok": true,
        "elapsedMs": 12,
        "content": "{\"ok\": true, \"data\": {…}}"
      },
      {
        "role": "assistant",
        "content": "",
        "toolCalls": [
          {
            "id": "call_2",
            "name": "sparql_query",
            "arguments": {"query": "SELECT ?company ?roe WHERE { … } LIMIT 10"}
          }
        ],
        "round": 2
      },
      {
        "role": "tool",
        "toolCallId": "call_2",
        "name": "sparql_query",
        "label": "执行 Agent 生成的只读 SPARQL",
        "arguments": {"query": "SELECT ?company ?roe WHERE { … } LIMIT 10"},
        "ok": true,
        "elapsedMs": 5,
        "content": "{\"ok\": true, \"data\": {…}}"
      },
      {"role": "assistant", "content": "…最终 Markdown 回答…"}
    ]
  },
  "notice": null,
  "elapsedMs": 1234
}
```

`queryPath` 汇总本次实际调用的工具及其查询步骤（范围选择、属性路径、过滤、规则复核、结果），
前端渲染为“本体查询路径”。问题不同，工具组合与路径也不同。

`execution` 是前端“执行详情”面板的数据源：按顺序给出用户/历史消息、LLM 的工具决策（工具名与参数）、
发给 LLM 的工具结果原文，以及最终回答。工具结果与发给 LLM 的内容一致，过长时会被截断并标记。
系统提示只返回隐藏标记与字符数，不把提示原文下发浏览器。规则模式下 `messages` 只包含用户消息
和每次确定性工具调用/返回，没有 LLM 消息。

`citations` 的 `kind:id` 可以直接映射到浏览器的 `#entity=kind:id`，点击后跳转到 Explorer 详情。
真实 A 股结果额外带 `dataMode: "real"`；其运行时实体标记为 `kind: "real"`，不在静态
`data.js` 中，因此前端显示为不可点击的证据 chip，而规则、类和已有 SKOS 概念仍可跳转。

### 6.5 真实 A 股数据

默认启用，无需 API key。输入 `600519`、`贵州茅台` 或 `600519.SH` 时：

1. `EastmoneyProvider` 解析证券并读取公开行情（价格、涨跌幅、换手率、市值、PE/PB）；
2. 读取最近一期年报与主要财务指标（ROE、ROA、资产负债率、利息保障、经营现金流、增速）；
3. 读取近 80 个交易日日线，计算 MA5/MA20/MA60、连板天数和炸板次数；
4. `load_company_data` 调用 `OntologyStore.register_real_company`，在内存中写入 `ash:ListedCompany`、
   `ash:AShare`、`ash:AnnualReport`、`ash:MarketQuote`、`ash:Valuation`、`ash:LimitUpStreak` 和
   SKOS 行业概念；
5. LLM 模式由 Agent 查询 `ash:RuleArtifact` 并对照公司事实；规则模式由规则引擎执行 R01–R11 与
   R16–R21。缺少龙虎榜净买入、封单金额或新闻催化的字段标为“无法评估”，不会用推测补齐；
   回答返回 `dataMode="real"`。

要点：

- 运行时 IRI 位于 `.../a-share/real#`，不写回 Turtle 文件；
- 行情缓存 60 秒、财报缓存 6 小时、短线日线缓存 5 分钟；规则模式的 `screen_companies` 不包含
  真实公司，真实横截面请用 `query_ontology` 的 `universe=real`；LLM 模式用 `sparql_query` 查询；
- 真实 A 股的短线字段目前覆盖均线、连板/炸板；龙虎榜净买入/席位、封单等缺失字段由 Agent 通过
  `acquire_data` 自行抓取并写入运行内存本体，不再要求用户预先提供数据源或写适配器；
- 数据来自东方财富公开网页接口，可能延迟、限流或改版；生产环境应替换为持牌数据源；
- `MARKET_DATA_ENABLED=false` 可完全关闭真实数据查询；关闭后 Agent 只分析示例公司。

---

## 6.5 Agent 自驱数据获取

目标：**缺数据由 Agent 自己去取、自己接入**，不再要求用户先补数据源或由工程师为每个来源写
Python 适配器。

### 流程

1. `load_company_data`（LLM 模式）或 `get_company_analysis`（规则模式）返回真实 A 股画像；
   缺失的短线字段进入 `missingData`，相关规则显示为“无法评估”；
2. Agent 调用 `acquire_data`（省略 `fields` 时自动补齐缺失字段）；
3. 服务端 `server/acquisition.py` 按**声明式数据源**执行 GET：URL 模板、参数、列表选择、
   字段→JSON 路径映射、类型/倍率转换，返回事实与来源；
4. `OntologyStore.merge_short_term` 把事实写入运行内存 RDF 图（`ash:LimitUpStreak`、
   `ash:DragonTigerList`、席位、竞价快照、情绪指标、主题热度等），并保留来源、日期与
   `dataQualityFlag="agent-acquired"`；
5. 规则引擎立即重算，`acquire_data` 返回规则状态变化、更新后的 `shortTerm`、仍缺字段与
   数据来源；LLM 模式随后用 `sparql_query` 查询写入后的事实，规则模式据此回答。

抓取到的事实会保存在每只证券的覆盖层里，后续行情/年报刷新不会把它们静默清掉；覆盖层默认
1 小时后过期，过期后再次分析会重新获取。它们只写入内存，不修改仓库中的 Turtle 文件。

### 内置数据源

| 数据源 id | 获取字段 | 说明 |
| --- | --- | --- |
| `eastmoney-billboard` | 龙虎榜净买入/买入额/卖出额 | 按交易日回溯，未上榜不写入 |
| `eastmoney-billboard-seats` | 买方营业部席位与净买入 | 机构/陆股通/基金等单列，营业部席位推断为游资 |
| `eastmoney-limit-pool` | 连板天数、炸板次数、封单金额、首次涨停时间 | 当日涨停池，未涨停不写入 |

### Agent 自行接入新数据源

内置数据源不够时，Agent 可以在 `source` 参数里直接传入声明式数据源，成功后注册到当前进程，
后续问题可复用：

```json
{
  "id": "my-auction-source",
  "label": "公开竞价快照",
  "url": "https://example.eastmoney.com/auction",
  "params": {"code": "{code}", "date": "{yyyymmdd}"},
  "select": {"path": "data.rows", "match": {"code": "{code}"}},
  "asOfPath": "date",
  "fields": {
    "auctionPriceChange": {"path": "premiumPct", "type": "float"},
    "auctionVolumeRatio": {"path": "volumeRatio", "type": "float", "scale": 1.0}
  }
}
```

字段类型支持 `float`、`int`、`bool`、`str`、`time` 与 `rows`（席位列表）。模板变量包括
`{code}`、`{market}`、`{secid}`、`{date}`、`{yyyymmdd}` 和 `{year}`。字段路径是简化的
JSONPath：`a.b[0].c`。

### 安全边界

- 只允许 `https`，且主机必须在 `ACQUISITION_ALLOWED_HOSTS`（默认东方财富、新浪、腾讯、
  巨潮、交易所等公开金融域名）内；
- 每次解析目标域名并拒绝内网、本机、链路本地等非全局地址；不跟随重定向；
- 只发 `GET`，不携带 Cookie、密钥或用户凭据；
- 超时、响应体大小与字段路径数量都有上限；
- `ACQUISITION_ENABLED=false` 可完全关闭该能力。

### 已知限制

- 个人交易日志、账户持仓等非公开数据无法从公开接口获取，Agent 会明确说明需要用户提供；
- 新闻催化暂未接入可核对的公开来源，仍标为“无法评估”；
- 竞价快照/情绪指标/主题热度已支持写入，但尚未有内置数据源，可由 Agent 用 `source` 接入；
- 数据为公开网页接口，可能延迟、限流或改版；生产环境应替换为持牌数据源。

---

## 7. 安全边界

后端内置：

- **密钥边界**：key 只在 `Settings.llm_api_key`，`repr` 不输出；不写日志、不进 prompt、不进响应；
- **CORS**：只允许 `ALLOWED_ORIGINS` 中的 Origin；
- **限流**：每 IP 每分钟/每小时 + 全局每日额度；
- **请求体上限**：默认 24 KB；
- **并发上限**：默认 4 个 LLM 请求；
- **静态白名单**：只挂载 `assets/`、`ontology/`、`docs/` 和 `index.html`，不会把 `.env`、
  `server/`、`.git` 或 `requirements.txt` 当静态文件发出去；
- **错误脱敏**：上游 401/500 的原始 body 不返回浏览器；日志中的 key 会被替换为 `[redacted]`；
- **输出边界**：系统提示要求不提供真实投资建议、不编造工具结果外的数字；真实数据模式必须标明
  公开接口与数据日期，不生成评级、目标价、止损价或风险评分。

仍然需要注意：

- 公开演示后端是**可被任何人调用**的。限流和额度只能降低滥用风险，不能替代身份认证。
  如果要在公开互联网长期运行，建议加平台级 WAF/配额，或只允许内网/受控用户访问。
- 多实例部署时，进程内限流不会共享；需要 Redis 或平台限流。
- ODRL 政策是声明式示例，不是法律合同或真实访问控制。
- 所有公司、财务、行情、决策均为合成示例，不构成投资建议。

---

## 8. 验证

```bash
make test                      # API、规则阈值、LLM 客户端、回退与密钥扫描测试
make validate                  # 本体结构校验 + 密钥扫描
python scripts/check_no_secrets.py
```

浏览器端验证：

```bash
make agent
# 打开 http://127.0.0.1:8000/#agent
```

检查：

1. 状态显示“规则模式”或“LLM 已配置”；
2. 输入“分析华辰智造”，出现结论卡片、规则信号和证据链；
3. 点击证据 chip，Explorer 打开对应 IRI；
4. 页面源码/网络请求中没有 `LLM_API_KEY` 或 `Authorization` 头。
