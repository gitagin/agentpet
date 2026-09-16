from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Literal, Mapping, Sequence
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.utils.hash import sha256_hex
from app.utils.time import local_timezone


RETRIEVAL_PLAN_VERSION = "retrieval-plan.v1"
RETRIEVAL_PLAN_TELEMETRY_VERSION = "retrieval-plan-telemetry.v1"
MAX_QUERY_CHARS = 2_000
MAX_SEMANTIC_VARIANTS = 3
MAX_FILTERS = 8
# 检索"今天/昨天"等相对日期按本机时区解释；常量保留为文档化缺省。
DEFAULT_RETRIEVAL_TIMEZONE = "Asia/Shanghai"


def _current_local_tz():
    # 每次取值而不是模块级冻结：fixed-offset tz 在 DST 切换后的长驻进程里
    # 日期锚定会漂移 1 小时，动态取本机 tz 保证"今天"始终是本机今天。
    return local_timezone()

RetrievalSourceScope = Literal[
    "personal_memory",
    "diary",
    "daily_chat",
    "wiki",
    "vault_note",
    "graph",
]
RetrievalChannel = Literal[
    "fts",
    "vector",
    "active_memory",
    "diary",
    "daily_chat",
    "graph",
]

DEFAULT_SOURCE_SCOPES: tuple[RetrievalSourceScope, ...] = (
    "personal_memory",
    "diary",
    "daily_chat",
    "wiki",
    "vault_note",
    "graph",
)
DEFAULT_REQUESTED_CHANNELS: tuple[RetrievalChannel, ...] = ("fts",)
_ALLOWED_FILTER_KEYS = {
    "date_field",
    "language",
    "lifecycle_status",
    "source_type",
    "status",
    "vault_id",
}

_QUOTED_PATTERNS = (
    re.compile(r'"([^"\r\n]{1,256})"'),
    re.compile(r"“([^”\r\n]{1,256})”"),
    re.compile(r"‘([^’\r\n]{1,256})’"),
    re.compile(r"「([^」\r\n]{1,256})」"),
    re.compile(r"『([^』\r\n]{1,256})』"),
    re.compile(r"(?<!\w)'([^'\r\n]{1,256})'(?!\w)"),
)
_IDENTIFIER_RE = re.compile(
    r"(?<![\w-])(?=[A-Za-z0-9_-]{2,64}(?![\w-]))"
    r"(?=[A-Za-z0-9_-]*[A-Za-z])(?=[A-Za-z0-9_-]*\d)"
    r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*(?![\w-])"
)
_UUID_RE = re.compile(
    r"(?<![0-9A-Fa-f])"
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[1-5][0-9A-Fa-f]{3}-"
    r"[89ABab][0-9A-Fa-f]{3}-[0-9A-Fa-f]{12}"
    r"(?![0-9A-Fa-f])"
)
_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)")
_ZH_FULL_DATE_RE = re.compile(r"(?<!\d)(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号](?!\d)")
_ZH_MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号](?!\d)")
_LATIN_ENTITY_RE = re.compile(
    r"(?<![\w-])(?:[A-Z][A-Za-z]{1,31}|[A-Z]{2,16})"
    r"(?:\s+(?:[A-Z][A-Za-z]{1,31}|[A-Z]{2,16})){0,3}(?![\w-])"
)
_ZH_CONTEXT_ENTITY_RE = re.compile(
    r"(?:关于|查询|查找|找|记得|和|与)([\u4e00-\u9fff]{2,4})(?=的|在|说|提到|，|。|？|\s|$)"
)
_ZH_NAME_RE = re.compile(
    r"((?:欧阳|司马|上官|诸葛|[赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    r"戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉岑薛雷贺倪汤"
    r"滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵汪祁毛禹狄米贝明臧"
    r"计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱"
    r"骆高夏蔡田樊胡凌霍虞万支柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉钮"
    r"龚程嵇邢滑裴陆荣翁荀羊甄曲封芮储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗"
    r"班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲台从鄂索"
    r"咸籍赖卓蔺屠蒙池乔阴郁胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍郤璩桑桂濮牛寿通"
    r"边扈燕冀浦尚农温别庄晏柴瞿阎充慕连茹习艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡"
    r"国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰"
    r"巢关蒯相查后荆红游竺权逯盖益桓公])[\u4e00-\u9fff]{1,2})"
    r"(?=的|在|说|提到|认为|决定|，|。|？|\s|$)"
)
_PRONOUN_PATTERNS = (
    re.compile(r"(?<!其)(?:他们|她们|那个项目|这个项目|他|她|它)"),
    re.compile(r"\b(?:he|she|they|it|that project|this project)\b", re.IGNORECASE),
)
_ENTITY_STOPWORDS = {
    "Find",
    "Please",
    "Remember",
    "Search",
    "Show",
    "Tell",
    "What",
    "When",
    "Where",
    "Who",
}


class RetrievalDateRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: date
    end: date
    expressions: tuple[str, ...] = Field(default_factory=tuple, max_length=4)

    @field_validator("expressions")
    @classmethod
    def _validate_expressions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _bounded_unique(value, max_items=4, max_chars=64)

    @model_validator(mode="after")
    def _validate_order(self) -> "RetrievalDateRange":
        if self.end < self.start:
            raise ValueError("retrieval_date_range_reversed")
        return self


class ApprovedRetrievalContext(BaseModel):
    """Narrow context that is approved solely for reference resolution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    referent: str | None = Field(default=None, max_length=128)
    reference_date: date | None = None

    @field_validator("referent")
    @classmethod
    def _normalize_referent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalize_text(value)
        return normalized or None


class RetrievalPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["retrieval-plan.v1"] = RETRIEVAL_PLAN_VERSION
    lexical_query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    semantic_variants: tuple[str, ...] = Field(default_factory=tuple, max_length=MAX_SEMANTIC_VARIANTS)
    exact_terms: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    identifiers: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    entities: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    date_range: RetrievalDateRange | None = None
    source_scopes: tuple[RetrievalSourceScope, ...] = Field(min_length=1, max_length=6)
    filters: dict[str, str] = Field(default_factory=dict)
    requested_channels: tuple[RetrievalChannel, ...] = Field(min_length=1, max_length=6)
    confidence: float = Field(ge=0.0, le=1.0)
    planner_source: Literal["deterministic", "validated_model"]
    fallback_reason: Literal["model_output_unavailable", "model_output_invalid"] | None = None
    context_resolution_count: int = Field(default=0, ge=0, le=2)
    privacy_filtered_channel_count: int = Field(default=0, ge=0, le=1)

    @field_validator("lexical_query")
    @classmethod
    def _normalize_lexical_query(cls, value: str) -> str:
        normalized = _normalize_text(value)
        if not normalized:
            raise ValueError("retrieval_query_empty")
        return normalized

    @field_validator("semantic_variants")
    @classmethod
    def _validate_variants(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _bounded_unique(value, max_items=MAX_SEMANTIC_VARIANTS, max_chars=512)

    @field_validator("exact_terms", "identifiers", "entities")
    @classmethod
    def _validate_atoms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _bounded_unique(value, max_items=16, max_chars=256)

    @field_validator("source_scopes", "requested_channels")
    @classmethod
    def _validate_enum_sequence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique(value)

    @field_validator("filters")
    @classmethod
    def _validate_filters(cls, value: dict[str, str]) -> dict[str, str]:
        return _normalize_filters(value)


class RetrievalPlanTelemetry(BaseModel):
    """Safe projection: hashes, counts, and no query/context values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["retrieval-plan-telemetry.v1"] = RETRIEVAL_PLAN_TELEMETRY_VERSION
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_context_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    semantic_variant_count: int = Field(ge=0, le=MAX_SEMANTIC_VARIANTS)
    exact_term_count: int = Field(ge=0)
    identifier_count: int = Field(ge=0)
    entity_count: int = Field(ge=0)
    date_expression_count: int = Field(ge=0)
    source_scope_count: int = Field(ge=1)
    filter_count: int = Field(ge=0, le=MAX_FILTERS)
    requested_channel_count: int = Field(ge=1)
    context_resolution_count: int = Field(ge=0, le=2)
    model_output_used_count: int = Field(ge=0, le=1)
    deterministic_fallback_count: int = Field(ge=0, le=1)
    privacy_filtered_channel_count: int = Field(ge=0, le=1)


class _ModelPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lexical_query: str | None = Field(default=None, min_length=1, max_length=MAX_QUERY_CHARS)
    semantic_variants: tuple[str, ...] = Field(default_factory=tuple, max_length=MAX_SEMANTIC_VARIANTS)
    exact_terms: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    identifiers: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    entities: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    date_range: RetrievalDateRange | None = None
    source_scopes: tuple[RetrievalSourceScope, ...] = Field(default_factory=tuple, max_length=6)
    filters: dict[str, str] = Field(default_factory=dict)
    requested_channels: tuple[RetrievalChannel, ...] = Field(default_factory=tuple, max_length=6)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)

    @field_validator("lexical_query")
    @classmethod
    def _normalize_optional_query(cls, value: str | None) -> str | None:
        return _normalize_text(value) if value is not None else None

    @field_validator("semantic_variants")
    @classmethod
    def _validate_model_variants(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _bounded_unique(value, max_items=MAX_SEMANTIC_VARIANTS, max_chars=512)

    @field_validator("exact_terms", "identifiers", "entities")
    @classmethod
    def _validate_model_atoms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _bounded_unique(value, max_items=16, max_chars=256)

    @field_validator("source_scopes", "requested_channels")
    @classmethod
    def _validate_model_enums(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique(value)

    @field_validator("filters")
    @classmethod
    def _validate_model_filters(cls, value: dict[str, str]) -> dict[str, str]:
        return _normalize_filters(value)


class RetrievalQueryPlanner:
    def plan(
        self,
        query: str,
        *,
        approved_context: ApprovedRetrievalContext | None = None,
        model_output: str | Mapping[str, Any] | None = None,
        approved_source_scopes: Sequence[RetrievalSourceScope] | None = None,
        requested_channels: Sequence[RetrievalChannel] | None = None,
        filters: Mapping[str, str] | None = None,
        local_privacy: bool = False,
        sensitive: bool = False,
        now: date | datetime | None = None,
    ) -> RetrievalPlan:
        lexical_query = _normalize_query(query)
        context = approved_context or ApprovedRetrievalContext()
        anchor_date = _anchor_date(context, now)
        exact_terms = _extract_quoted_terms(lexical_query)
        identifiers = _extract_identifiers(lexical_query)
        entities = _extract_entities(lexical_query, exact_terms=exact_terms)
        date_range = _extract_date_range(lexical_query, anchor_date=anchor_date)
        scopes = _approved_scopes(approved_source_scopes, lexical_query, date_range)
        channel_cap = _approved_channels(requested_channels)
        caller_filters = _normalize_filters(dict(filters or {}))
        resolved_variants, context_resolution_count = _context_variants(
            lexical_query,
            context=context,
            date_range=date_range,
        )

        draft: _ModelPlanDraft | None = None
        fallback_reason: Literal["model_output_unavailable", "model_output_invalid"] | None
        if model_output is None:
            fallback_reason = "model_output_unavailable"
        else:
            try:
                draft = _parse_model_output(model_output)
                _validate_model_preservation(
                    draft,
                    lexical_query=lexical_query,
                    exact_terms=exact_terms,
                    identifiers=identifiers,
                    entities=entities,
                    deterministic_date_range=date_range,
                    approved_context=context,
                )
                fallback_reason = None
            except (TypeError, ValueError):
                draft = None
                fallback_reason = "model_output_invalid"

        variants = list(resolved_variants)
        final_entities = list(entities)
        if context.referent and any(context.referent in variant for variant in resolved_variants):
            final_entities.append(context.referent)
        final_date_range = date_range
        final_scopes = scopes
        final_channels = channel_cap
        merged_filters: dict[str, str] = {}
        confidence = 0.55

        if draft is not None:
            variants.extend(draft.semantic_variants)
            final_entities.extend(draft.entities)
            if final_date_range is None:
                final_date_range = draft.date_range
            if draft.source_scopes:
                final_scopes = tuple(scope for scope in draft.source_scopes if scope in scopes) or scopes
            if draft.requested_channels:
                final_channels = tuple(channel for channel in draft.requested_channels if channel in channel_cap) or channel_cap
            merged_filters.update(draft.filters)
            confidence = draft.confidence

        merged_filters.update(caller_filters)
        protected_atoms = _protected_atoms(
            exact_terms=exact_terms,
            identifiers=identifiers,
            entities=entities,
            date_range=final_date_range,
        )
        variants = [
            variant
            for variant in _bounded_unique(variants, max_items=MAX_SEMANTIC_VARIANTS, max_chars=512)
            if variant != lexical_query and _preserves_atoms(variant, protected_atoms)
        ][:MAX_SEMANTIC_VARIANTS]

        privacy_filtered = 0
        if local_privacy or sensitive:
            without_vector = tuple(channel for channel in final_channels if channel != "vector")
            privacy_filtered = int(len(without_vector) != len(final_channels))
            final_channels = without_vector or ("fts",)
            if "fts" not in final_channels:
                final_channels = ("fts", *final_channels)

        return RetrievalPlan(
            lexical_query=lexical_query,
            semantic_variants=tuple(variants),
            exact_terms=exact_terms,
            identifiers=identifiers,
            entities=_bounded_unique(final_entities, max_items=16, max_chars=256),
            date_range=final_date_range,
            source_scopes=final_scopes,
            filters=merged_filters,
            requested_channels=final_channels,
            confidence=confidence,
            planner_source="validated_model" if draft is not None else "deterministic",
            fallback_reason=fallback_reason,
            context_resolution_count=context_resolution_count,
            privacy_filtered_channel_count=privacy_filtered,
        )


def build_retrieval_plan(
    query: str,
    **kwargs: Any,
) -> RetrievalPlan:
    return RetrievalQueryPlanner().plan(query, **kwargs)


def retrieval_today(now: date | datetime | None = None) -> date:
    """Date anchor for relative-date queries.

    Shared by the planner and the retrieval cache key so a cached "昨天"
    answer can never survive past midnight.
    """
    return _anchor_date(ApprovedRetrievalContext(), now)


_GRAPH_INTENT_MARKERS = (
    "关系",
    "相关",
    "和谁",
    "跟谁",
    "与谁",
    "负责",
    "属于",
    "连接",
    "联系",
    "之间",
    "关联",
    "认识",
)
_GRAPH_INTENT_RE = re.compile(
    r"\b(?:relat\w+|connect\w+|owned by|belongs to|associated with|linked to)\b",
    re.IGNORECASE,
)


def route_retrieval_channels(
    base_channels: Sequence[RetrievalChannel],
    query: str,
) -> tuple[RetrievalChannel, ...]:
    """Deterministic routing rules that adjust channels before planning.

    Relation markers add the graph channel, which resolves entity ids
    and traverses the SQLite-authoritative graph.  Graph retrieval is
    scoped to relational/multi-hop queries; applying it to every query
    only adds latency and noise.

    Exact-identifier queries keep their channels: production evidence
    routes them past query expansion, not past semantic recall — this
    codebase has no expansion layer, so there is nothing to bypass.
    """
    channels = _unique(tuple(base_channels)) or ("fts",)
    has_graph_intent = any(marker in query for marker in _GRAPH_INTENT_MARKERS) or bool(
        _GRAPH_INTENT_RE.search(query)
    )
    if has_graph_intent and "graph" not in channels:
        channels = (*channels, "graph")
    return channels


def build_retrieval_plan_telemetry(
    plan: RetrievalPlan,
    *,
    original_query: str,
    approved_context: ApprovedRetrievalContext | None = None,
) -> RetrievalPlanTelemetry:
    context_hash = None
    if approved_context is not None:
        context_payload = json.dumps(
            approved_context.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        context_hash = sha256_hex(f"retrieval-plan-context.v1\n{context_payload}")
    return RetrievalPlanTelemetry(
        query_hash=sha256_hex(f"retrieval-plan-query.v1\n{_normalize_query(original_query)}"),
        approved_context_hash=context_hash,
        semantic_variant_count=len(plan.semantic_variants),
        exact_term_count=len(plan.exact_terms),
        identifier_count=len(plan.identifiers),
        entity_count=len(plan.entities),
        date_expression_count=len(plan.date_range.expressions) if plan.date_range else 0,
        source_scope_count=len(plan.source_scopes),
        filter_count=len(plan.filters),
        requested_channel_count=len(plan.requested_channels),
        context_resolution_count=plan.context_resolution_count,
        model_output_used_count=int(plan.planner_source == "validated_model"),
        deterministic_fallback_count=int(plan.planner_source == "deterministic"),
        privacy_filtered_channel_count=plan.privacy_filtered_channel_count,
    )


def _normalize_query(query: str) -> str:
    normalized = _normalize_text(query)
    if not normalized:
        raise ValueError("retrieval_query_empty")
    if len(normalized) > MAX_QUERY_CHARS:
        raise ValueError("retrieval_query_too_long")
    return normalized


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _bounded_unique(values: Sequence[str], *, max_items: int, max_chars: int) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise ValueError("retrieval_plan_text_value_invalid")
        item = _normalize_text(raw)
        if not item:
            continue
        if len(item) > max_chars:
            raise ValueError("retrieval_plan_text_value_too_long")
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)
        if len(normalized) > max_items:
            raise ValueError("retrieval_plan_item_limit_exceeded")
    return tuple(normalized)


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    unique: list[str] = []
    for item in values:
        if item not in unique:
            unique.append(item)
    return tuple(unique)


def _normalize_filters(filters: Mapping[str, str]) -> dict[str, str]:
    if len(filters) > MAX_FILTERS:
        raise ValueError("retrieval_filter_limit_exceeded")
    normalized: dict[str, str] = {}
    for raw_key, raw_value in filters.items():
        key = _normalize_text(str(raw_key))
        if key not in _ALLOWED_FILTER_KEYS:
            raise ValueError("retrieval_filter_key_invalid")
        value = _normalize_text(str(raw_value))
        if not value or len(value) > 128:
            raise ValueError("retrieval_filter_value_invalid")
        normalized[key] = value
    return normalized


def _extract_quoted_terms(query: str) -> tuple[str, ...]:
    located: list[tuple[int, str]] = []
    for pattern in _QUOTED_PATTERNS:
        located.extend((match.start(), match.group(1)) for match in pattern.finditer(query))
    located.sort(key=lambda item: item[0])
    return _bounded_unique([value for _, value in located], max_items=16, max_chars=256)


def _extract_identifiers(query: str) -> tuple[str, ...]:
    located = [(match.start(), match.group(0)) for match in _IDENTIFIER_RE.finditer(query)]
    located.extend((match.start(), match.group(0)) for match in _UUID_RE.finditer(query))
    located.sort(key=lambda item: item[0])
    return _bounded_unique([value for _, value in located], max_items=16, max_chars=256)


def _extract_entities(query: str, *, exact_terms: Sequence[str]) -> tuple[str, ...]:
    located: list[tuple[int, str]] = []
    for term in exact_terms:
        offset = query.find(term)
        if offset >= 0:
            located.append((offset, term))
    for match in _LATIN_ENTITY_RE.finditer(query):
        value = match.group(0)
        parts = value.split()
        offset = match.start()
        while len(parts) > 1 and parts[0] in _ENTITY_STOPWORDS:
            offset += len(parts[0]) + 1
            parts.pop(0)
        value = " ".join(parts)
        if value not in _ENTITY_STOPWORDS:
            located.append((offset, value))
    located.extend((match.start(1), match.group(1)) for match in _ZH_CONTEXT_ENTITY_RE.finditer(query))
    located.extend((match.start(1), match.group(1)) for match in _ZH_NAME_RE.finditer(query))
    located.sort(key=lambda item: item[0])
    return _bounded_unique([value for _, value in located], max_items=16, max_chars=256)


def _anchor_date(context: ApprovedRetrievalContext, now: date | datetime | None) -> date:
    if context.reference_date is not None:
        return context.reference_date
    if isinstance(now, datetime):
        current = now if now.tzinfo is not None else now.replace(tzinfo=_current_local_tz())
        return current.astimezone(_current_local_tz()).date()
    if isinstance(now, date):
        return now
    return datetime.now(_current_local_tz()).date()


def _extract_date_range(query: str, *, anchor_date: date) -> RetrievalDateRange | None:
    located: list[tuple[int, date, str]] = []
    full_spans: list[tuple[int, int]] = []
    for pattern in (_ISO_DATE_RE, _ZH_FULL_DATE_RE):
        for match in pattern.finditer(query):
            parsed = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            if parsed is not None:
                located.append((match.start(), parsed, match.group(0)))
                full_spans.append(match.span())
    for match in _ZH_MONTH_DAY_RE.finditer(query):
        if any(start <= match.start() and match.end() <= end for start, end in full_spans):
            continue
        parsed = _safe_date(anchor_date.year, int(match.group(1)), int(match.group(2)))
        if parsed is not None:
            located.append((match.start(), parsed, match.group(0)))
    if located:
        located.sort(key=lambda item: item[0])
        return RetrievalDateRange(
            start=located[0][1],
            end=located[-1][1],
            expressions=tuple(item[2] for item in located),
        )

    lowered = query.casefold()
    relative: tuple[date, date, str] | None = None
    if "前天" in query or "day before yesterday" in lowered:
        target = anchor_date - timedelta(days=2)
        relative = (target, target, "前天" if "前天" in query else "day before yesterday")
    elif "后天" in query or "day after tomorrow" in lowered:
        target = anchor_date + timedelta(days=2)
        relative = (target, target, "后天" if "后天" in query else "day after tomorrow")
    elif "昨天" in query or re.search(r"\byesterday\b", lowered):
        target = anchor_date - timedelta(days=1)
        relative = (target, target, "昨天" if "昨天" in query else "yesterday")
    elif "明天" in query or re.search(r"\btomorrow\b", lowered):
        target = anchor_date + timedelta(days=1)
        relative = (target, target, "明天" if "明天" in query else "tomorrow")
    elif "今天" in query or "今日" in query or re.search(r"\btoday\b", lowered):
        expression = "今天" if "今天" in query else "今日" if "今日" in query else "today"
        relative = (anchor_date, anchor_date, expression)
    elif "上周" in query or "上星期" in query or "last week" in lowered:
        this_monday = anchor_date - timedelta(days=anchor_date.weekday())
        expression = "上周" if "上周" in query else "上星期" if "上星期" in query else "last week"
        relative = (this_monday - timedelta(days=7), this_monday - timedelta(days=1), expression)
    elif "本周" in query or "这周" in query or "this week" in lowered:
        this_monday = anchor_date - timedelta(days=anchor_date.weekday())
        expression = "本周" if "本周" in query else "这周" if "这周" in query else "this week"
        relative = (this_monday, this_monday + timedelta(days=6), expression)
    if relative is None:
        return None
    return RetrievalDateRange(start=relative[0], end=relative[1], expressions=(relative[2],))


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _approved_scopes(
    approved: Sequence[RetrievalSourceScope] | None,
    query: str,
    date_range: RetrievalDateRange | None,
) -> tuple[RetrievalSourceScope, ...]:
    if approved is not None:
        scopes = _unique(tuple(approved))
        if not scopes:
            raise ValueError("retrieval_source_scopes_empty")
        return scopes  # type: ignore[return-value]
    lowered = query.casefold()
    if date_range is not None or any(marker in query for marker in ("日记", "聊天记录", "回忆")):
        return ("daily_chat", "diary", "personal_memory")
    if any(marker in query for marker in ("知识库", "文档", "笔记")) or "docs" in lowered:
        return ("wiki", "vault_note")
    if any(marker in query for marker in ("我喜欢", "我的偏好", "你记得我", "记得我")):
        return ("personal_memory",)
    return DEFAULT_SOURCE_SCOPES


def _approved_channels(approved: Sequence[RetrievalChannel] | None) -> tuple[RetrievalChannel, ...]:
    channels = _unique(tuple(approved)) if approved is not None else DEFAULT_REQUESTED_CHANNELS
    if not channels:
        raise ValueError("retrieval_channels_empty")
    return channels  # type: ignore[return-value]


def _context_variants(
    query: str,
    *,
    context: ApprovedRetrievalContext,
    date_range: RetrievalDateRange | None,
) -> tuple[tuple[str, ...], int]:
    variants: list[str] = []
    resolution_count = 0
    if context.referent:
        resolved = query
        for pattern in _PRONOUN_PATTERNS:
            resolved, count = pattern.subn(context.referent, resolved, count=1)
            if count:
                variants.append(resolved)
                resolution_count += 1
                break
    if date_range is not None and date_range.expressions:
        expression = date_range.expressions[0]
        if expression in {
            "前天",
            "昨天",
            "今天",
            "今日",
            "明天",
            "后天",
            "day before yesterday",
            "yesterday",
            "today",
            "tomorrow",
            "day after tomorrow",
        }:
            resolved_date = date_range.start.isoformat()
            variants.append(query.replace(expression, f"{expression} ({resolved_date})", 1))
            resolution_count += 1
    return _bounded_unique(variants, max_items=2, max_chars=512), min(resolution_count, 2)


def _parse_model_output(output: str | Mapping[str, Any]) -> _ModelPlanDraft:
    if isinstance(output, str):
        start = output.find("{")
        end = output.rfind("}")
        if start < 0 or end < start:
            raise ValueError("retrieval_plan_json_missing")
        payload = json.loads(output[start : end + 1])
    elif isinstance(output, Mapping):
        payload = dict(output)
    else:
        raise TypeError("retrieval_plan_model_output_invalid")
    if not isinstance(payload, dict):
        raise ValueError("retrieval_plan_model_output_not_object")
    return _ModelPlanDraft.model_validate(payload)


def _validate_model_preservation(
    draft: _ModelPlanDraft,
    *,
    lexical_query: str,
    exact_terms: tuple[str, ...],
    identifiers: tuple[str, ...],
    entities: tuple[str, ...],
    deterministic_date_range: RetrievalDateRange | None,
    approved_context: ApprovedRetrievalContext,
) -> None:
    required = _protected_atoms(
        exact_terms=exact_terms,
        identifiers=identifiers,
        entities=entities,
        date_range=deterministic_date_range,
    )
    if draft.lexical_query is not None and not _preserves_atoms(draft.lexical_query, required):
        raise ValueError("retrieval_plan_model_replaced_exact_atom")
    if any(term not in exact_terms for term in draft.exact_terms):
        raise ValueError("retrieval_plan_model_invented_exact_term")
    if any(identifier not in identifiers for identifier in draft.identifiers):
        raise ValueError("retrieval_plan_model_invented_identifier")
    allowed_entities = {item.casefold() for item in entities}
    if approved_context.referent:
        allowed_entities.add(approved_context.referent.casefold())
    allowed_entities.update(term.casefold() for term in exact_terms)
    if any(entity.casefold() not in allowed_entities and entity not in lexical_query for entity in draft.entities):
        raise ValueError("retrieval_plan_model_invented_entity")
    if draft.date_range is not None:
        if deterministic_date_range is not None and draft.date_range != deterministic_date_range:
            raise ValueError("retrieval_plan_model_changed_date_range")
        if deterministic_date_range is None and (
            not draft.date_range.expressions
            or any(expression not in lexical_query for expression in draft.date_range.expressions)
        ):
            raise ValueError("retrieval_plan_model_invented_date_range")
    for variant in draft.semantic_variants:
        if not _preserves_atoms(variant, required):
            raise ValueError("retrieval_plan_variant_dropped_exact_atom")


def _protected_atoms(
    *,
    exact_terms: Sequence[str],
    identifiers: Sequence[str],
    entities: Sequence[str],
    date_range: RetrievalDateRange | None,
) -> tuple[str, ...]:
    atoms = [*exact_terms, *identifiers, *entities]
    if date_range is not None:
        atoms.extend(date_range.expressions)
    return _bounded_unique(atoms, max_items=48, max_chars=256)


def _preserves_atoms(text: str, atoms: Sequence[str]) -> bool:
    return all(contains_exact_retrieval_atom(text, atom) for atom in atoms)


def contains_exact_retrieval_atom(text: str, atom: str) -> bool:
    if not re.search(r"[A-Za-z0-9]", atom):
        return atom in text
    return (
        re.search(
            rf"(?<![A-Za-z0-9_-]){re.escape(atom)}(?![A-Za-z0-9_-])",
            text,
            re.IGNORECASE,
        )
        is not None
    )
