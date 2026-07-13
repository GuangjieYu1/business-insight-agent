"""Deterministic goal candidate generation for Phase 6B."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
import re
import unicodedata

from data_formulator.insight.domain import ClarificationOption, ClarificationQuestion, DatasetProfile, GoalCandidate, GoalFilter, GoalType

MAX_CANDIDATES = 4
MAX_PER_TYPE = 2
MAX_QUESTIONS = 2
FUZZY_THRESHOLD = 0.78
BLOCKING_ISSUES = {"empty_column", "constant_column", "near_constant_column", "high_cardinality_id_like"}

QUALITY_TERMS = ("数据有什么问题", "数据问题", "质量", "脏", "清洗", "缺失", "重复", "异常值", "quality", "dirty data")
TREND_TERMS = ("趋势", "变化", "增长", "下降", "最近", "近期", "环比", "同比", "trend", "recent", "growth", "decline")
DRIVER_TERMS = ("为什么", "原因", "驱动", "影响因素", "最重要", "driver", "reason", "factor")
COMPARE_TERMS = ("比较", "对比", "相比", "差异", "compare", "versus")
SEGMENT_TERMS = ("客户", "地区", "产品", "群体", "细分", "分群", "segment", "customer", "region", "product")
DISTRIBUTION_TERMS = ("分布", "离散", "偏态", "方差", "distribution", "spread", "variance")
TIME_ALIASES = ("日期", "时间", "月份", "季度", "年份", "date", "time", "month", "quarter", "year", "week", "day")
METRIC_CONCEPTS = {
    "revenue": ("收入", "营收", "销售额", "revenue", "sales", "sale", "gmv", "amount", "amt", "金额"),
    "profit": ("利润", "毛利", "净利", "profit", "margin"),
    "cost": ("成本", "费用", "cost", "expense"),
    "orders": ("订单", "订单量", "订单数", "orders", "order", "ordercount", "ordercnt"),
    "quantity": ("销量", "数量", "件数", "quantity", "qty", "volume", "units"),
}
DIMENSION_CONCEPTS = {
    "region": ("地区", "区域", "大区", "城市", "region", "area", "city"),
    "product": ("产品", "商品", "品类", "product", "item", "category"),
    "customer": ("客户", "用户", "客群", "customer", "client", "user"),
    "channel": ("渠道", "来源", "channel", "source"),
    "store": ("门店", "店铺", "store", "shop"),
}
CHINESE_NUMBERS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}


@dataclass(frozen=True)
class CandidateGenerationResult:
    candidates: list[GoalCandidate]
    questions: list[ClarificationQuestion]


@dataclass(frozen=True)
class RankedField:
    name: str
    role_tier: int
    match_priority: int
    concept_overlap: int
    fuzzy_score: float
    risks: tuple[str, ...]
    concepts: frozenset[str]

    @property
    def certainty(self) -> int:
        if self.match_priority >= 3 and self.role_tier >= 2:
            return 3
        if self.match_priority >= 2 and self.role_tier >= 1:
            return 2
        if self.match_priority >= 1 or self.role_tier >= 1:
            return 1
        return 0


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().lower()


def _compact(text: str) -> str:
    return re.sub(r"[\s_\-]+", "", _normalize(text))


def _ascii_tokens(text: str) -> tuple[str, ...]:
    return tuple(token for token in re.findall(r"[a-z0-9_]+", _normalize(text)) if token)


def _contains(compact_text: str, options: tuple[str, ...]) -> bool:
    return any(_compact(option) in compact_text for option in options)


def _concept_hits(text: str, concept_map: dict[str, tuple[str, ...]]) -> frozenset[str]:
    compact = _compact(text)
    hits: set[str] = set()
    for concept, aliases in concept_map.items():
        if any(_compact(alias) in compact for alias in aliases):
            hits.add(concept)
    return frozenset(hits)


def _dedupe_text(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item and item.strip()))


def _column_risks(column, role: str) -> tuple[str, ...]:
    issues = {str(issue) for issue in column.quality_issue_types}
    risks: list[str] = []
    if "high_missing_column" in issues:
        risks.append(f"列 {column.name} 缺失比例较高")
    if role == "target" and "numeric_parse_conflict" in issues:
        risks.append(f"列 {column.name} 存在数值解析冲突")
    if role == "time" and "datetime_parse_conflict" in issues:
        risks.append(f"列 {column.name} 存在日期解析冲突")
    if "mixed_type_column" in issues:
        risks.append(f"列 {column.name} 类型混杂")
    if "whitespace_pollution" in issues:
        risks.append(f"列 {column.name} 存在空白污染")
    if "dirty_character_column" in issues:
        risks.append(f"列 {column.name} 存在脏字符")
    if "high_cardinality_id_like" in issues:
        risks.append(f"列 {column.name} 更像标识列而非分析字段")
    if "meaningless_header_candidate" in issues or "invalid_header" in issues:
        risks.append(f"列 {column.name} 表头语义不稳定")
    return _dedupe_text(risks)

def _role_tier(column, role: str, concepts: frozenset[str]) -> int:
    issues = {str(issue) for issue in column.quality_issue_types}
    if issues & BLOCKING_ISSUES:
        return 0
    if role == "target":
        if column.inferred_type == "numeric" and "numeric_parse_conflict" not in issues:
            return 2
        if column.numeric_parseable_count > 0 and column.numeric_parse_conflict_count == 0:
            return 1
        return 1 if concepts else 0
    if role == "time":
        if column.inferred_type == "datetime" and "datetime_parse_conflict" not in issues:
            return 2
        if column.datetime_parseable_count > 0 and column.datetime_parse_conflict_count == 0:
            return 2 if _contains(_compact(column.name), TIME_ALIASES) else 1
        return 0
    if column.inferred_type in {"text", "boolean"}:
        return 2
    if column.inferred_type == "numeric" and column.distinct_count <= 50 and column.distinct_ratio <= 0.5:
        return 1
    return 1 if concepts else 0


def _column_match_priority(compact_query: str, name: str, concepts: frozenset[str], query_concepts: frozenset[str], ascii_tokens: tuple[str, ...], aliases: tuple[str, ...]) -> tuple[int, float]:
    compact_name = _compact(name)
    if compact_name and compact_name in compact_query:
        return 3, 1.0
    if query_concepts & concepts:
        return 2, 1.0
    best = 0.0
    options = {compact_name, *(_compact(alias) for alias in aliases)}
    for token in ascii_tokens:
        if len(token) < 3:
            continue
        compact_token = _compact(token)
        for option in options:
            if not option:
                continue
            best = max(best, SequenceMatcher(None, compact_token, option).ratio())
    return (1, best) if best >= FUZZY_THRESHOLD else (0, best)


def _rank_fields(query: str, profile: DatasetProfile, role: str) -> list[RankedField]:
    compact_query = _compact(query)
    ascii_tokens = _ascii_tokens(query)
    query_concepts = _concept_hits(query, METRIC_CONCEPTS if role == "target" else DIMENSION_CONCEPTS)
    ranked: list[RankedField] = []
    for column in profile.columns:
        if role == "target":
            concepts = _concept_hits(column.name, METRIC_CONCEPTS)
            aliases = tuple(alias for concept in concepts for alias in METRIC_CONCEPTS[concept])
        elif role == "dimension":
            concepts = _concept_hits(column.name, DIMENSION_CONCEPTS)
            aliases = tuple(alias for concept in concepts for alias in DIMENSION_CONCEPTS[concept])
        else:
            concepts = frozenset({"time"}) if _contains(_compact(column.name), TIME_ALIASES) else frozenset()
            aliases = TIME_ALIASES
        tier = _role_tier(column, role, concepts)
        match_priority, fuzzy = _column_match_priority(compact_query, column.name, concepts, query_concepts, ascii_tokens, aliases)
        if tier <= 0 and match_priority <= 0:
            continue
        ranked.append(RankedField(column.name, tier, match_priority, len(query_concepts & concepts), fuzzy, _column_risks(column, role), concepts))
    ranked.sort(key=lambda item: (item.match_priority, item.role_tier, item.concept_overlap, int(round(item.fuzzy_score * 1000)), item.name), reverse=True)
    return ranked


def _metric_ambiguous(fields: list[RankedField]) -> bool:
    return len(fields) >= 2 and fields[0].match_priority > 0 and (fields[0].match_priority, fields[0].role_tier, fields[0].concept_overlap) == (fields[1].match_priority, fields[1].role_tier, fields[1].concept_overlap)


def _time_ambiguous(fields: list[RankedField]) -> bool:
    return len(fields) >= 2 and (fields[0].match_priority, fields[0].role_tier) == (fields[1].match_priority, fields[1].role_tier) and fields[0].match_priority < 3


def _time_filter(user_input: str, time_column: str | None) -> GoalFilter | None:
    if time_column is None:
        return None
    normalized = _normalize(user_input)
    patterns = (
        (r"(?:最近|近)\s*([一二两三四五六七八九十十二\d]+)\s*个?月", "relative_last_n_months"),
        (r"(?:last|past)\s*(\d+)\s*months?", "relative_last_n_months"),
        (r"(?:最近|近)\s*([一二两三四五六七八九十十二\d]+)\s*个?周", "relative_last_n_weeks"),
        (r"(?:last|past)\s*(\d+)\s*weeks?", "relative_last_n_weeks"),
        (r"(?:最近|近)\s*([一二两三四五六七八九十十二\d]+)\s*个?季度", "relative_last_n_quarters"),
        (r"(?:最近|近)\s*([一二两三四五六七八九十十二\d]+)\s*年", "relative_last_n_years"),
    )
    for pattern, operator in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        raw = match.group(1)
        value = int(raw) if raw.isdigit() else CHINESE_NUMBERS.get(raw)
        if value is not None:
            return GoalFilter(column=time_column, operator=operator, value=value)
    return None


def _dimension_filters(user_input: str, profile: DatasetProfile) -> tuple[GoalFilter, ...]:
    compact_query = _compact(user_input)
    filters: list[GoalFilter] = []
    for column in profile.columns:
        if column.value_storage_policy != "stored":
            continue
        if _role_tier(column, "dimension", _concept_hits(column.name, DIMENSION_CONCEPTS)) <= 0:
            continue
        for item in column.top_values:
            value = item.get("value")
            if value is None:
                continue
            text = str(value).strip()
            if len(_compact(text)) >= 2 and _compact(text) in compact_query:
                filters.append(GoalFilter(column=column.name, operator="eq", value=text))
                break
    return tuple(filters)


def _clarification_questions(query: str, metric_fields: list[RankedField], time_fields: list[RankedField]) -> list[ClarificationQuestion]:
    compact_query = _compact(query)
    trend_requested = _contains(compact_query, TREND_TERMS)
    questions: list[ClarificationQuestion] = []
    if _metric_ambiguous(metric_fields):
        questions.append(ClarificationQuestion(text="请确认要分析的指标列", text_code="insight.metricQuestion", responseType="single_choice", options=[ClarificationOption(label=item.name, label_code="insight.column.option") for item in metric_fields[:4]]))
    if len(questions) < MAX_QUESTIONS and trend_requested and _time_ambiguous(time_fields):
        questions.append(ClarificationQuestion(text="请确认用于趋势分析的时间列", text_code="insight.timeQuestion", responseType="single_choice", options=[ClarificationOption(label=item.name, label_code="insight.column.option") for item in time_fields[:4]]))
    return questions[:MAX_QUESTIONS]


def _score(trigger_strength: int, target_certainty: int, time_certainty: int, dimension_certainty: int, missing_count: int, risk_count: int, goal_type: GoalType, title: str) -> tuple[int, int, int, int, int, int, str, str]:
    return (trigger_strength, target_certainty, time_certainty, dimension_certainty, -missing_count, -risk_count, goal_type.value, title)


def _confidence(score: tuple[int, int, int, int, int, int, str, str]) -> float:
    trigger_strength, target_certainty, time_certainty, dimension_certainty, missing_penalty, risk_penalty, _, _ = score
    value = 0.24 + min(trigger_strength, 6) * 0.08 + target_certainty * 0.11 + time_certainty * 0.06 + dimension_certainty * 0.05 + max(missing_penalty, -3) * 0.04 + max(risk_penalty, -3) * 0.02
    return max(0.15, min(0.95, round(value, 2)))


def _candidate_id(intent_id: str, goal_type: GoalType, target_metric: str | None, time_column: str | None, dimensions: tuple[str, ...]) -> str:
    payload = f"{intent_id}|{goal_type.value}|{target_metric or ''}|{time_column or ''}|{'|'.join(dimensions)}"
    return f"goal_candidate_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"

def _make_candidate(workspace_id: str, intent_id: str, dataset_id: str, dataset_version_id: str, goal_type: GoalType, title: str, description: str, target_metric: str | None, dimensions: tuple[str, ...], time_column: str | None, filters: tuple[GoalFilter, ...], missing_information: tuple[str, ...], assumptions: tuple[str, ...], score: tuple[int, int, int, int, int, int, str, str]) -> GoalCandidate:
    return GoalCandidate(id=_candidate_id(intent_id, goal_type, target_metric, time_column, dimensions), workspace_id=workspace_id, intent_id=intent_id, dataset_id=dataset_id, dataset_version_id=dataset_version_id, title=title, description=description, goal_type=goal_type, target_metric=target_metric, dimensions=list(dimensions), time_column=time_column, filters=list(filters), confidence=_confidence(score), assumptions=list(assumptions), missing_information=list(missing_information), requires_confirmation=True)


def generate_goal_candidates(*, workspace_id: str, intent_id: str, dataset_id: str, dataset_version_id: str, user_input: str, profile: DatasetProfile) -> CandidateGenerationResult:
    compact_query = _compact(user_input)
    asks_quality = _contains(compact_query, QUALITY_TERMS)
    asks_trend = _contains(compact_query, TREND_TERMS)
    asks_driver = _contains(compact_query, DRIVER_TERMS)
    asks_compare = _contains(compact_query, COMPARE_TERMS)
    asks_segment = _contains(compact_query, SEGMENT_TERMS)
    asks_distribution = _contains(compact_query, DISTRIBUTION_TERMS)

    metric_fields = _rank_fields(user_input, profile, "target")
    time_fields = _rank_fields(user_input, profile, "time")
    dimension_fields = _rank_fields(user_input, profile, "dimension")
    questions = _clarification_questions(user_input, metric_fields, time_fields)

    best_metric = metric_fields[0] if metric_fields else None
    best_time = time_fields[0] if time_fields else None
    best_dims = tuple(item.name for item in dimension_fields[:2])
    base_filters = list(_dimension_filters(user_input, profile))
    time_filter = _time_filter(user_input, best_time.name if best_time and best_time.role_tier > 0 else None)
    if time_filter is not None:
        base_filters.insert(0, time_filter)
    filters = tuple(base_filters)
    metric_ambiguous = _metric_ambiguous(metric_fields)
    target = best_metric.name if best_metric else None
    trusted_time = best_time.name if best_time and best_time.role_tier > 0 else None

    drafted: list[tuple[tuple[str, str | None, str | None], GoalCandidate, tuple[int, int, int, int, int, int, str, str]]] = []

    def add(goal_type: GoalType, title: str, description: str, *, target_metric: str | None, dimensions: tuple[str, ...] = (), time_column: str | None = None, filters_value: tuple[GoalFilter, ...] = (), missing: list[str] | None = None, assumptions: list[str] | None = None, trigger: int = 3, target_certainty: int = 0, time_certainty: int = 0, dimension_certainty: int = 0) -> None:
        missing_info = _dedupe_text(missing or [])
        assumption_info = _dedupe_text(assumptions or [])
        score = _score(trigger, target_certainty, time_certainty, dimension_certainty, len(missing_info), len(assumption_info), goal_type, title)
        candidate = _make_candidate(workspace_id, intent_id, dataset_id, dataset_version_id, goal_type, title, description, target_metric, dimensions, time_column, filters_value, missing_info, assumption_info, score)
        drafted.append(((goal_type.value, target_metric, time_column), candidate, score))

    if asks_trend and trusted_time is not None:
        missing = []
        assumptions = list(best_metric.risks if best_metric else ()) + list(best_time.risks if best_time else ())
        if target is None:
            missing.append("尚未识别出明确的数值指标列")
        if metric_ambiguous:
            missing.append("目标指标存在多个候选列，建议先确认具体指标")
        add(GoalType.TREND_ANALYSIS, f"分析{target or '核心指标'}的近期趋势", f"围绕 {trusted_time} 观察 {target or '核心指标'} 的时间变化，并结合当前版本的体检结果解释趋势可信度。", target_metric=target, time_column=trusted_time, filters_value=filters, missing=missing, assumptions=assumptions, trigger=6, target_certainty=best_metric.certainty if best_metric else 0, time_certainty=best_time.certainty if best_time else 0)
    elif asks_trend and target and best_dims:
        add(GoalType.COMPARISON, f"比较{target}在{best_dims[0]}上的差异", f"由于当前版本缺少可信时间列，先按 {best_dims[0]} 对 {target} 做静态对比。", target_metric=target, dimensions=(best_dims[0],), filters_value=_dimension_filters(user_input, profile), missing=["未检测到可信时间列，当前更适合先做对比、分群或数据质量检查"], assumptions=list(best_metric.risks if best_metric else ()), trigger=4, target_certainty=best_metric.certainty if best_metric else 0, dimension_certainty=dimension_fields[0].certainty if dimension_fields else 0)

    if asks_driver and target:
        missing = ["目标指标存在多个候选列，驱动分析前建议先确认指标"] if metric_ambiguous else []
        if not best_dims:
            missing.append("尚未识别出稳定的分组维度")
        assumptions = list(best_metric.risks if best_metric else ())
        for item in dimension_fields[:2]:
            assumptions.extend(item.risks)
        add(GoalType.DRIVER_ANALYSIS, f"分析{target}的主要影响因素", f"基于当前版本，优先从 {'、'.join(best_dims) if best_dims else '可用维度'} 解释 {target} 的变化。", target_metric=target, dimensions=best_dims, time_column=trusted_time, filters_value=filters, missing=missing, assumptions=assumptions, trigger=5, target_certainty=best_metric.certainty if best_metric else 0, time_certainty=best_time.certainty if best_time and trusted_time else 0, dimension_certainty=dimension_fields[0].certainty if dimension_fields else 0)

    if target and best_dims and (asks_compare or asks_trend or asks_driver or asks_segment):
        add(GoalType.COMPARISON, f"比较{target}在{best_dims[0]}上的差异", f"以 {best_dims[0]} 为主维度，对 {target} 做分组对比，观察差异是否稳定。", target_metric=target, dimensions=(best_dims[0],), filters_value=_dimension_filters(user_input, profile), missing=["目标指标存在多个候选列，建议先确认比较指标"] if metric_ambiguous else [], assumptions=list(best_metric.risks if best_metric else ()) + list(dimension_fields[0].risks if dimension_fields else ()), trigger=5 if asks_compare else 3, target_certainty=best_metric.certainty if best_metric else 0, dimension_certainty=dimension_fields[0].certainty if dimension_fields else 0)
        add(GoalType.SEGMENT_ANALYSIS, f"按{'、'.join(best_dims)}分析{target}表现", f"围绕 {'、'.join(best_dims)} 对 {target} 做分群观察，识别表现差异和潜在异常群体。", target_metric=target, dimensions=best_dims, filters_value=_dimension_filters(user_input, profile), missing=["目标指标存在多个候选列，建议先确认分群指标"] if metric_ambiguous else [], assumptions=list(best_metric.risks if best_metric else ()) + [risk for item in dimension_fields[:2] for risk in item.risks], trigger=5 if asks_segment else 3, target_certainty=best_metric.certainty if best_metric else 0, dimension_certainty=dimension_fields[0].certainty if dimension_fields else 0)

    if asks_distribution and target:
        add(GoalType.DISTRIBUTION_ANALYSIS, f"查看{target}的分布特征", f"检查 {target} 的集中趋势、离散程度和异常值提示。", target_metric=target, missing=["目标指标存在多个候选列，建议先确认要查看分布的指标"] if metric_ambiguous else [], assumptions=list(best_metric.risks if best_metric else ()), trigger=5, target_certainty=best_metric.certainty if best_metric else 0)

    strong_quality_issues = [issue for issue in profile.quality_issues if str(issue.severity) in {"medium", "high", "critical"}]
    if asks_quality or (not drafted and strong_quality_issues):
        add(GoalType.DATA_QUALITY_REVIEW, "检查数据质量问题", "基于当前版本的确定性体检结果，优先查看缺失值、重复、解析冲突和字段信息量风险。", trigger=6 if asks_quality else 2)

    if not drafted:
        add(GoalType.DATA_QUALITY_REVIEW, "检查数据质量问题", "当前未识别出足够明确的业务分析目标，先查看数据质量与字段结构更稳妥。", trigger=1)

    best_by_key: dict[tuple[str, str | None, str | None], tuple[GoalCandidate, tuple[int, int, int, int, int, int, str, str]]] = {}
    for key, candidate, score in drafted:
        current = best_by_key.get(key)
        if current is None or score > current[1]:
            best_by_key[key] = (candidate, score)

    ordered = sorted(best_by_key.values(), key=lambda item: (-item[1][0], -item[1][1], -item[1][2], -item[1][3], -item[1][4], -item[1][5], item[1][6], item[1][7]))
    candidates: list[GoalCandidate] = []
    per_type: dict[str, int] = {}
    for candidate, _score_value in ordered:
        goal_type_key = candidate.goal_type.value if hasattr(candidate.goal_type, 'value') else str(candidate.goal_type)
        if per_type.get(goal_type_key, 0) >= MAX_PER_TYPE:
            continue
        per_type[goal_type_key] = per_type.get(goal_type_key, 0) + 1
        candidates.append(candidate)
        if len(candidates) >= MAX_CANDIDATES:
            break
    return CandidateGenerationResult(candidates=candidates, questions=questions)