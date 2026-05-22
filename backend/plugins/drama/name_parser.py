"""drama_name_parser.py — Python 版剧名解析工具（与前端 TypeScript 版保持一致）

三层分离：
  parse_drama_name()                  — 从单个剧名字段解析语言尾缀
  parse_mini_program_campaign_name()  — 小程序活动名称解析器
  parse_app_campaign_name()           — APP 活动名称解析器

核心约束（不可违反）：
  - 第 10 字段是唯一合法剧名来源
  - 第 11 字段及以后全部归入 remark_raw
  - remark_raw 不参与语言识别、剧名解析、content_key 生成
  - 即使 remark_raw 中出现括号语言标记，也不影响解析结果
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────
# 语言映射表（与前端 LANG_CODE_MAP 保持一致）
# ─────────────────────────────────────────────────────────────

_LANG_CODE_MAP: dict[str, str] = {
    "EN": "en",
    "ES": "es",
    "PT": "pt",
    "FR": "fr",
    "DE": "de",
    "ID": "id",
    "TH": "th",
    "JP": "ja",
    "JA": "ja",
    "KR": "ko",
    "KO": "ko",
    "AR": "ar",
}

# 匹配剧名结尾的语言尾缀（半角括号、全角括号、方括号；大小写不敏感）
# 仅匹配已知语言代码（2~3 字母），锚定在字符串结尾
_LANG_SUFFIX_RE = re.compile(
    r'\s*(?:\(|（|\[)([A-Za-z]{2,3})(?:\)|）|\])\s*$'
)


# ─────────────────────────────────────────────────────────────
# 数据类
# ─────────────────────────────────────────────────────────────

@dataclass
class ParsedDramaName:
    drama_name_raw: str
    localized_drama_name: str
    language_code: str = "unknown"
    language_tag_raw: Optional[str] = None


@dataclass
class ParsedMiniProgramCampaign:
    campaign_name_raw: str
    parse_status: str = "ok"       # ok / partial / failed
    parse_error: Optional[str] = None

    drama_id: str = ""
    drama_type: str = ""
    country: str = ""
    source_type: str = ""
    media_channel: str = ""
    buyer_name: str = ""
    optimization_type: str = ""
    bid_type: str = ""
    publish_date: str = ""

    drama_name_raw: str = ""
    localized_drama_name: str = ""
    language_code: str = "unknown"
    language_tag_raw: Optional[str] = None

    remark_raw: Optional[str] = None


@dataclass
class ParsedAppCampaign:
    campaign_name_raw: str
    parse_status: str = "ok"
    parse_error: Optional[str] = None

    field1: str = ""
    field2: str = ""
    field3: str = ""
    field4: str = ""
    field5: str = ""
    field6: str = ""
    field7: str = ""
    field8: str = ""
    field9: str = ""

    drama_name_raw: str = ""
    localized_drama_name: str = ""
    language_code: str = "unknown"
    language_tag_raw: Optional[str] = None

    buyer_short_name: Optional[str] = None
    remark_raw: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# 核心函数
# ─────────────────────────────────────────────────────────────

def parse_drama_name(raw: str) -> ParsedDramaName:
    """
    从剧名原始字符串解析语言尾缀。
    参数 raw 只应传入第 10 字段的内容，不含任何备注。
    """
    if not raw or not raw.strip():
        return ParsedDramaName(
            drama_name_raw=raw,
            localized_drama_name="",
            language_code="unknown",
        )

    match = _LANG_SUFFIX_RE.search(raw)
    if match:
        tag_content = match.group(1).upper()
        code = _LANG_CODE_MAP.get(tag_content)
        if code:
            localized = raw[: match.start()].strip()
            return ParsedDramaName(
                drama_name_raw=raw,
                localized_drama_name=localized,
                language_code=code,
                language_tag_raw=match.group(0).strip(),
            )

    return ParsedDramaName(
        drama_name_raw=raw,
        localized_drama_name=raw.strip(),
        language_code="unknown",
    )


def parse_mini_program_campaign_name(name: str) -> ParsedMiniProgramCampaign:
    """
    解析小程序推广活动名称。

    固定字段（'-' 分隔，1-based）：
      1  drama_id
      2  drama_type
      3  country
      4  source_type
      5  media_channel
      6  buyer_name
      7  optimization_type
      8  bid_type
      9  publish_date
      10 drama_name_raw  ← 唯一合法剧名来源
      11+ remark_raw（原样拼接，不参与任何解析）

    少于 10 段 → parse_status='failed'
    """
    try:
        parts = name.split("-")

        if len(parts) < 10:
            return ParsedMiniProgramCampaign(
                campaign_name_raw=name,
                parse_status="failed",
                parse_error=f"字段数不足，期望 ≥10 段，实际 {len(parts)} 段",
            )

        # 第 10 字段（index 9）是唯一合法剧名来源，不允许拼入第 11 字段
        drama_field = parts[9]
        parsed = parse_drama_name(drama_field)

        # 第 11 字段及以后 → remark_raw（原样保留，不做任何解析）
        remark_raw = "-".join(parts[10:]) if len(parts) > 10 else None

        return ParsedMiniProgramCampaign(
            campaign_name_raw=name,
            parse_status="ok",
            drama_id=parts[0].strip(),
            drama_type=parts[1].strip(),
            country=parts[2].strip(),
            source_type=parts[3].strip(),
            media_channel=parts[4].strip(),
            buyer_name=parts[5].strip(),
            optimization_type=parts[6].strip(),
            bid_type=parts[7].strip(),
            publish_date=parts[8].strip(),
            drama_name_raw=parsed.drama_name_raw,
            localized_drama_name=parsed.localized_drama_name,
            language_code=parsed.language_code,
            language_tag_raw=parsed.language_tag_raw,
            remark_raw=remark_raw,
        )
    except Exception as e:
        return ParsedMiniProgramCampaign(
            campaign_name_raw=name,
            parse_status="failed",
            parse_error=str(e),
        )


def parse_app_campaign_name(name: str) -> ParsedAppCampaign:
    """
    解析 APP 推广活动名称。

    当前字段约定（'-' 分隔，1-based）：
      1~9  定位字段（封装为 field1~field9，便于后续扩展）
      10   drama_name_raw  ← 唯一合法剧名来源
      11   buyer_short_name（若存在）
      12+  remark_raw（原样保留，不参与解析）

    少于 10 段 → parse_status='failed'
    """
    try:
        parts = name.split("-")

        if len(parts) < 10:
            return ParsedAppCampaign(
                campaign_name_raw=name,
                parse_status="failed",
                parse_error=f"字段数不足，期望 ≥10 段，实际 {len(parts)} 段",
            )

        # 第 10 字段（index 9）是唯一合法剧名来源
        drama_field = parts[9]
        parsed = parse_drama_name(drama_field)

        # 第 11 字段：投手简称（若存在且非空）
        buyer_short_name = parts[10].strip() if len(parts) > 10 and parts[10].strip() else None

        # 第 12 字段及以后 → remark_raw
        remark_raw = "-".join(parts[11:]) if len(parts) > 11 else None

        return ParsedAppCampaign(
            campaign_name_raw=name,
            parse_status="ok",
            field1=parts[0].strip(),
            field2=parts[1].strip(),
            field3=parts[2].strip(),
            field4=parts[3].strip(),
            field5=parts[4].strip(),
            field6=parts[5].strip(),
            field7=parts[6].strip(),
            field8=parts[7].strip(),
            field9=parts[8].strip(),
            drama_name_raw=parsed.drama_name_raw,
            localized_drama_name=parsed.localized_drama_name,
            language_code=parsed.language_code,
            language_tag_raw=parsed.language_tag_raw,
            buyer_short_name=buyer_short_name,
            remark_raw=remark_raw,
        )
    except Exception as e:
        return ParsedAppCampaign(
            campaign_name_raw=name,
            parse_status="failed",
            parse_error=str(e),
        )
