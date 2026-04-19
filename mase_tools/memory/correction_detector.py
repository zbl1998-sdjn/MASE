"""Auto-correction detector for MASE memory.

Detects user utterances that supersede prior memory ("I'm actually 28, not 25";
"我之前说错了, 其实是 ..."). Fully heuristic — no LLM call required for the
hot path. The detection layer is intentionally conservative: false positives
just trigger a redundant `mase2_supersede_facts` no-op.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 中文 / 英文触发短语 (大小写不敏感) — 用于 *检测*
_TRIGGER_PATTERNS = [
    # English
    r"\bactually\b",
    r"\bi (?:meant|misspoke|was wrong)\b",
    r"\bcorrection[:,]\s",
    r"\blet me correct\b",
    r"\bscratch that\b",
    r"\bsorry,?\s*(?:i meant|that was wrong|correction)",
    r"\bnot\b\s+\w+[, ]+(?:it'?s|but)\s+\w+",
    r"\bupdate\b[: ]\s*\w+",
    # Chinese
    r"我之前说错[了的]?",
    r"更正[一下]?[:，,]?",
    r"我说错[了的]?",
    r"不[对是]，?\s*(?:其实|应该)",
    r"其实[是不]",
    r"(?:重新|再)?(?:确认|更新)一下",
    r"我刚刚说错",
    r"应该是",
]

# 关键词抽取时仅删除 *短* 触发词本身，不能贪婪吞掉后续主题词
_STRIP_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bactually\b[,]?",
        r"\bi (?:meant|misspoke|was wrong)\b",
        r"\bcorrection[:,]\s?",
        r"\blet me correct\b",
        r"\bscratch that\b",
        r"\bsorry,?\b",
        r"\bnot\b",
        r"我之前说错[了的]?",
        r"更正[一下]?[:，,]?",
        r"我说错[了的]?",
        r"其实[是不]?",
        r"应该是",
    ]
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _TRIGGER_PATTERNS]


@dataclass
class CorrectionSignal:
    """Outcome of the correction detector."""

    is_correction: bool
    matched_pattern: str | None = None
    snippet: str | None = None

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return self.is_correction


def detect_correction(utterance: str) -> CorrectionSignal:
    """Return a :class:`CorrectionSignal` for the given user utterance.

    Heuristic only — caller may further confirm with an LLM judge before
    issuing a destructive supersede call. The return value is safe to pass
    around; ``bool(signal)`` is True iff a correction trigger is present.
    """
    if not utterance or not utterance.strip():
        return CorrectionSignal(is_correction=False)

    for pat in _COMPILED:
        m = pat.search(utterance)
        if m:
            start = max(0, m.start() - 10)
            end = min(len(utterance), m.end() + 40)
            return CorrectionSignal(
                is_correction=True,
                matched_pattern=pat.pattern,
                snippet=utterance[start:end].strip(),
            )
    return CorrectionSignal(is_correction=False)


def extract_keywords_for_supersede(utterance: str, *, max_keywords: int = 6) -> list[str]:
    """Pull plausible *subject* keywords out of a correction utterance.

    Strategy: strip trigger phrases, then keep tokens with length ≥ 2 that
    look like content words (CJK chars, alphanumeric ≥ 3 chars). The list
    feeds into :func:`mase_tools.memory.db_core.supersede_log_entries` which
    does the heavy lifting via FTS / LIKE fallback.
    """
    if not utterance:
        return []
    cleaned = utterance
    for pat in _STRIP_PATTERNS:
        cleaned = pat.sub(" ", cleaned)

    # Tokenize: keep CJK runs and ascii words ≥ 3 chars
    tokens: list[str] = []
    for m in re.finditer(r"[\u4e00-\u9fff]+|[A-Za-z][A-Za-z0-9_]{2,}|\d+", cleaned):
        tok = m.group(0)
        if tok.lower() in {"the", "and", "but", "not", "you", "are", "for", "actually", "meant"}:
            continue
        tokens.append(tok)
        if len(tokens) >= max_keywords:
            break
    # de-dup preserving order
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t not in seen:
            out.append(t)
            seen.add(t)
    return out
