"""optimizer_name_parser.py — 优化师多级匹配解析器（名单校验版）

匹配规则：
  1. 小程序: campaign_name 按 '-' 切分，第 6 位(parts[5])为候选值
     → 必须在 optimizer_directory 名单中匹配到 optimizer_name/optimizer_code/aliases
     → 匹配不到归为"未识别"

  2. APP: campaign_name 按 '-' 切分:
     → 第 12 位(parts[11])为第一候选值，去名单匹配
     → 若未命中，第 11 位(parts[10])为第二候选值，去名单匹配
     → 两者都未命中归为"未识别"

  3. 不允许候选值直接当最终优化师，必须经过名单校验
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

UNKNOWN_OPTIMIZER = "未识别"

# 匹配来源枚举
MATCH_SOURCE_CAMPAIGN     = "campaign_name"
MATCH_SOURCE_MANUAL       = "manual_assign"
MATCH_SOURCE_UNASSIGNED   = "unassigned"

# 匹配位置
MATCH_POS_FIELD_6  = "field_6"
MATCH_POS_FIELD_11 = "field_11"
MATCH_POS_FIELD_12 = "field_12"
MATCH_POS_UNASSIGNED = "unassigned"

# 置信度
CONFIDENCE = {
    MATCH_SOURCE_CAMPAIGN:   0.90,
    MATCH_SOURCE_MANUAL:     1.00,
    MATCH_SOURCE_UNASSIGNED: 0.00,
}

_MINI_PROGRAM_KEYWORDS = {"小程序", "miniprogram", "mini_program", "mp"}


def normalize_optimizer_name(name: str | None) -> str:
    """trim → 压缩多空格 → 大写。空值返回 '未识别'。"""
    if not name or not isinstance(name, str):
        return UNKNOWN_OPTIMIZER
    s = name.strip()
    if not s:
        return UNKNOWN_OPTIMIZER
    s = re.sub(r"\s+", " ", s).upper()
    return s


def detect_source_type(campaign_name: str) -> str:
    parts = campaign_name.split("-")
    if len(parts) >= 4:
        f4 = parts[3].strip().lower()
        if any(k in f4 for k in _MINI_PROGRAM_KEYWORDS):
            return "小程序"
    return "APP"


# ---------------------------------------------------------------------------
# 名单匹配引擎
# ---------------------------------------------------------------------------

@dataclass
class DirectoryEntry:
    """optimizer_directory 的内存表示"""
    optimizer_id: int
    optimizer_name: str
    optimizer_code: str
    aliases: list[str] = field(default_factory=list)


class OptimizerDirectoryMatcher:
    """
    基于 optimizer_directory 构建的匹配索引。
    匹配候选值时依次检查: optimizer_name / optimizer_code / aliases（大小写不敏感）。
    """

    def __init__(self, directory_rows: list[dict]):
        self._entries: list[DirectoryEntry] = []
        self._lookup: dict[str, str] = {}
        for row in directory_rows:
            name = row.get("optimizer_name", "")
            code = row.get("optimizer_code", "")
            aliases_str = row.get("aliases", "")
            alias_list = [a.strip() for a in aliases_str.split(",") if a.strip()] if aliases_str else []

            entry = DirectoryEntry(
                optimizer_id=row.get("id", 0),
                optimizer_name=name,
                optimizer_code=code,
                aliases=alias_list,
            )
            self._entries.append(entry)

            # 标准名称 → 映射到自身
            self._lookup[name.upper().strip()] = name
            # 编码 → 映射到标准名称
            if code:
                self._lookup[code.upper().strip()] = name
            # 别名 → 映射到标准名称
            for alias in alias_list:
                self._lookup[alias.upper().strip()] = name

    def match(self, candidate: str) -> Optional[str]:
        """
        尝试匹配候选值到名单中的标准优化师名称。
        返回标准名称，或 None 表示未匹配。
        """
        if not candidate or not candidate.strip():
            return None
        key = candidate.strip().upper()
        key = re.sub(r"\s+", " ", key)
        return self._lookup.get(key)

    @property
    def is_empty(self) -> bool:
        return len(self._entries) == 0


# ---------------------------------------------------------------------------
# 匹配结果
# ---------------------------------------------------------------------------

@dataclass
class MatchResult:
    optimizer_name_raw: str = ""
    optimizer_name_normalized: str = UNKNOWN_OPTIMIZER
    match_source: str = MATCH_SOURCE_UNASSIGNED
    match_position: str = MATCH_POS_UNASSIGNED
    match_confidence: float = 0.00
    parse_status: str = "ok"
    parse_error: Optional[str] = None


# ---------------------------------------------------------------------------
# 核心匹配函数
# ---------------------------------------------------------------------------

def resolve_optimizer(
    *,
    campaign_name: str,
    source_type: str,
    matcher: OptimizerDirectoryMatcher,
) -> MatchResult:
    """
    基于名单校验的优化师解析。
    小程序: parts[5] → 名单匹配
    APP: parts[11] → 名单匹配，失败则 parts[10] → 名单匹配
    """
    if not campaign_name or not campaign_name.strip():
        return MatchResult(
            parse_status="failed",
            parse_error="campaign_name 为空",
        )

    parts = campaign_name.split("-")

    if source_type == "小程序":
        return _resolve_mini_program(parts, matcher)
    else:
        return _resolve_app(parts, matcher)


def _resolve_mini_program(parts: list[str], matcher: OptimizerDirectoryMatcher) -> MatchResult:
    """小程序: 第 6 位 (parts[5]) 去名单匹配"""
    if len(parts) < 6:
        return MatchResult(
            parse_status="failed",
            parse_error=f"字段数不足，期望 ≥6（小程序），实际 {len(parts)}",
        )

    candidate = parts[5].strip()
    standard_name = matcher.match(candidate)

    if standard_name:
        return MatchResult(
            optimizer_name_raw=candidate,
            optimizer_name_normalized=standard_name,
            match_source=MATCH_SOURCE_CAMPAIGN,
            match_position=MATCH_POS_FIELD_6,
            match_confidence=CONFIDENCE[MATCH_SOURCE_CAMPAIGN],
        )

    return MatchResult(
        optimizer_name_raw=candidate,
        optimizer_name_normalized=UNKNOWN_OPTIMIZER,
        match_source=MATCH_SOURCE_UNASSIGNED,
        match_position=MATCH_POS_UNASSIGNED,
        match_confidence=0.00,
        parse_status="failed",
        parse_error=f"候选值 '{candidate}' 未在优化师名单中匹配到",
    )


def _resolve_app(parts: list[str], matcher: OptimizerDirectoryMatcher) -> MatchResult:
    """APP: 第 12 位 (parts[11]) 优先，不命中则第 11 位 (parts[10])"""

    # 第一候选: parts[11] (第12位)
    if len(parts) >= 12:
        candidate_12 = parts[11].strip()
        standard_name = matcher.match(candidate_12)
        if standard_name:
            return MatchResult(
                optimizer_name_raw=candidate_12,
                optimizer_name_normalized=standard_name,
                match_source=MATCH_SOURCE_CAMPAIGN,
                match_position=MATCH_POS_FIELD_12,
                match_confidence=CONFIDENCE[MATCH_SOURCE_CAMPAIGN],
            )

    # 第二候选: parts[10] (第11位)
    if len(parts) >= 11:
        candidate_11 = parts[10].strip()
        standard_name = matcher.match(candidate_11)
        if standard_name:
            return MatchResult(
                optimizer_name_raw=candidate_11,
                optimizer_name_normalized=standard_name,
                match_source=MATCH_SOURCE_CAMPAIGN,
                match_position=MATCH_POS_FIELD_11,
                match_confidence=CONFIDENCE[MATCH_SOURCE_CAMPAIGN],
            )

    # 拼接原始候选值供排查
    raw_parts = []
    if len(parts) >= 12:
        raw_parts.append(f"f12='{parts[11].strip()}'")
    if len(parts) >= 11:
        raw_parts.append(f"f11='{parts[10].strip()}'")
    raw_str = ", ".join(raw_parts) if raw_parts else "字段数不足"

    # 保留第一个非空候选值作为 raw
    first_raw = ""
    if len(parts) >= 12 and parts[11].strip():
        first_raw = parts[11].strip()
    elif len(parts) >= 11 and parts[10].strip():
        first_raw = parts[10].strip()

    return MatchResult(
        optimizer_name_raw=first_raw,
        optimizer_name_normalized=UNKNOWN_OPTIMIZER,
        match_source=MATCH_SOURCE_UNASSIGNED,
        match_position=MATCH_POS_UNASSIGNED,
        match_confidence=0.00,
        parse_status="failed",
        parse_error=f"APP 候选值均未在优化师名单中匹配到 ({raw_str})",
    )
