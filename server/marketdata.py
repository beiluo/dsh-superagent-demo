"""Real A-share market data adapter.

The demo provider reads the public JSON endpoints used by Eastmoney's quote
pages.  It needs no API key, which keeps the local demo self-contained, but it
is an unofficial web endpoint: it can change, rate-limit or return partial
data.  Everything is therefore isolated behind :class:`MarketDataProvider` so
a licensed vendor (Tushare, AkShare, Wind, ...) can be swapped in later.

Only public market/filing facts are mapped; no account, order or position data
is fetched, and the adapter never writes to the ontology files on disk.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx

SOURCE_LABEL = "东方财富公开行情接口"
SOURCE_URL = "https://quote.eastmoney.com/"
SEARCH_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"
SHANGHAI_TZ = timezone(timedelta(hours=8))

SEARCH_ENDPOINT = "https://searchapi.eastmoney.com/api/suggest/get"
QUOTE_ENDPOINT = "https://push2.eastmoney.com/api/qt/stock/get"
REPORT_ENDPOINT = "https://datacenter-web.eastmoney.com/api/data/v1/get"
INDICATOR_ENDPOINT = "https://datacenter.eastmoney.com/securities/api/data/v1/get"

QUOTE_FIELDS = "f43,f47,f48,f57,f58,f60,f86,f116,f162,f163,f164,f167,f168,f170,f173"

CODE_PATTERN = re.compile(r"^(?:(?:sh|sz|bj)[.\s-]?)?(\d{6})(?:\.(?:sh|sz|bj))?$", re.IGNORECASE)
A_SHARE_CLASSIFICATIONS = {"AStock", "NEEQ"}
A_SHARE_MARKETS = {"沪A", "深A", "京A", "科创板", "创业板"}


class MarketDataError(Exception):
    """A safe, user-facing failure from the real-data provider."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SecurityRef:
    code: str
    name: str
    secid: str
    exchange_code: str
    exchange_label: str
    segment_code: str
    segment_label: str


@dataclass
class RealCompanySnapshot:
    """Normalised public-data snapshot for one listed A-share company."""

    security: SecurityRef
    quote: dict[str, Any]
    valuation: dict[str, Any]
    financials: dict[str, Any] | None
    industry: str | None
    fetched_at: datetime
    notes: list[str] = field(default_factory=list)
    source_label: str = SOURCE_LABEL
    source_url: str = SOURCE_URL

    def as_of(self) -> str:
        return (self.quote.get("asOf") or self.fetched_at.date().isoformat())[:10]


class MarketDataProvider(Protocol):
    source_label: str
    source_url: str

    def fetch(self, query: str) -> RealCompanySnapshot | None:
        """Resolve ``query`` to one A-share and return a snapshot, or None."""


def _num(value: Any, *, divide: float = 1.0, digits: int = 2) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text in {"-", "--", "null", "None"}:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
    number = number / divide
    return round(number, digits)


def _date(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else None


def _market_from_code(code: str) -> tuple[str, str]:
    if code.startswith("92"):
        return "BJ", "BSE"
    if code.startswith(("6", "9")):
        return "SH", "SSE"
    if code.startswith(("4", "8")):
        return "BJ", "BSE"
    return "SZ", "SZSE"


def _secucode(code: str) -> str:
    if code.startswith(("92", "4", "8")):
        suffix = "BJ"
    elif code.startswith(("6", "9")):
        suffix = "SH"
    else:
        suffix = "SZ"
    return f"{code}.{suffix}"


def _segment_from(code: str, exchange_code: str) -> tuple[str, str]:
    if exchange_code == "BSE":
        return "bse", "北交所"
    if code.startswith(("688", "689")):
        return "star", "科创板"
    if code.startswith(("300", "301")):
        return "chinext", "创业板"
    return "main", "主板"


def _exchange_details(item: dict[str, Any], code: str) -> tuple[str, str]:
    type_name = str(item.get("SecurityTypeName") or "")
    quote_id = str(item.get("QuoteID") or "")
    if "京" in type_name or (quote_id.startswith("0.") and code.startswith(("4", "8", "9"))):
        return "BSE", "北京证券交易所"
    if quote_id.startswith("1."):
        return "SSE", "上海证券交易所"
    if "科创板" in type_name:
        return "SSE", "上海证券交易所"
    return "SZSE", "深圳证券交易所"


class EastmoneyProvider:
    """Public-data provider backed by Eastmoney's anonymous JSON endpoints."""

    source_label = SOURCE_LABEL
    source_url = SOURCE_URL

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        quote_ttl_seconds: int = 60,
        financial_ttl_seconds: int = 21_600,
        transport: httpx.BaseTransport | None = None,
        clock: Any = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.quote_ttl_seconds = quote_ttl_seconds
        self.financial_ttl_seconds = financial_ttl_seconds
        self._clock = clock or time.monotonic
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=min(4.0, timeout_seconds)),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                "Accept": "application/json,text/plain,*/*",
                "Referer": SOURCE_URL,
            },
            transport=transport,
            follow_redirects=True,
            trust_env=False,
        )
        self._lock = threading.Lock()
        self._resolve_cache: dict[str, tuple[float, SecurityRef]] = {}
        self._quote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._financial_cache: dict[str, tuple[float, tuple[dict[str, Any] | None, str | None, list[str]]]] = {}

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise MarketDataError("market_data_timeout", "真实行情数据源响应超时，请稍后重试。") from exc
        except httpx.RequestError as exc:
            raise MarketDataError("market_data_unreachable", "无法连接真实行情数据源，请稍后重试。") from exc
        if response.status_code >= 400:
            raise MarketDataError(
                "market_data_http_error",
                f"真实行情数据源返回 HTTP {response.status_code}，请稍后重试。",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MarketDataError("market_data_bad_response", "真实行情数据源返回了无法解析的数据。") from exc
        if not isinstance(payload, dict):
            raise MarketDataError("market_data_bad_response", "真实行情数据源返回了无法解析的数据。")
        return payload

    def _cache_get(self, cache: dict[str, Any], key: str, ttl: int) -> Any | None:
        with self._lock:
            item = cache.get(key)
        if not item:
            return None
        stored_at, value = item
        if self._clock() - stored_at <= ttl:
            return value
        return None

    def _cache_put(self, cache: dict[str, Any], key: str, value: Any) -> None:
        with self._lock:
            cache[key] = (self._clock(), value)

    # ------------------------------------------------------------------
    # Resolve and fetch
    # ------------------------------------------------------------------

    def resolve(self, query: str) -> SecurityRef | None:
        text = re.sub(r"\s+", "", str(query or ""))
        if not text:
            return None
        cached = self._cache_get(self._resolve_cache, text.lower(), 3_600)
        if cached is not None:
            return cached

        code_match = CODE_PATTERN.match(text)
        code_hint = code_match.group(1) if code_match else None
        if not code_hint:
            anywhere = re.search(r"(?<!\d)(\d{6})(?!\d)", text)
            code_hint = anywhere.group(1) if anywhere else None
        if not code_hint and not re.search(r"[\u4e00-\u9fffA-Za-z]", text):
            return None

        try:
            payload = self._get_json(
                SEARCH_ENDPOINT,
                {"input": code_hint or text, "type": "14", "token": SEARCH_TOKEN},
            )
        except MarketDataError:
            if not code_hint:
                raise
            # A 6-digit code can still be quoted even if the suggestion API is down.
            payload = {}
        table = payload.get("QuotationCodeTable") or {}
        items = table.get("Data") or []
        candidates = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            classification = str(item.get("Classify") or "")
            type_name = str(item.get("SecurityTypeName") or "")
            if classification not in A_SHARE_CLASSIFICATIONS and type_name not in A_SHARE_MARKETS:
                continue
            if "京A" not in type_name and classification != "AStock":
                continue
            item_code = str(item.get("Code") or "")
            if code_hint and item_code != code_hint:
                continue
            candidates.append(item)

        if not candidates and code_hint:
            market, exchange_code = _market_from_code(code_hint)
            exchange_label = {"SSE": "上海证券交易所", "SZSE": "深圳证券交易所", "BSE": "北京证券交易所"}[exchange_code]
            segment_code, segment_label = _segment_from(code_hint, exchange_code)
            resolved = SecurityRef(
                code=code_hint,
                name="",
                secid=f"{'1' if market == 'SH' else '0'}.{code_hint}",
                exchange_code=exchange_code,
                exchange_label=exchange_label,
                segment_code=segment_code,
                segment_label=segment_label,
            )
            self._cache_put(self._resolve_cache, text.lower(), resolved)
            return resolved

        if not candidates:
            return None
        if not code_hint:
            exact = [item for item in candidates if str(item.get("Name") or "").strip() == text]
            if exact:
                candidates = exact

        item = candidates[0]
        code = str(item.get("Code") or "")
        quote_id = str(item.get("QuoteID") or "")
        secid = quote_id if "." in quote_id else f"{'1' if code.startswith('6') else '0'}.{code}"
        exchange_code, exchange_label = _exchange_details(item, code)
        segment_code, segment_label = _segment_from(code, exchange_code)
        resolved = SecurityRef(
            code=code,
            name=str(item.get("Name") or ""),
            secid=secid,
            exchange_code=exchange_code,
            exchange_label=exchange_label,
            segment_code=segment_code,
            segment_label=segment_label,
        )
        self._cache_put(self._resolve_cache, text.lower(), resolved)
        self._cache_put(self._resolve_cache, code.lower(), resolved)
        if resolved.name:
            self._cache_put(self._resolve_cache, resolved.name.lower(), resolved)
        return resolved

    def fetch(self, query: str) -> RealCompanySnapshot | None:
        security = self.resolve(query)
        if security is None:
            return None
        quote, fetched_at = self._quote(security)
        if not security.name:
            security = replace(security, name=str(quote.get("name") or security.code))
        quote = dict(quote)
        financials, industry, notes = self._financials(security)
        valuation = {
            "peTtm": quote.pop("peTtm", None),
            "pb": quote.pop("pb", None),
            "asOf": quote.get("asOf"),
            "source": SOURCE_LABEL,
            "quality": "public-api",
        }
        quote["source"] = SOURCE_LABEL
        quote["quality"] = "public-api"
        return RealCompanySnapshot(
            security=security,
            quote=quote,
            valuation=valuation,
            financials=financials,
            industry=industry,
            fetched_at=fetched_at,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Endpoint parsing
    # ------------------------------------------------------------------

    def _quote(self, security: SecurityRef) -> tuple[dict[str, Any], datetime]:
        cached = self._cache_get(self._quote_cache, security.code, self.quote_ttl_seconds)
        if cached is not None:
            return cached, self._fetched_at_for(security.code)

        payload = self._get_json(QUOTE_ENDPOINT, {"secid": security.secid, "fields": QUOTE_FIELDS})
        data = payload.get("data")
        if not isinstance(data, dict) or not data.get("f57"):
            raise MarketDataError(
                "market_data_no_quote",
                f"没有获取到 {security.code} 的行情；该证券可能已停牌、退市或代码有误。",
            )
        timestamp = _num(data.get("f86"), digits=0)
        if timestamp:
            if timestamp > 10_000_000_000:
                timestamp = timestamp / 1000
            fetched_at = datetime.fromtimestamp(timestamp, tz=SHANGHAI_TZ)
            if not (2000 <= fetched_at.year <= 2100):
                fetched_at = datetime.now(tz=SHANGHAI_TZ)
        else:
            fetched_at = datetime.now(tz=SHANGHAI_TZ)

        raw_volume = _num(data.get("f47"), digits=0)
        quote = {
            "code": str(data.get("f57") or security.code),
            "name": str(data.get("f58") or security.name),
            "lastPrice": _num(data.get("f43"), divide=100.0),
            "changePct": _num(data.get("f170"), divide=100.0),
            "volume": raw_volume * 100 if raw_volume is not None else None,
            "turnoverRate": _num(data.get("f168"), divide=100.0),
            "marketCap": _num(data.get("f116"), digits=0),
            "peTtm": _num(data.get("f164"), divide=100.0),
            "pb": _num(data.get("f167"), divide=100.0),
            "asOf": fetched_at.date().isoformat(),
        }
        if quote["peTtm"] is None:
            quote["peTtm"] = _num(data.get("f162"), divide=100.0)
        # Negative PE/PB mean "not meaningful" rather than "cheap"; rules must
        # not treat a loss-making or negative-equity company as a value pick.
        for field_name in ("peTtm", "pb"):
            if quote[field_name] is not None and quote[field_name] <= 0:
                quote[field_name] = None
        self._cache_put(self._quote_cache, security.code, quote)
        with self._lock:
            self._quote_cache[f"{security.code}:at"] = (self._clock(), fetched_at)
        return quote, fetched_at

    def _fetched_at_for(self, code: str) -> datetime:
        with self._lock:
            item = self._quote_cache.get(f"{code}:at")
        return item[1] if item else datetime.now(tz=SHANGHAI_TZ)

    def _financials(self, security: SecurityRef) -> tuple[dict[str, Any] | None, str | None, list[str]]:
        cached = self._cache_get(self._financial_cache, security.code, self.financial_ttl_seconds)
        if cached is not None:
            return cached

        notes: list[str] = []
        report: dict[str, Any] | None = None
        industry: str | None = None
        try:
            report, industry = self._annual_report(security.code)
        except MarketDataError as exc:
            notes.append(str(exc))

        if report is not None:
            try:
                indicators = self._annual_indicators(security.code, report.get("fiscalYearEnd") or "")
            except MarketDataError as exc:
                indicators = {}
                notes.append(str(exc))
            for key in (
                "debtRatio",
                "roa",
                "interestCoverage",
                "operatingCashFlow",
            ):
                if indicators.get(key) is not None:
                    report[key] = indicators[key]
            if report.get("operatingCashFlow") is None:
                notes.append("经营现金流缺失。")
            if report.get("interestCoverage") is None:
                notes.append("利息保障倍数缺失，R02 无法完整评估。")
        else:
            notes.append("年报或财务指标暂不可用，仅展示行情与估值。")

        result = (report, industry, notes)
        self._cache_put(self._financial_cache, security.code, result)
        return result

    def _annual_report(self, code: str) -> tuple[dict[str, Any], str | None]:
        payload = self._get_json(
            REPORT_ENDPOINT,
            {
                "reportName": "RPT_LICO_FN_CPD",
                "columns": "ALL",
                "filter": f'(SECURITY_CODE="{code}")',
                "sortColumns": "REPORTDATE",
                "sortTypes": "-1",
                "pageSize": "16",
                "pageNumber": "1",
            },
        )
        rows = ((payload.get("result") or {}).get("data")) or []
        annual = next(
            (row for row in rows if isinstance(row, dict) and (_date(row.get("REPORTDATE")) or "").endswith("12-31")),
            None,
        )
        if annual is None:
            raise MarketDataError("market_data_no_annual_report", "没有获取到最近一期年报数据。")
        fiscal_year_end = _date(annual.get("REPORTDATE"))
        year = (fiscal_year_end or "")[:4]
        report = {
            "period": year or None,
            "fiscalYearEnd": fiscal_year_end,
            "revenue": _num(annual.get("TOTAL_OPERATE_INCOME"), digits=0),
            "netProfit": _num(annual.get("PARENT_NETPROFIT"), digits=0),
            "roe": _num(annual.get("WEIGHTAVG_ROE")),
            "eps": _num(annual.get("BASIC_EPS"), digits=3),
            "revenueGrowth": _num(annual.get("YSTZ")),
            "profitGrowth": _num(annual.get("SJLTZ")),
            "debtRatio": None,
            "roa": None,
            "interestCoverage": None,
            "operatingCashFlow": None,
            "asOf": fiscal_year_end,
            "source": SOURCE_LABEL,
            "quality": "public-api",
            "currency": "CNY",
        }
        industry = str(annual.get("PUBLISHNAME") or annual.get("BOARD_NAME") or "").strip() or None
        return report, industry

    def _annual_indicators(self, code: str, fiscal_year_end: str) -> dict[str, Any]:
        security_code = _secucode(code)
        payload = self._get_json(
            INDICATOR_ENDPOINT,
            {
                "reportName": "RPT_F10_FINANCE_MAINFINADATA",
                "columns": "ALL",
                "filter": f'(SECUCODE="{security_code}")',
                "sortColumns": "REPORT_DATE",
                "sortTypes": "-1",
                "pageSize": "12",
                "pageNumber": "1",
            },
        )
        rows = ((payload.get("result") or {}).get("data")) or []
        annual = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_date = _date(row.get("REPORT_DATE"))
            if row_date and row_date == fiscal_year_end:
                annual = row
                break
        if annual is None:
            raise MarketDataError("market_data_no_indicators", "没有获取到对应年报的财务指标。")
        return {
            "debtRatio": _num(annual.get("ZCFZL")),
            "roa": _num(annual.get("ZZCJLL")),
            "interestCoverage": _num(annual.get("INTEREST_COVERAGE_RATIO")),
            "operatingCashFlow": _num(annual.get("NETCASH_OPERATE_PK"), digits=0),
        }


def industry_slug(label: str) -> str:
    """Stable, filesystem-safe industry key derived from its display label."""

    digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:10]
    return f"real-industry-{digest}"


__all__ = [
    "EastmoneyProvider",
    "MarketDataError",
    "MarketDataProvider",
    "RealCompanySnapshot",
    "SecurityRef",
    "SOURCE_LABEL",
    "SOURCE_URL",
    "industry_slug",
]
