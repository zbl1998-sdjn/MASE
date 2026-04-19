from typing import Any

from .correction_detector import (
    CorrectionSignal,
    detect_correction,
    extract_keywords_for_supersede,
)
from .db_core import (
    add_event_log,
    get_entity_fact_history,
    get_entity_facts,
    search_event_log,
    supersede_log_entries,
    upsert_entity_fact,
)


def mase2_write_interaction(thread_id: str, role: str, content: str) -> str:
    """写入基础的对话流水账"""
    log_id = add_event_log(thread_id, role, content)
    return f"Success: Event logged with ID {log_id}"

def mase2_upsert_fact(category: str, key: str, value: str, *, reason: str | None = None, source_log_id: int | None = None) -> str:
    """写入提取出的实体状态 (Entity Fact)"""
    upsert_entity_fact(category, key, value, reason=reason, source_log_id=source_log_id)
    return f"Success: Fact {category}.{key} updated to {value}"

def mase2_search_memory(keywords: list[str], limit: int = 5) -> list[dict[str, Any]]:
    """在底层的流水账中利用 BM25 全文检索搜索关键词"""
    return search_event_log(keywords, limit)

def mase2_get_facts(category: str = None) -> list[dict[str, Any]]:
    """获取所有/特定的实体状态字典，这应该作为高优先级上下文"""
    return get_entity_facts(category)


# ---------- Auto-correction (Mem0-style UPDATE/DELETE) ----------

def mase2_detect_correction(utterance: str) -> CorrectionSignal:
    """检测一句用户话语是否包含"我之前说错了/actually..." 类纠正触发词。"""
    return detect_correction(utterance)


def mase2_supersede_facts(
    keywords: list[str],
    replacement_log_id: int,
    reason: str = "user_correction",
) -> dict[str, Any]:
    """把所有命中 ``keywords`` 的旧流水账标记为 superseded，新值由 replacement_log_id 指向。

    返回 {"superseded_count": N}.
    """
    n = supersede_log_entries(keywords, replacement_log_id, reason=reason)
    return {"superseded_count": n, "replacement_log_id": replacement_log_id, "reason": reason}


def mase2_correct_and_log(
    thread_id: str,
    new_utterance: str,
    *,
    role: str = "user",
    extra_keywords: list[str] | None = None,
) -> dict[str, Any]:
    """端到端 helper：写入新的 utterance，并自动 supersede 旧的同主题流水账。

    1. ``add_event_log`` 写入新行 → 拿到 ``new_log_id``
    2. ``detect_correction`` 判断是否为纠正
    3. 若是 → ``extract_keywords_for_supersede`` 抽取主题词 → ``supersede_log_entries``

    无论是否触发 supersede，都返回 ``new_log_id``，调用方拿来后续 upsert_fact 时
    传入 source_log_id，形成"事实变化 ⇄ 触发对话"双向溯源。
    """
    new_id = add_event_log(thread_id, role, new_utterance)
    signal = detect_correction(new_utterance)
    result: dict[str, Any] = {
        "new_log_id": new_id,
        "is_correction": bool(signal),
        "matched_pattern": signal.matched_pattern,
        "superseded_count": 0,
    }
    if signal:
        kws = extract_keywords_for_supersede(new_utterance)
        if extra_keywords:
            kws = list(dict.fromkeys([*kws, *extra_keywords]))
        if kws:
            n = supersede_log_entries(kws, new_id, reason="user_correction")
            result["superseded_count"] = n
            result["matched_keywords"] = kws
    return result


def mase2_get_fact_history(category: str | None = None, entity_key: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """查询事实审计链 (Mem0 缺乏的能力)。"""
    return get_entity_fact_history(category=category, entity_key=entity_key, limit=limit)

