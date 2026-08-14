"""采集美团 / 饿了么 / 京东 / 淘宝闪购等官网公开政策与促销。

硬约束：
- 只抓公开官网、新闻中心、规则/开放平台页
- 禁止爬商家登录后台、禁止 OAuth、禁止编造活动
- 失败如实记入 PlatformIntelRun
"""
from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.time import utc_now
from app.models.business_facts import CampaignRecord
from app.models.entities import Store
from app.models.platform_intel import PlatformIntelItem, PlatformIntelRun

logger = logging.getLogger(__name__)

FetchFn = Callable[[str], tuple[int, str, str, str]]
# status, content_type, body, final_url

USER_AGENT = "MealKey-AI/1.0 (+official-public-policy-collector; no-login)"
MAX_BODY = 512_000
MAX_FOLLOW_LINKS = 6
FETCH_TIMEOUT = 12

_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"}

PROMO_KEYWORDS = (
    "活动",
    "促销",
    "满减",
    "流量券",
    "补贴",
    "报名",
    "神券",
    "红包",
    "免佣",
    "费率优惠",
    "新商",
    "招商",
    "流量扶持",
    "爆品",
)
POLICY_KEYWORDS = (
    "规则",
    "政策",
    "规范",
    "违规",
    "处罚",
    "治理",
    "合规",
    "费率",
    "抽成",
    "保证金",
    "服务协议",
    "入驻",
    "审核",
    "恶意",
    "评价治理",
)

DEFAULT_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "platform": "meituan",
        "name": "美团新闻中心",
        "url": "https://www.meituan.com/news/",
        "kind_hint": "news",
        "follow_links": True,
        "link_contains": "/news/",
    },
    {
        "platform": "meituan",
        "name": "美团关于我们",
        "url": "https://about.meituan.com/",
        "kind_hint": "policy",
        "follow_links": False,
    },
    {
        "platform": "eleme",
        "name": "饿了么开放平台",
        "url": "https://open.ele.me/",
        "kind_hint": "policy",
        "follow_links": False,
    },
    {
        "platform": "jd",
        "name": "京东集团新闻",
        "url": "https://about.jd.com/news/",
        "kind_hint": "news",
        "follow_links": True,
        "link_contains": "/news",
    },
    {
        "platform": "taobao",
        "name": "淘宝闪购公开页",
        "url": "https://pages.tmall.com/wow/z/tmtjb/town/index",
        "kind_hint": "promo",
        "follow_links": False,
    },
)

_DATE_RE = re.compile(r"(20\d{2})[-年./](\d{1,2})[-月./](\d{1,2})")


class IntelFetchError(RuntimeError):
    pass


@dataclass
class ParsedPage:
    url: str
    title: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        text = " ".join(part.strip() for part in self.paragraphs if part.strip())
        text = re.sub(r"\s+", " ", text).strip()
        return text[:400]


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.links: list[tuple[str, str]] = []
        self.paragraphs: list[str] = []
        self._in_a = False
        self._href = ""
        self._a_text: list[str] = []
        self._in_title = False
        self._in_block = False
        self._block_text: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k: (v or "") for k, v in attrs}
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "a" and attrs_d.get("href"):
            self._in_a = True
            self._href = attrs_d["href"]
            self._a_text = []
        elif tag == "title":
            self._in_title = True
        elif tag in {"p", "h1", "h2", "h3", "li", "article"}:
            self._in_block = True
            self._block_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "a" and self._in_a:
            text = html.unescape("".join(self._a_text)).strip()
            text = re.sub(r"\s+", " ", text)
            if text and len(text) >= 6:
                self.links.append((self._href, text[:180]))
            self._in_a = False
        elif tag == "title":
            self._in_title = False
        elif tag in {"p", "h1", "h2", "h3", "li", "article"} and self._in_block:
            text = html.unescape("".join(self._block_text)).strip()
            text = re.sub(r"\s+", " ", text)
            if text and len(text) >= 8:
                self.paragraphs.append(text[:500])
            self._in_block = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
        if self._in_a:
            self._a_text.append(data)
        if self._in_block:
            self._block_text.append(data)


def _is_safe_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if not host or host in _BLOCKED_HOSTS:
        return False
    if host.endswith(".local") or host.endswith(".internal"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    except ValueError:
        pass
    return True


def default_fetch(url: str, timeout: int = FETCH_TIMEOUT) -> tuple[int, str, str, str]:
    if not _is_safe_url(url):
        raise IntelFetchError(f"拒绝非公开安全地址：{url}")
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            final_url = response.geturl() or url
            if not _is_safe_url(final_url):
                raise IntelFetchError(f"重定向到非公开地址：{final_url}")
            raw = response.read(MAX_BODY)
            ctype = response.headers.get("Content-Type", "text/html") or "text/html"
            charset = "utf-8"
            if "charset=" in ctype.lower():
                charset = ctype.split("charset=", 1)[-1].split(";")[0].strip() or "utf-8"
            try:
                body = raw.decode(charset, errors="replace")
            except LookupError:
                body = raw.decode("utf-8", errors="replace")
            return int(getattr(response, "status", 200) or 200), ctype, body, final_url
    except HTTPError as exc:
        raise IntelFetchError(f"HTTP {exc.code} {url}") from exc
    except URLError as exc:
        raise IntelFetchError(f"无法访问 {url}：{exc.reason}") from exc
    except TimeoutError as exc:
        raise IntelFetchError(f"超时 {url}") from exc


def parse_html(url: str, body: str) -> ParsedPage:
    parser = _PageParser()
    try:
        parser.feed(body)
        parser.close()
    except Exception:  # noqa: BLE001
        logger.debug("html parse degraded for %s", url, exc_info=True)
    title = html.unescape(parser.title or "").strip()
    title = re.sub(r"\s+", " ", title)[:200]
    return ParsedPage(url=url, title=title, links=parser.links, paragraphs=parser.paragraphs)


def classify_kind(title: str, summary: str, hint: str = "news") -> str:
    blob = f"{title} {summary}"
    promo_hits = sum(1 for kw in PROMO_KEYWORDS if kw in blob)
    policy_hits = sum(1 for kw in POLICY_KEYWORDS if kw in blob)
    if promo_hits and promo_hits >= policy_hits:
        return "promo"
    if policy_hits:
        return "policy"
    if hint in {"policy", "promo", "news"}:
        return hint
    return "news"


def _content_hash(title: str, summary: str, url: str) -> str:
    raw = f"{title.strip()}|{summary.strip()}|{url.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_published_at(*texts: str) -> datetime | None:
    for text in texts:
        match = _DATE_RE.search(text or "")
        if not match:
            continue
        try:
            return datetime(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                tzinfo=timezone.utc,
            )
        except ValueError:
            continue
    return None


def _same_host(left: str, right: str) -> bool:
    return (urlparse(left).hostname or "").lower() == (urlparse(right).hostname or "").lower()


def _absolute(base: str, href: str) -> str | None:
    joined = urljoin(base, href.split("#", 1)[0].strip())
    if not _is_safe_url(joined):
        return None
    return joined


def load_sources(db: Session | None = None) -> list[dict[str, Any]]:
    sources = [dict(item) for item in DEFAULT_SOURCES]
    extra_raw = ""
    try:
        from app.services.settings_store import get_setting

        extra_raw = (get_setting("platform_intel_sources_json", db) or "").strip()
    except Exception:  # noqa: BLE001
        extra_raw = ""
    if extra_raw:
        try:
            extra = json.loads(extra_raw)
        except json.JSONDecodeError:
            extra = []
        if isinstance(extra, list):
            for row in extra:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "").strip()
                if not _is_safe_url(url):
                    continue
                sources.append(
                    {
                        "platform": str(row.get("platform") or "unknown")[:32],
                        "name": str(row.get("name") or url)[:120],
                        "url": url,
                        "kind_hint": str(row.get("kind_hint") or "news")[:24],
                        "follow_links": bool(row.get("follow_links")),
                        "link_contains": str(row.get("link_contains") or ""),
                    }
                )
    return sources


def _upsert_item(
    db: Session,
    *,
    platform: str,
    kind: str,
    title: str,
    url: str,
    summary: str,
    source_name: str,
    source_url: str,
    published_at: datetime | None,
) -> str:
    title = (title or url)[:300]
    summary = (summary or "")[:800]
    digest = _content_hash(title, summary, url)
    existing = db.execute(select(PlatformIntelItem).where(PlatformIntelItem.url == url)).scalar_one_or_none()
    now = utc_now()
    if existing is None:
        db.add(
            PlatformIntelItem(
                platform=platform,
                kind=kind,
                title=title,
                url=url,
                summary=summary or None,
                source_name=source_name,
                source_url=source_url,
                content_hash=digest,
                published_at=published_at,
                fetched_at=now,
                status="active",
            )
        )
        return "new"
    if existing.content_hash == digest:
        existing.fetched_at = now
        existing.status = "active"
        return "same"
    existing.platform = platform
    existing.kind = kind
    existing.title = title
    existing.summary = summary or None
    existing.source_name = source_name
    existing.source_url = source_url
    existing.content_hash = digest
    existing.published_at = published_at or existing.published_at
    existing.fetched_at = now
    existing.status = "active"
    return "updated"


def _collect_source(
    db: Session,
    source: dict[str, Any],
    fetch: FetchFn,
) -> dict[str, Any]:
    url = source["url"]
    name = source["name"]
    platform = source["platform"]
    hint = source.get("kind_hint") or "news"
    result = {"source": name, "url": url, "status": "ok", "items": 0, "error": None}
    try:
        status, _ctype, body, final_url = fetch(url)
        if status >= 400:
            raise IntelFetchError(f"HTTP {status} {url}")
        page = parse_html(final_url, body)
        pages: list[ParsedPage] = [page]
        if source.get("follow_links"):
            needle = str(source.get("link_contains") or "")
            seen: set[str] = {final_url.rstrip("/")}
            for href, link_text in page.links:
                if len(pages) > MAX_FOLLOW_LINKS:
                    break
                abs_url = _absolute(final_url, href)
                if abs_url is None or abs_url.rstrip("/") in seen:
                    continue
                if not _same_host(final_url, abs_url):
                    continue
                if needle and needle not in abs_url:
                    continue
                seen.add(abs_url.rstrip("/"))
                try:
                    child_status, _, child_body, child_final = fetch(abs_url)
                    if child_status >= 400:
                        continue
                    child = parse_html(child_final, child_body)
                    if not child.title:
                        child.title = link_text
                    pages.append(child)
                except IntelFetchError:
                    continue
        for item in pages:
            title = item.title or name
            summary = item.summary
            if item is page and not summary and item.links:
                summary = "；".join(text for _, text in item.links[:8])[:400]
            if len(title) < 4 and len(summary) < 12:
                continue
            kind = classify_kind(title, summary, hint)
            change = _upsert_item(
                db,
                platform=platform,
                kind=kind,
                title=title,
                url=item.url,
                summary=summary,
                source_name=name,
                source_url=url,
                published_at=_parse_published_at(title, summary),
            )
            result["items"] += 1
            if change == "new":
                result["new"] = int(result.get("new") or 0) + 1
            elif change == "updated":
                result["updated"] = int(result.get("updated") or 0) + 1
        if result["items"] == 0 and page.title:
            change = _upsert_item(
                db,
                platform=platform,
                kind=classify_kind(page.title, page.summary, hint),
                title=page.title,
                url=final_url,
                summary=page.summary or f"已访问公开页「{name}」，正文过短，未抽到政策/活动条目。",
                source_name=name,
                source_url=url,
                published_at=None,
            )
            result["items"] = 1
            result[change] = int(result.get(change) or 0) + 1
    except IntelFetchError as exc:
        result["status"] = "failed"
        result["error"] = str(exc)
        logger.info("platform intel source failed: %s", exc)
    return result


def collect_official_intel(
    db: Session,
    *,
    store_id: str | None = None,
    fetch: FetchFn | None = None,
) -> dict[str, Any]:
    fetch_fn = fetch or default_fetch
    sources = load_sources(db)
    run = PlatformIntelRun(
        status="running",
        source_count=len(sources),
        fetched_count=0,
        new_count=0,
        updated_count=0,
    )
    db.add(run)
    db.flush()
    details: list[dict[str, Any]] = []
    errors: list[str] = []
    for source in sources:
        row = _collect_source(db, source, fetch_fn)
        details.append(row)
        run.fetched_count += int(row.get("items") or 0)
        run.new_count += int(row.get("new") or 0)
        run.updated_count += int(row.get("updated") or 0)
        if row.get("error"):
            errors.append(str(row["error"]))
    projected = 0
    if store_id:
        projected = project_promos_to_store(db, store_id)
    run.completed_at = utc_now()
    if errors and run.fetched_count == 0:
        run.status = "failed"
        run.error = "；".join(errors[:4])
    elif errors:
        run.status = "completed_with_errors"
        run.error = "；".join(errors[:4])
    else:
        run.status = "completed"
        run.error = None
    run.detail_json = json.dumps(details, ensure_ascii=False)[:8000]
    db.commit()
    db.refresh(run)
    return serialize_run(run, projected=projected, details=details)


def serialize_run(run: PlatformIntelRun, *, projected: int = 0, details: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload = {
        "run_id": run.id,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "source_count": run.source_count,
        "fetched_count": run.fetched_count,
        "new_count": run.new_count,
        "updated_count": run.updated_count,
        "error": run.error,
        "projected_campaigns": projected,
    }
    if details is not None:
        payload["sources"] = details
    return payload


def serialize_item(item: PlatformIntelItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "platform": item.platform,
        "kind": item.kind,
        "title": item.title,
        "url": item.url,
        "summary": item.summary,
        "source_name": item.source_name,
        "source_url": item.source_url,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "fetched_at": item.fetched_at.isoformat() if item.fetched_at else None,
        "status": item.status,
    }


def list_intel(
    db: Session,
    *,
    kind: str | None = None,
    platform: str | None = None,
    limit: int = 30,
) -> list[PlatformIntelItem]:
    stmt = select(PlatformIntelItem).where(PlatformIntelItem.status == "active")
    if kind:
        stmt = stmt.where(PlatformIntelItem.kind == kind)
    if platform:
        stmt = stmt.where(PlatformIntelItem.platform == platform)
    stmt = stmt.order_by(PlatformIntelItem.fetched_at.desc()).limit(max(1, min(limit, 100)))
    return list(db.execute(stmt).scalars())


def latest_run(db: Session) -> PlatformIntelRun | None:
    return db.execute(select(PlatformIntelRun).order_by(PlatformIntelRun.started_at.desc()).limit(1)).scalar_one_or_none()


def project_for_demand(db: Session, limit: int = 6) -> dict[str, Any]:
    items = list_intel(db, limit=40)
    run = latest_run(db)
    promos = [serialize_item(item) for item in items if item.kind == "promo"][:limit]
    policies = [serialize_item(item) for item in items if item.kind == "policy"][:limit]
    news = [serialize_item(item) for item in items if item.kind == "news"][:limit]
    status = "ok" if (promos or policies or news) else "empty"
    if run and run.status == "failed" and status == "empty":
        status = "failed"
    return {
        "official_promos": promos,
        "official_policies": policies,
        "official_news": news,
        "intel_status": status,
        "intel_run_error": run.error if run else None,
        "intel_fetched_at": run.completed_at.isoformat() if run and run.completed_at else None,
    }


def project_promos_to_store(db: Session, store_id: str) -> int:
    """把官网促销投影到本店活动表。不编造补贴数字，状态为 unknown。"""
    store = db.get(Store, store_id)
    if store is None:
        return 0
    promos = list_intel(db, kind="promo", limit=20)
    written = 0
    for item in promos:
        existing = db.execute(
            select(CampaignRecord).where(
                CampaignRecord.store_id == store_id,
                CampaignRecord.intel_item_id == item.id,
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = db.execute(
                select(CampaignRecord).where(
                    CampaignRecord.store_id == store_id,
                    CampaignRecord.source == "official_web",
                    CampaignRecord.name == item.title,
                    CampaignRecord.platform == item.platform,
                )
            ).scalar_one_or_none()
        if existing is None:
            db.add(
                CampaignRecord(
                    store_id=store_id,
                    platform=item.platform,
                    name=item.title[:200],
                    campaign_type="official_web",
                    status="unknown",
                    source="official_web",
                    confidence="low",
                    source_url=item.url,
                    intel_item_id=item.id,
                )
            )
            written += 1
            continue
        existing.source_url = item.url
        existing.intel_item_id = item.id
        existing.source = "official_web"
        if existing.status in {"", None}:
            existing.status = "unknown"
    return written


def schedule_label() -> str:
    return f"{settings.platform_intel_hour:02d}:{settings.platform_intel_minute:02d}"
