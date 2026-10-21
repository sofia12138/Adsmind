from fastapi import APIRouter, Query
from meta_ads.api.accounts import MetaAccountService

router = APIRouter(prefix="/meta/accounts", tags=["Meta 广告账户"])


@router.get("/")
async def list_accounts():
    from repositories import biz_account_repository
    from core.isolation import application_id
    rows = biz_account_repository.list_by_platform('meta', application_id=application_id())
    return {"data": [{"id": r['account_id'], "account_id": r['account_id'], "name": r['account_name'], "currency": r['currency'], "timezone_name": r['timezone']} for r in rows]}


@router.get("/info")
async def get_account_info(ad_account_id: str | None = Query(None)):
    data = await MetaAccountService().get_account_info(ad_account_id)
    return {"data": data}
