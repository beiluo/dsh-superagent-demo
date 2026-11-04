"""Agent-driven acquisition of missing market data.

The product agent decides *what* fact it is missing and *where* to get it; this
module only provides a generic runner for declarative source recipes.  A recipe
is JSON: an HTTPS endpoint, optional list selection, and a field-to-JSON-path
mapping.  Adding a new public dataset therefore does not require a new Python
adapter -- the agent can register a recipe at runtime, and the same recipe is
reused for later questions.

Safety boundaries:

* HTTPS only, no redirects, bounded response size and timeout;
* hosts must match the configured public-finance allow-list, and every resolved
  address must be globally routable (blocks localhost / private-network SSRF);
* only read-only ``GET`` requests are issued, with no cookies or credentials.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

SHANGHAI_TZ = timezone(timedelta(hours=8))

SOURCE_FILE = Path(__file__).with_name("data_sources.json")

DEFAULT_ALLOWED_HOSTS: tuple[str, ...] = (
    "eastmoney.com",
    "sina.com.cn",
    "qq.com",
    "163.com",
    "cninfo.com.cn",
    "sse.com.cn",
    "szse.cn",
    "csrc.gov.cn",
    "10jqka.com.cn",
)

# Fields the rest of the server knows how to merge into the runtime ontology.
SUPPORTED_FIELDS: dict[str, dict[str, Any]] = {
    "dragonTigerNetBuy": {
        "label": "龙虎榜净买入",
        "unit": "元",
        "rules": ["R16"],
        "hint": "交易所龙虎榜明细的净买入金额。",
    },
    "hotMoneySeatCount": {
        "label": "游资席位数量",
        "unit": "个",
        "rules": ["R16"],
        "hint": "龙虎榜买方席位中的营业部（推断为游资）数量。",
    },
    "sealAmount": {
        "label": "封单金额",
        "unit": "元",
        "rules": ["R17"],
        "hint": "涨停池中的封单资金。",
    },
    "limitUpDays": {
        "label": "连板天数",
        "unit": "天",
        "rules": ["R17", "R18"],
        "hint": "涨停池中的连续涨停天数。",
    },
    "brokenBoardCount": {
        "label": "炸板次数",
        "unit": "次",
        "rules": ["R17", "R19"],
        "hint": "涨停池中的炸板次数。",
    },
    "firstLimitUpTime": {"label": "首次涨停时间", "unit": "", "rules": ["R17"], "hint": ""},
    "auctionPriceChange": {
        "label": "竞价涨幅",
        "unit": "%",
        "rules": [],
        "hint": "集合竞价/开盘价相对前收盘价的涨跌幅。",
    },
    "auctionVolumeRatio": {
        "label": "竞价量比",
        "unit": "倍",
        "rules": [],
        "hint": "集合竞价成交量相对近期均量的倍数。",
    },
    "sentimentScore": {
        "label": "市场情绪分数",
        "unit": "分",
        "rules": [],
        "hint": "市场情绪指标分数。",
    },
    "themeHeatScore": {
        "label": "主题热度",
        "unit": "分",
        "rules": ["R21"],
        "hint": "主题/行业热度分数。",
    },
    "hasNewsCatalyst": {
        "label": "新闻催化",
        "unit": "",
        "rules": ["R21"],
        "hint": "是否存在可核对的催化新闻。",
    },
}

# Fields that can appear in a source payload for context/provenance but are not
# requested as mergeable facts on their own.
SOURCE_ONLY_FIELDS = {"dragonTigerBuyAmount", "dragonTigerSellAmount"}


class AcquisitionError(Exception):
    """A safe, user-facing acquisition failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text in {"-", "--", "null", "None"}:
            return None
        value = text
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    if number is None:
        return None
    try:
        return int(number)
    except (TypeError, ValueError, OverflowError):
        return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y", "是"}:
            return True
        if text in {"false", "0", "no", "n", "否", ""}:
            return False
    return None


def _as_time(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) not in {5, 6}:
        return text
    digits = digits.zfill(6)
    hour, minute, second = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
    if hour > 23 or minute > 59 or second > 59:
        return text
    return f"{hour:02d}:{minute:02d}:{second:02d}"


TYPE_READERS: dict[str, Callable[[Any], Any]] = {
    "float": lambda value: _as_float(value),
    "int": lambda value: _as_int(value),
    "bool": lambda value: _as_bool(value),
    "str": lambda value: None if value is None else str(value),
    "time": lambda value: _as_time(value),
}


_PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _walk(payload: Any, path: str) -> Any:
    """Read ``a.b[0].c`` / ``a[2]`` from a decoded JSON document."""

    if path in {"", "."}:
        return payload
    current = payload
    position = 0
    for match in _PATH_TOKEN.finditer(path):
        if match.start() != position and path[position : match.start()].strip("."):
            raise AcquisitionError("invalid_path", f"无法解析字段路径：{path}")
        position = match.end()
        name, index = match.group(1), match.group(2)
        if name is not None:
            if not isinstance(current, dict):
                return None
            current = current.get(name)
        else:
            if not isinstance(current, list):
                return None
            offset = int(index)
            if offset >= len(current) or offset < -len(current):
                return None
            current = current[offset]
        if current is None:
            return None
    if position != len(path) and path[position:].strip("."):
        raise AcquisitionError("invalid_path", f"无法解析字段路径：{path}")
    return current


class _Template(dict):
    def __missing__(self, key: str) -> str:
        raise AcquisitionError("invalid_source", f"数据源模板缺少变量 {{{key}}}。")


def _render(template: str, context: dict[str, Any]) -> str:
    if not isinstance(template, str):
        raise AcquisitionError("invalid_source", "数据源模板必须是字符串。")
    try:
        return template.format_map(_Template(context))
    except (KeyError, ValueError, IndexError) as exc:
        raise AcquisitionError("invalid_source", f"数据源模板无法渲染：{exc}") from exc


def _check_public_url(url: str, allowed_hosts: tuple[str, ...]) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise AcquisitionError("unsafe_source", "只允许 HTTPS 公开数据源。")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise AcquisitionError("unsafe_source", "数据源地址不能携带凭据或非标准端口。")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise AcquisitionError("unsafe_source", "数据源地址缺少主机名。")
    allowed = any(host == suffix or host.endswith("." + suffix) for suffix in allowed_hosts)
    if not allowed:
        raise AcquisitionError(
            "host_not_allowed",
            f"数据源主机 {host} 不在允许的公开金融数据域名内。",
        )
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise AcquisitionError("source_unreachable", f"无法解析数据源主机 {host}。") from exc
    for info in addresses:
        address = str(info[4][0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise AcquisitionError("unsafe_source", "数据源解析到了非法地址。") from None
        if not ip.is_global:
            raise AcquisitionError("unsafe_source", "数据源不能指向内网或本机地址。")


@dataclass(frozen=True)
class DataRequest:
    url: str
    params: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    select: dict[str, Any] | None = None
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    as_of_path: str | None = None


@dataclass(frozen=True)
class DataSource:
    id: str
    label: str
    description: str
    attribution: str
    requests: tuple[DataRequest, ...]
    lookback_days: int = 0
    ttl_seconds: int = 300
    custom: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "attribution": self.attribution,
            "lookbackDays": self.lookback_days,
            "ttlSeconds": self.ttl_seconds,
            "fields": sorted(
                {
                    name
                    for request in self.requests
                    for name in request.fields
                }
            ),
            "custom": self.custom,
        }


@dataclass
class AcquiredDataset:
    source_id: str
    label: str
    attribution: str
    values: dict[str, Any]
    as_of: str
    url: str
    fetched_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "label": self.label,
            "attribution": self.attribution,
            "asOf": self.as_of,
            "url": self.url,
            "fetchedAt": self.fetched_at.isoformat(),
            "values": {key: value for key, value in self.values.items() if value is not None},
        }


def _parse_source(raw: Any, *, custom: bool = False) -> DataSource:
    if not isinstance(raw, dict):
        raise AcquisitionError("invalid_source", "数据源定义必须是 JSON 对象。")
    source_id = str(raw.get("id") or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", source_id):
        raise AcquisitionError("invalid_source", "数据源 id 只能包含小写字母、数字、点、横线和下划线。")
    label = str(raw.get("label") or source_id).strip()[:120]
    description = str(raw.get("description") or "").strip()[:500]
    attribution = str(raw.get("attribution") or "公开数据接口").strip()[:200]
    lookback_days = _as_int(raw.get("lookbackDays", 0))
    ttl_seconds = _as_int(raw.get("ttlSeconds", 300))
    if lookback_days is None or not 0 <= lookback_days <= 30:
        raise AcquisitionError("invalid_source", "lookbackDays 必须在 0–30 之间。")
    if ttl_seconds is None or not 0 <= ttl_seconds <= 86_400:
        raise AcquisitionError("invalid_source", "ttlSeconds 必须在 0–86400 之间。")
    raw_requests = raw.get("requests")
    if raw_requests is None and raw.get("url"):
        # Agent-friendly flat form: one request described at the top level.
        raw_requests = [
            {
                "url": raw.get("url"),
                "params": raw.get("params") or {},
                "headers": raw.get("headers") or {},
                "select": raw.get("select"),
                "fields": raw.get("fields") or {},
                "asOfPath": raw.get("asOfPath"),
            }
        ]
    if not isinstance(raw_requests, list) or not raw_requests or len(raw_requests) > 4:
        raise AcquisitionError("invalid_source", "每个数据源需要 1–4 个请求定义。")
    requests: list[DataRequest] = []
    for item in raw_requests:
        if not isinstance(item, dict):
            raise AcquisitionError("invalid_source", "请求定义必须是 JSON 对象。")
        url = str(item.get("url") or "").strip()
        if not url:
            raise AcquisitionError("invalid_source", "请求缺少 url。")
        params = item.get("params") or {}
        headers = item.get("headers") or {}
        if not isinstance(params, dict) or not isinstance(headers, dict):
            raise AcquisitionError("invalid_source", "params/headers 必须是对象。")
        select = item.get("select")
        if select is not None and not isinstance(select, dict):
            raise AcquisitionError("invalid_source", "select 必须是对象。")
        fields = item.get("fields") or {}
        if not isinstance(fields, dict) or not fields or len(fields) > 40:
            raise AcquisitionError("invalid_source", "fields 需要 1–40 个字段映射。")
        for name, spec in fields.items():
            if name not in SUPPORTED_FIELDS and name not in SOURCE_ONLY_FIELDS and name != "seats":
                raise AcquisitionError("unknown_field", f"不支持的数据字段：{name}")
            if not isinstance(spec, dict) or not str(spec.get("path") or "").strip():
                raise AcquisitionError("invalid_source", f"字段 {name} 缺少 path。")
            kind = str(spec.get("type") or "float")
            if kind not in TYPE_READERS and kind != "rows":
                raise AcquisitionError("invalid_source", f"字段 {name} 的 type 不支持：{kind}")
        requests.append(
            DataRequest(
                url=url,
                params={str(key): str(value) for key, value in params.items()},
                headers={str(key): str(value) for key, value in headers.items()},
                select=select,
                fields={str(name): dict(spec) for name, spec in fields.items()},
                as_of_path=(str(item["asOfPath"]) if item.get("asOfPath") else None),
            )
        )
    return DataSource(
        id=source_id,
        label=label,
        description=description,
        attribution=attribution,
        requests=tuple(requests),
        lookback_days=lookback_days,
        ttl_seconds=ttl_seconds,
        custom=custom,
    )


def _load_default_sources(path: Path = SOURCE_FILE) -> list[DataSource]:
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("sources") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    sources: list[DataSource] = []
    for item in items:
        try:
            sources.append(_parse_source(item))
        except AcquisitionError:
            continue
    return sources


def _scope_as_of(payload: Any, scope: Any, path: str | None) -> str:
    if not path:
        return ""
    if path.startswith("$"):
        value = _walk(payload, path[1:].lstrip("."))
    else:
        value = _walk(scope, path)
    if value is None:
        return ""
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return text[:10] if len(text) >= 10 else text


class AcquisitionService:
    """Runs declarative sources and returns extracted facts with provenance."""

    def __init__(
        self,
        *,
        sources: list[dict[str, Any]] | list[DataSource] | None = None,
        allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS,
        timeout_seconds: float = 8.0,
        max_bytes: int = 2_000_000,
        client: httpx.Client | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.allowed_hosts = tuple(host.lower().strip(".") for host in allowed_hosts if host)
        self.timeout_seconds = max(2.0, float(timeout_seconds))
        self.max_bytes = max(10_000, int(max_bytes))
        self._clock = clock or (lambda: datetime.now(tz=SHANGHAI_TZ))
        self._client = client
        self._cache: dict[tuple[str, str, str], tuple[float, AcquiredDataset]] = {}
        self.sources: dict[str, DataSource] = {}
        raw_sources = sources if sources is not None else _load_default_sources()
        for item in raw_sources:
            spec = item if isinstance(item, DataSource) else _parse_source(item)
            self.sources[spec.id] = spec

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_sources(self) -> list[dict[str, Any]]:
        return [source.as_dict() for source in self.sources.values()]

    def get_source(self, source_id: str) -> DataSource:
        source = self.sources.get(source_id)
        if source is None:
            raise AcquisitionError("unknown_source", f"未知数据源：{source_id}")
        return source

    def register_source(self, raw: Any) -> DataSource:
        spec = _parse_source(raw, custom=True)
        if spec.id in self.sources and not self.sources[spec.id].custom:
            raise AcquisitionError("source_id_taken", f"数据源 id 已被内置数据源占用：{spec.id}")
        self.sources[spec.id] = spec
        return spec

    def fetch(self, source_id: str, context: dict[str, Any]) -> AcquiredDataset:
        source = self.get_source(source_id)
        return self._fetch_spec(source, context)

    def fetch_custom(self, raw: Any, context: dict[str, Any]) -> AcquiredDataset:
        spec = _parse_source(raw, custom=True)
        return self._fetch_spec(spec, context, cache=False)

    # ------------------------------------------------------------------
    # Implementation
    # ------------------------------------------------------------------

    def _client_for_request(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        options: dict[str, Any] = {
            "timeout": self.timeout_seconds,
            "follow_redirects": False,
            "trust_env": False,
            "headers": {
                "User-Agent": "ashare-ontology-agent/1.8.1 (+https://github.com/beiluo/dsh-superagent-demo)",
                "Accept": "application/json,text/plain,*/*",
            },
        }
        # Honour the deployment proxy explicitly.  httpx's trust_env parser
        # rejects some NO_PROXY forms such as "[::1]", so the proxy is read here
        # and environment parsing is disabled.
        proxy = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
        )
        if proxy:
            options["proxy"] = proxy
        try:
            self._client = httpx.Client(**options)
        except (TypeError, ValueError):
            options.pop("proxy", None)
            self._client = httpx.Client(**options)
        return self._client

    def _fetch_spec(
        self, spec: DataSource, context: dict[str, Any], *, cache: bool = True
    ) -> AcquiredDataset:
        code = str(context.get("code") or "")
        cache_key = (spec.id, code, str(context.get("base_date") or ""))
        now = self._clock()
        if cache:
            cached = self._cache.get(cache_key)
            if cached and (now - cached[1].fetched_at).total_seconds() < spec.ttl_seconds:
                return cached[1]

        base_date = context.get("base_date")
        if isinstance(base_date, str):
            try:
                base_date = date.fromisoformat(base_date)
            except ValueError:
                base_date = None
        if not isinstance(base_date, date):
            base_date = now.date()

        last_error: AcquisitionError | None = None
        for offset in range(spec.lookback_days + 1):
            day = base_date - timedelta(days=offset)
            rendered_context = {
                **context,
                "date": day.isoformat(),
                "yyyymmdd": day.strftime("%Y%m%d"),
                "year": str(day.year),
            }
            try:
                values: dict[str, Any] = {}
                as_of = ""
                source_url = ""
                for request in spec.requests:
                    url = _render(request.url, rendered_context)
                    params = {
                        key: _render(value, rendered_context)
                        for key, value in request.params.items()
                    }
                    headers = {
                        key: _render(value, rendered_context)
                        for key, value in request.headers.items()
                    }
                    payload = self._get_json(url, params, headers)
                    if not source_url:
                        source_url = _with_params(url, params)
                    request_values, request_as_of = self._extract(
                        payload, request, rendered_context
                    )
                    values.update(request_values)
                    if not as_of:
                        as_of = request_as_of
                if not any(value is not None for value in values.values()):
                    raise AcquisitionError("no_data", "数据源没有返回可用字段。")
            except AcquisitionError as exc:
                last_error = exc
                if exc.code in {"no_data", "http_not_found", "empty_response"} and offset < spec.lookback_days:
                    continue
                raise
            dataset = AcquiredDataset(
                source_id=spec.id,
                label=spec.label,
                attribution=spec.attribution,
                values=values,
                as_of=as_of or rendered_context["date"],
                url=source_url,
                fetched_at=now,
            )
            if cache:
                self._cache[cache_key] = (time.time(), dataset)
            return dataset

        raise last_error or AcquisitionError("no_data", "数据源没有返回可用字段。")

    def _get_json(self, url: str, params: dict[str, str], headers: dict[str, str]) -> Any:
        _check_public_url(url, self.allowed_hosts)
        client = self._client_for_request()
        try:
            with client.stream("GET", url, params=params, headers=headers) as response:
                if response.status_code == 404:
                    raise AcquisitionError("http_not_found", "数据源返回 404。")
                if response.status_code >= 400:
                    raise AcquisitionError(
                        "http_error", f"数据源返回 HTTP {response.status_code}。"
                    )
                if 300 <= response.status_code < 400:
                    raise AcquisitionError("unsafe_redirect", "数据源发生了未授权的重定向。")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise AcquisitionError("response_too_large", "数据源响应超过大小限制。")
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise AcquisitionError("source_unreachable", "无法连接公开数据源，请稍后重试。") from exc
        raw = b"".join(chunks)
        if not raw.strip():
            raise AcquisitionError("empty_response", "数据源返回了空响应。")
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise AcquisitionError("bad_response", "数据源返回的不是可解析的 JSON。") from exc

    def _extract(
        self, payload: Any, request: DataRequest, context: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        scope = payload
        if request.select:
            path = request.select.get("path")
            if not isinstance(path, str) or not path:
                raise AcquisitionError("invalid_source", "select 缺少 path。")
            rows = _walk(payload, path)
            if not isinstance(rows, list) or not rows:
                raise AcquisitionError("no_data", "数据源没有返回可选的记录。")
            matcher = request.select.get("match") or {}
            if not isinstance(matcher, dict):
                raise AcquisitionError("invalid_source", "select.match 必须是对象。")
            selected = None
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if all(
                    str(row.get(key)) == _render(str(expected), context)
                    for key, expected in matcher.items()
                ):
                    selected = row
                    break
            if selected is None:
                raise AcquisitionError("no_data", "数据源没有匹配该证券的记录。")
            scope = selected

        values: dict[str, Any] = {}
        for name, spec in request.fields.items():
            path = str(spec.get("path") or "")
            if spec.get("type") == "rows":
                rows = _walk(scope, path)
                if not isinstance(rows, list):
                    rows = []
                item_spec = spec.get("item") or {}
                if not isinstance(item_spec, dict):
                    raise AcquisitionError("invalid_source", f"字段 {name} 的 item 映射无效。")
                items = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    item = {}
                    for key, item_path in item_spec.items():
                        item[str(key)] = _walk(row, str(item_path))
                    if any(value is not None for value in item.values()):
                        items.append(item)
                if not items:
                    raise AcquisitionError("no_data", "数据源没有返回席位明细。")
                values[name] = items
                continue
            raw = _walk(scope, path)
            kind = str(spec.get("type") or "float")
            if kind == "rows":
                continue
            value = TYPE_READERS[kind](raw) if kind in TYPE_READERS else None
            scale = _as_float(spec.get("scale"))
            if value is not None and scale is not None and scale != 1.0:
                value = value * scale
            values[name] = value

        return values, _scope_as_of(payload, scope, request.as_of_path)


def _with_params(url: str, params: dict[str, str]) -> str:
    if not params:
        return url
    try:
        query = httpx.QueryParams(params)
    except Exception:  # pragma: no cover - defensive
        return url
    return f"{url}?{query}"


__all__ = [
    "AcquisitionError",
    "AcquisitionService",
    "AcquiredDataset",
    "DEFAULT_ALLOWED_HOSTS",
    "SUPPORTED_FIELDS",
]
