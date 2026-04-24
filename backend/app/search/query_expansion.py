"""Query expansion and retrieval metadata helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


_SYNONYM_GROUPS: Dict[str, List[str]] = {
    "坏死": ["细胞坏死", "凝固性坏死", "液化性坏死"],
    "凋亡": ["细胞凋亡", "程序性细胞死亡"],
    "可逆性损伤": ["可逆性细胞损伤", "细胞可逆性损伤"],
    "首过效应": ["首关效应", "肝首过效应", "首过消除"],
    "生物利用度": ["生物利用率", "药物吸收利用度"],
    "气滞": ["气机郁滞", "肝气郁滞", "脾胃气滞"],
    "气逆": ["胃气上逆", "肺气上逆", "肝气上逆"],
    "气陷": ["中气下陷", "气虚下陷", "脏器下垂"],
    "MIC": ["最低抑菌浓度", "最小抑菌浓度"],
    "最低杀菌浓度": ["MBC", "最小杀菌浓度"],
    "耐药性": ["细菌耐药", "药物耐药"],
    "阿托品": ["atropine"],
    "有机磷中毒": ["有机磷酸酯类中毒", "农药中毒"],
    "去甲肾上腺素": ["noradrenaline", "norepinephrine"],
    "肾上腺素": ["epinephrine", "adrenaline"],
    "感冒": ["普通感冒", "上呼吸道感染", "急性上呼吸道感染"],
    "头痛": ["头疼", "头部疼痛", "偏头痛"],
    "高血压": ["血压高", "原发性高血压", "hypertension"],
    "心脏不舒服": ["胸闷", "胸痛", "心悸", "心前区不适"],
    "发痒": ["瘙痒", "皮肤瘙痒", "全身瘙痒"],
    "全身一热就全身发痒": ["受热后瘙痒", "热刺激性瘙痒", "胆碱能性荨麻疹"],
}


def _tokenize(query: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", query)
        if token.strip()
    ]


def _dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def build_query_expansion_plan(
    query: str,
    *,
    enabled: bool = True,
    max_terms: int = 6,
) -> Dict[str, Any]:
    clean_query = query.strip()
    if not clean_query or not enabled:
        return {
            "original_query": clean_query,
            "matched_terms": [],
            "expanded_terms": [],
            "combined_query": clean_query,
            "keyword_terms": _dedupe_preserve_order([clean_query, *_tokenize(clean_query)]),
            "used_query_expansion": False,
        }

    matched_terms: List[str] = []
    expanded_terms: List[str] = []
    tokens = _tokenize(clean_query)

    for canonical_term, synonyms in _SYNONYM_GROUPS.items():
        candidates = [canonical_term, *synonyms]
        if any(candidate and candidate in clean_query for candidate in candidates) or any(
            token in candidates or token == canonical_term for token in tokens
        ):
            matched_terms.append(canonical_term)
            for synonym in candidates:
                if synonym not in clean_query:
                    expanded_terms.append(synonym)

    expanded_terms = _dedupe_preserve_order(expanded_terms)[:max_terms]
    keyword_terms = _dedupe_preserve_order([clean_query, *tokens, *expanded_terms])

    if expanded_terms:
        combined_query = f"{clean_query}；相关医学表述：{'、'.join(expanded_terms)}"
    else:
        combined_query = clean_query

    return {
        "original_query": clean_query,
        "matched_terms": _dedupe_preserve_order(matched_terms),
        "expanded_terms": expanded_terms,
        "combined_query": combined_query,
        "keyword_terms": keyword_terms,
        "used_query_expansion": bool(expanded_terms),
    }


def empty_retrieval_stats(*, used_query_expansion: bool = False) -> Dict[str, Any]:
    return {
        "chunk_hits": 0,
        "entity_hits": 0,
        "community_hits": 0,
        "relation_hits": 0,
        "web_hits": 0,
        "evidence_total": 0,
        "used_query_expansion": used_query_expansion,
        "knowledge_backed": False,
    }


def merge_retrieval_stats(*stats_items: Dict[str, Any]) -> Dict[str, Any]:
    merged = empty_retrieval_stats()
    for stats in stats_items:
        if not stats:
            continue
        merged["chunk_hits"] += int(stats.get("chunk_hits", 0) or 0)
        merged["entity_hits"] += int(stats.get("entity_hits", 0) or 0)
        merged["community_hits"] += int(stats.get("community_hits", 0) or 0)
        merged["relation_hits"] += int(stats.get("relation_hits", 0) or 0)
        merged["web_hits"] += int(stats.get("web_hits", 0) or 0)
        merged["evidence_total"] += int(stats.get("evidence_total", 0) or 0)
        merged["used_query_expansion"] = bool(
            merged["used_query_expansion"] or stats.get("used_query_expansion")
        )
    merged["knowledge_backed"] = merged["evidence_total"] > 0
    return merged


def dedupe_source_items(source_items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for item in source_items:
        if not item:
            continue
        source_id = str(
            item.get("id")
            or f"{item.get('source_type', 'unknown')}::{item.get('title', '')}::{item.get('content', '')[:80]}"
        )
        if source_id in seen:
            continue
        seen.add(source_id)
        deduped.append(item)
    return deduped


def has_visible_evidence(stats: Dict[str, Any] | None) -> bool:
    if not stats:
        return False
    return int(stats.get("evidence_total", 0) or 0) > 0


def summarize_retrieval_stats(stats: Dict[str, Any] | None) -> str:
    if not has_visible_evidence(stats):
        return "知识库未命中可展示证据。"

    parts: List[str] = []
    if stats.get("chunk_hits"):
        parts.append(f"{stats['chunk_hits']} 条文献片段")
    if stats.get("entity_hits"):
        parts.append(f"{stats['entity_hits']} 个实体")
    if stats.get("community_hits"):
        parts.append(f"{stats['community_hits']} 条社区摘要")
    if stats.get("relation_hits"):
        parts.append(f"{stats['relation_hits']} 条实体关系")
    if stats.get("web_hits"):
        parts.append(f"{stats['web_hits']} 条网页结果")

    summary = "，".join(parts) if parts else "已命中可展示证据"
    if stats.get("used_query_expansion"):
        summary += "；已启用同义词拓展"
    return f"累计命中 {stats.get('evidence_total', 0)} 条可展示证据：{summary}。"
