"""Validate the currency contract before any platform write."""
from decimal import Decimal, InvalidOperation

# These currencies use the existing Meta minor-unit conversion (x100).
# Additional currency conventions require separate platform validation.
META_CURRENCIES = {'USD', 'EUR', 'CNY'}


def budget_checks(payload, platform, currency):
    currency = str(currency or '').upper()
    declared = str(payload.get('budget_currency') or '').upper()
    checks = [{'code': 'budget_currency', 'ok': bool(currency) and (declared == currency or (not declared and currency == 'USD')),
               'message': f'预算币种与账户一致（{currency}）' if currency and declared == currency else '请按账户币种重新确认预算后保存草稿'}]
    if platform == 'meta':
        checks.append({'code': 'budget_unit', 'ok': currency in META_CURRENCIES,
                       'message': 'Meta 预算金额单位已支持' if currency in META_CURRENCIES else f'Meta {currency or "未知币种"} 的预算单位尚未验证，暂不能创建'})
    try:
        amount = Decimal(str(payload.get('budget')))
        valid = amount.is_finite() and amount > 0 and amount * 100 == (amount * 100).to_integral_value()
    except (InvalidOperation, ValueError, TypeError):
        valid = False
    checks.append({'code': 'budget_precision', 'ok': valid, 'message': '预算金额必须为正数，且最多保留两位小数'})
    if platform == 'meta':
        overrides = payload.get('overrides') or {}
        blocks = [overrides.get('campaign') or {}, overrides.get('adset') or {}, *(payload.get('adsets') or [])]
        valid_units = True
        for block in blocks:
            for field in ('daily_budget', 'lifetime_budget'):
                if field not in block:
                    continue
                try:
                    units = Decimal(str(block[field]))
                    valid_units = valid_units and units.is_finite() and units > 0 and units == units.to_integral_value()
                except (InvalidOperation, ValueError, TypeError):
                    valid_units = False
        checks.append({'code': 'meta_budget_amount', 'ok': bool(valid_units), 'message': 'Meta 广告系列与广告组预算必须为正整数金额单位'})
    return checks
