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
| `AGENT_MAX_STEPS` | 否 | `4` | LLM 工具调用最大轮数 |
| `MARKET_DATA_ENABLED` | 否 | `true` | 是否启用真实 A 股查询；关闭后只保留示例公司 |
| `MARKET_DATA_TIMEOUT_SECONDS` | 否 | `8` | 真实行情请求超时 |
| `MARKET_DATA_QUOTE_TTL_SECONDS` | 否 | `60` | 行情缓存秒数 |
| `MARKET_DATA_FINANCIAL_TTL_SECONDS` | 否 | `21600` | 年报/财务指标缓存秒数 |

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

### 6.1 工具

Agent 不把整份 Turtle 塞进 prompt，而是通过只读工具按需读取：

| 工具 | 作用 |
| --- | --- |
| `list_companies` | 列出本体中的合成公司与示例决策 |
| `get_company_analysis` | 企业、证券、财报、行情估值、风险、决策、证据、合规与规则信号；支持真实 A 股 |
| `screen_companies` | 对本体中已有公司执行 SWRL 规则筛选 |
| `query_ontology` | 问题驱动的跨公司筛选：业务字段→属性路径、行业、规则条件、排序；`universe=real` 扫真实行情单页样本 |
| `trace_evidence` | 从公司/决策/规则/政策展开证据链，保留数据日期、来源与版本 |
| `check_constraints` | R06/R07/R11 与 ODRL trade-guard 的人工批准、合规检查前置条件 |
| `simulate_scenario` | 在内存事实副本上改指标并重跑规则，对比 what-if 前后状态 |
| `get_portfolio_analysis` | 组合持仓、R05 止损、R06 集中度 |
| `get_rule` | 规则 IF/THEN、阈值、责任人、当前触发对象 |
| `get_policies` | ODRL 权限/禁止/义务 |
| `search_ontology` | 类、属性、个体、概念、规则、政策、服务检索 |

`query_ontology` 的多条筛选条件按 AND 组合，`positionWeight` 用 0-1 小数；`universe=real` 时只接受
`peTtm`、`pb`、`marketCap`、`turnoverRate`、`changePct`，读取行情接口单页最多 200 只，不做全市场
年报级扫描。命中结果会映射到运行时 RDF 图，因此每条筛选依据都能给出属性路径。

服务端从 `ontology/**/*.ttl` 读取规范源（rdflib），规则阈值与
`ontology/swrl/rules.ttl` 中的示例常量保持同步，并由 `tests/test_rules.py` 校验。

真实 A 股查询先用 `server/marketdata.py` 的公开数据适配器取数，再把快照映射成运行时
RDF 事实（公司、证券、年报、行情、估值、SKOS 行业），所以工具、规则和引用链路不需要分叉。

### 6.2 两种模式

- **LLM 模式**：工具调用循环，最多 `AGENT_MAX_STEPS` 轮；LLM 只能看到工具结果，不能访问环境变量。
- **规则模式**：没有 key 或 LLM 调用失败时，服务端用同一批工具做确定性检索，再生成 Markdown 回答。
  LLM 失败会自动回退，不会把上游错误原文返回给浏览器。

### 6.3 输出

`POST /api/agent/analyze` 返回：

```json
{
  "requestId": "…",
  "mode": "llm",
  "dataMode": "example",
  "model": "deepseek-chat",
  "answer": "Markdown…",
  "summary": {
    "title": "华辰智造",
    "recommendation": "增持",
    "confidence": 0.78,
    "targetPrice": 45.0,
    "stopLoss": 30.5,
    "riskLevel": "中",
    "riskScore": 42
  },
  "citations": [
    {"id": "decision-huachen-2026q4", "iri": "…", "label": "…", "kind": "individual"}
  ],
  "steps": [{"tool": "get_company_analysis", "label": "读取企业画像与决策链", "status": "ok"}],
  "queryPath": [
    {"tool": "get_company_analysis", "label": "读取企业画像与规则信号", "steps": []}
  ],
  "execution": {
    "mode": "llm",
    "model": "deepseek-chat",
    "systemPrompt": {"hidden": true, "chars": 858},
    "messages": [
      {"role": "user", "content": "分析华辰智造"},
      {
        "role": "assistant",
        "content": "",
        "toolCalls": [
          {
            "id": "call_1",
            "name": "get_company_analysis",
            "arguments": {"company": "华辰智造"}
          }
        ],
        "round": 1
      },
      {
        "role": "tool",
        "toolCallId": "call_1",
        "name": "get_company_analysis",
        "label": "读取企业画像与规则信号",
        "arguments": {"company": "华辰智造"},
        "ok": true,
        "elapsedMs": 12,
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

### 6.4 真实 A 股数据

默认启用，无需 API key。输入 `600519`、`贵州茅台` 或 `600519.SH` 时：

1. `EastmoneyProvider` 解析证券并读取公开行情（价格、涨跌幅、换手率、市值、PE/PB）；
2. 读取最近一期年报与主要财务指标（ROE、ROA、资产负债率、利息保障、经营现金流、增速）；
3. `OntologyStore.register_real_company` 在内存中写入 `ash:ListedCompany`、`ash:AShare`、
   `ash:AnnualReport`、`ash:MarketQuote`、`ash:Valuation` 和 SKOS 行业概念；
4. 规则引擎与回答层沿用原有实现，返回 `dataMode="real"`。

要点：

- 运行时 IRI 位于 `.../a-share/real#`，不写回 Turtle 文件；
- 行情缓存 60 秒、财报缓存 6 小时；`screen_companies` 不包含真实公司，真实横截面请用
  `query_ontology` 的 `universe=real`；
- 数据来自东方财富公开网页接口，可能延迟、限流或改版；生产环境应替换为持牌数据源；
- `MARKET_DATA_ENABLED=false` 可完全关闭真实数据查询；关闭后 Agent 只分析示例公司。

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
