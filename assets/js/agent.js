/* ==========================================================================
   A-Share Ontology Agent — browser client
   The browser never receives an LLM key. It only calls the public backend
   endpoint configured in assets/js/agent-config.js.
   ========================================================================== */
(() => {
  "use strict";

  const section = document.getElementById("agent");
  if (!section) return;

  const config = window.ASHD_AGENT_CONFIG || {};
  const apiBase =
    typeof config.apiBase === "string" ? config.apiBase.trim().replace(/\/+$/, "") : "";
  const endpoint = (path) => `${apiBase}${path}`;
  const isGitHubPages = /\.github\.io$/i.test(window.location.hostname);
  const MAX_QUESTION = 500;

  const state = {
    status: "checking",
    mode: "rules",
    busy: false,
    history: [],
    companies: [],
  };

  const el = {
    status: document.getElementById("agent-status"),
    statusText: document.getElementById("agent-status-text"),
    statusDetail: document.getElementById("agent-status-detail"),
    retry: document.getElementById("agent-retry"),
    suggestions: document.getElementById("agent-suggestions"),
    log: document.getElementById("agent-log"),
    welcome: document.getElementById("agent-welcome"),
    form: document.getElementById("agent-form"),
    input: document.getElementById("agent-input"),
    submit: document.getElementById("agent-submit"),
    footnote: document.getElementById("agent-footnote"),
  };
  if (!el.form || !el.input || !el.log) return;

  const SUGGESTIONS = [
    "分析华辰智造",
    "哪些公司是价值候选？",
    "组合的集中度风险如何？",
    "R02 是什么规则？",
  ];

  const KIND_LABELS = {
    class: "类",
    objectProperty: "对象属性",
    dataProperty: "数据属性",
    individual: "个体",
    concept: "概念",
    rule: "规则",
    policy: "政策",
    service: "服务",
  };

  const escapeHtml = (value) =>
    String(value == null ? "" : value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");

  const inlineMarkdown = (text) => {
    const code = [];
    let value = String(text || "").replace(/`([^`]+)`/g, (_, content) => {
      code.push(`<code>${content}</code>`);
      return `\u0000${code.length - 1}\u0000`;
    });
    value = value.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    value = value.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) => {
      return `<a href="${url}" target="_blank" rel="noreferrer noopener">${label}</a>`;
    });
    value = value.replace(/\u0000(\d+)\u0000/g, (_, index) => code[Number(index)] || "");
    return value;
  };

  const renderMarkdown = (markdown) => {
    const lines = escapeHtml(markdown).split("\n");
    const blocks = [];
    let paragraph = [];
    let listType = null;

    const flushParagraph = () => {
      if (paragraph.length) {
        blocks.push(`<p>${paragraph.join("<br>")}</p>`);
        paragraph = [];
      }
    };
    const closeList = () => {
      if (listType) {
        blocks.push(`</${listType}>`);
        listType = null;
      }
    };
    const openList = (type) => {
      if (listType !== type) {
        closeList();
        blocks.push(`<${type}>`);
        listType = type;
      }
    };

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) {
        flushParagraph();
        closeList();
        continue;
      }
      if (/^###\s+/.test(line)) {
        flushParagraph();
        closeList();
        blocks.push(`<h4>${inlineMarkdown(line.replace(/^###\s+/, ""))}</h4>`);
        continue;
      }
      if (/^##\s+/.test(line)) {
        flushParagraph();
        closeList();
        blocks.push(`<h3>${inlineMarkdown(line.replace(/^##\s+/, ""))}</h3>`);
        continue;
      }
      if (/^#\s+/.test(line)) {
        flushParagraph();
        closeList();
        blocks.push(`<h3>${inlineMarkdown(line.replace(/^#\s+/, ""))}</h3>`);
        continue;
      }
      if (/^&gt;\s?/.test(line) || /^>\s?/.test(line)) {
        flushParagraph();
        closeList();
        blocks.push(`<blockquote>${inlineMarkdown(line.replace(/^&gt;\s?/, "").replace(/^>\s?/, ""))}</blockquote>`);
        continue;
      }
      if (/^[-*]\s+/.test(line)) {
        flushParagraph();
        openList("ul");
        blocks.push(`<li>${inlineMarkdown(line.replace(/^[-*]\s+/, ""))}</li>`);
        continue;
      }
      if (/^\d+\.\s+/.test(line)) {
        flushParagraph();
        openList("ol");
        blocks.push(`<li>${inlineMarkdown(line.replace(/^\d+\.\s+/, ""))}</li>`);
        continue;
      }
      closeList();
      paragraph.push(inlineMarkdown(line));
    }
    flushParagraph();
    closeList();
    return blocks.join("");
  };

  const formatPct = (value) => {
    const number = Number(value);
    return Number.isFinite(number) ? `${Math.round(number * 100)}%` : "—";
  };

  const formatPrice = (value) => {
    const number = Number(value);
    return Number.isFinite(number) ? `¥${number.toFixed(2)}` : "—";
  };

  const formatNumber = (value) => {
    const number = Number(value);
    return Number.isFinite(number) ? String(number) : "—";
  };

  function setStatus(kind, text, detail) {
    state.status = kind;
    if (el.status) el.status.dataset.state = kind;
    if (el.statusText) el.statusText.textContent = text;
    if (el.statusDetail) el.statusDetail.textContent = detail;
  }

  function setBusy(busy) {
    state.busy = busy;
    if (!el.submit) return;
    el.submit.disabled = busy;
    el.submit.classList.toggle("is-busy", busy);
    const label = el.submit.querySelector("span");
    if (label) label.textContent = busy ? "分析中…" : "分析";
  }

  function scrollLog() {
    if (el.log) el.log.scrollTop = el.log.scrollHeight;
  }

  function hideWelcome() {
    if (el.welcome) el.welcome.hidden = true;
  }

  function appendUser(text) {
    hideWelcome();
    const message = document.createElement("div");
    message.className = "agent-msg agent-msg-user";
    const bubble = document.createElement("div");
    bubble.className = "agent-bubble";
    bubble.textContent = text;
    message.appendChild(bubble);
    el.log.appendChild(message);
    scrollLog();
  }

  function appendPending() {
    hideWelcome();
    const message = document.createElement("div");
    message.className = "agent-msg agent-msg-agent agent-msg-pending";
    message.innerHTML = `
      <div class="agent-msg-meta"><span class="agent-mode" data-mode="pending">检索本体</span></div>
      <div class="agent-bubble agent-pending" aria-label="正在分析">
        <span></span><span></span><span></span>
      </div>`;
    el.log.appendChild(message);
    scrollLog();
    return message;
  }

  function citationHref(item) {
    if (!item.kind || !item.id) return "";
    return `#entity=${encodeURIComponent(`${item.kind}:${item.id}`)}`;
  }

  function appendAgent(payload) {
    hideWelcome();
    const message = document.createElement("div");
    message.className = "agent-msg agent-msg-agent";

    const mode = payload.mode === "llm" ? "LLM 对话" : "规则模式";
    const meta = document.createElement("div");
    meta.className = "agent-msg-meta";
    const modeBadge = document.createElement("span");
    modeBadge.className = "agent-mode";
    modeBadge.dataset.mode = payload.mode === "llm" ? "llm" : "rules";
    modeBadge.textContent = mode;
    meta.appendChild(modeBadge);
    if (payload.model) {
      const model = document.createElement("span");
      model.className = "agent-meta-text";
      model.textContent = payload.model;
      meta.appendChild(model);
    }
    if (Number.isFinite(Number(payload.elapsedMs))) {
      const elapsed = document.createElement("span");
      elapsed.className = "agent-meta-text";
      elapsed.textContent = `${(Number(payload.elapsedMs) / 1000).toFixed(1)}s`;
      meta.appendChild(elapsed);
    }
    message.appendChild(meta);

    if (payload.notice) {
      const notice = document.createElement("p");
      notice.className = "agent-notice";
      notice.textContent = payload.notice;
      message.appendChild(notice);
    }

    if (payload.summary && payload.summary.title) {
      const summary = payload.summary;
      const card = document.createElement("div");
      card.className = "agent-summary";
      card.innerHTML = `
        <div class="agent-summary-primary">
          <span>本体示例结论</span>
          <strong>${escapeHtml(summary.recommendation || "—")}</strong>
          <small>置信度 ${formatPct(summary.confidence)}</small>
        </div>
        <div><span>目标价</span><strong>${formatPrice(summary.targetPrice)}</strong></div>
        <div><span>止损价</span><strong>${formatPrice(summary.stopLoss)}</strong></div>
        <div><span>风险</span><strong>${escapeHtml(summary.riskLevel || "—")} · ${formatNumber(summary.riskScore)}</strong></div>`;
      message.appendChild(card);
    }

    const answer = document.createElement("div");
    answer.className = "agent-answer";
    answer.innerHTML = renderMarkdown(payload.answer || "Agent 没有返回内容。");
    message.appendChild(answer);

    if (Array.isArray(payload.steps) && payload.steps.length) {
      const steps = document.createElement("div");
      steps.className = "agent-steps";
      for (const step of payload.steps) {
        const chip = document.createElement("span");
        chip.className = "agent-step";
        chip.dataset.status = step.status || "ok";
        chip.textContent = step.label || step.tool || "工具";
        if (step.detail) chip.title = step.detail;
        steps.appendChild(chip);
      }
      message.appendChild(steps);
    }

    if (Array.isArray(payload.citations) && payload.citations.length) {
      const citations = document.createElement("div");
      citations.className = "agent-citations";
      const label = document.createElement("span");
      label.className = "agent-citations-label";
      label.textContent = "本体证据";
      citations.appendChild(label);
      for (const item of payload.citations) {
        const href = citationHref(item);
        const node = document.createElement(href ? "a" : "span");
        node.className = "agent-citation";
        if (href) node.href = href;
        node.textContent = item.label || item.id || item.iri || "证据";
        const kind = document.createElement("em");
        kind.textContent = KIND_LABELS[item.kind] || item.kind || "";
        node.appendChild(kind);
        citations.appendChild(node);
      }
      message.appendChild(citations);
    }

    el.log.appendChild(message);
    scrollLog();
  }

  function appendError(message, question) {
    hideWelcome();
    const node = document.createElement("div");
    node.className = "agent-msg agent-msg-agent";
    node.innerHTML = `
      <div class="agent-msg-meta"><span class="agent-mode" data-mode="error">未完成</span></div>
      <div class="agent-bubble agent-error"></div>`;
    node.querySelector(".agent-error").textContent = message;
    if (question) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "agent-inline-retry";
      retry.textContent = "重试";
      retry.addEventListener("click", () => send(question));
      node.appendChild(retry);
    }
    el.log.appendChild(node);
    scrollLog();
  }

  async function fetchWithTimeout(url, options, timeoutMs) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } finally {
      window.clearTimeout(timer);
    }
  }

  async function checkStatus() {
    setStatus("checking", "正在检查 Agent 服务…", "浏览器只连接公开 API，不包含任何 LLM 密钥。");
    if (!apiBase && isGitHubPages) {
      setStatus(
        "offline",
        "Agent 后端未连接",
        "GitHub Pages 只托管静态页面。请先部署 server/，再把后端地址填入 assets/js/agent-config.js（该文件不含密钥）。"
      );
      return;
    }
    try {
      const response = await fetchWithTimeout(
        endpoint("/api/agent/status"),
        { headers: { Accept: "application/json" } },
        6000
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      state.mode = data.mode || "rules";
      state.companies = data.companies || [];
      if (data.llm && data.llm.configured) {
        setStatus(
          "llm",
          `LLM 已配置 · ${data.llm.model || data.llm.provider || "server"}`,
          "问答由服务端调用 LLM；密钥只在服务端环境变量中，浏览器不会收到。"
        );
      } else {
        setStatus(
          "rules",
          "规则模式 · 未启用 LLM",
          "服务端没有可用的 LLM 配置（LLM_API_KEY 或 LLM_ENABLED），当前使用本体规则回答。配置密钥后刷新即可升级为 LLM 对话。"
        );
      }
    } catch (error) {
      setStatus(
        "offline",
        "Agent 服务未连接",
        apiBase
          ? `无法连接 ${apiBase}。请检查后端是否运行、地址是否正确，以及 CORS 是否包含当前站点。`
          : "当前页面没有同源后端。请运行 make agent，或在 GitHub Pages 的 agent-config.js 中填写后端地址。"
      );
    }
  }

  function send(question) {
    const text = String(question || "").trim();
    if (!text || state.busy) return;
    appendUser(text);
    if (state.status === "offline") {
      appendError(
        "Agent 后端未连接。GitHub Pages 不能安全保存 LLM key；请先部署 server/，再把公开后端地址填入 assets/js/agent-config.js。详见 docs/agent.md。",
        ""
      );
      return;
    }

    state.busy = true;
    setBusy(true);
    const pending = appendPending();
    const history = state.history.slice(-4);

    fetchWithTimeout(
      endpoint("/api/agent/analyze"),
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ question: text, history }),
      },
      90000
    )
      .then(async (response) => {
        let payload = {};
        try {
          payload = await response.json();
        } catch (error) {
          payload = {};
        }
        if (!response.ok) {
          const message = payload?.error?.message || `Agent 服务返回 ${response.status}`;
          throw new Error(message);
        }
        pending.remove();
        appendAgent(payload);
        state.history = state.history
          .concat([
            { role: "user", content: text },
            { role: "assistant", content: payload.answer || "" },
          ])
          .slice(-6);
      })
      .catch((error) => {
        pending.remove();
        const message =
          error && error.name === "AbortError"
            ? "请求超时，请稍后重试。"
            : error && error.message
              ? error.message
              : "请求失败，请稍后重试。";
        appendError(message, text);
      })
      .finally(() => {
        state.busy = false;
        setBusy(false);
      });
  }

  function renderSuggestions() {
    if (!el.suggestions) return;
    for (const text of SUGGESTIONS) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "agent-suggestion";
      button.textContent = text;
      button.addEventListener("click", () => {
        el.input.value = text;
        autoGrow();
        updateCounter();
        el.input.focus();
        send(text);
      });
      el.suggestions.appendChild(button);
    }
  }

  function autoGrow() {
    el.input.style.height = "auto";
    el.input.style.height = `${Math.min(el.input.scrollHeight, 128)}px`;
  }

  function updateCounter() {
    const counter = document.getElementById("agent-counter");
    if (counter) counter.textContent = `${el.input.value.length} / ${MAX_QUESTION}`;
  }

  function bind() {
    el.form.addEventListener("submit", (event) => {
      event.preventDefault();
      send(el.input.value);
      el.input.value = "";
      autoGrow();
      updateCounter();
    });
    el.input.addEventListener("input", () => {
      autoGrow();
      updateCounter();
    });
    el.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        el.form.requestSubmit();
      }
    });
    if (el.retry) el.retry.addEventListener("click", checkStatus);
    window.addEventListener("online", checkStatus);
  }

  renderSuggestions();
  bind();
  autoGrow();
  updateCounter();
  checkStatus();
})();
