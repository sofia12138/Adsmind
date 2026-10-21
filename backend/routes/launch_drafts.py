from fastapi import APIRouter, Body, Depends, HTTPException, Query
from auth import User, get_current_user
from core.application import ApplicationCtx, get_current_application
from services import launch_draft_service as service

router = APIRouter(prefix='/launch-drafts', tags=['广告创建草稿'])


def writer(user: User = Depends(get_current_user)):
    if user.role not in ('admin', 'super_admin', 'optimizer'):
        raise HTTPException(403, '当前账号没有广告创建权限')
    return user


@router.get('')
async def list_drafts(page: int = Query(1, ge=1), application: ApplicationCtx = Depends(get_current_application), user: User = Depends(writer)):
    return {'data': service.list_drafts(application, user, page)}


@router.post('')
async def create(body: dict = Body(...), application: ApplicationCtx = Depends(get_current_application), user: User = Depends(writer)):
    payload = body.get('payload')
    if not isinstance(payload, dict) or len(str(payload)) > 1_000_000:
        raise HTTPException(400, '草稿内容无效或过大')
    row = service.create(payload, body.get('request_key'), application, user)
    return {'data': service.public(row), 'precheck': service.precheck(row['payload'], row['template_snapshot'], application, user)}


@router.post('/{draft_id}/execute')
async def execute(draft_id: str, body: dict = Body(...), application: ApplicationCtx = Depends(get_current_application), user: User = Depends(writer)):
    row = service.load(draft_id, application, user)
    if not isinstance(body.get('revision'), int):
        raise HTTPException(400, '请提供草稿版本号')
    row = await service.execute(row, body['revision'], application, user)
    return {'data': service.public(row)}


@router.post('/{draft_id}/check')
async def check(draft_id: str, application: ApplicationCtx = Depends(get_current_application), user: User = Depends(writer)):
    row = service.load(draft_id, application, user)
    return {'data': service.public(row), 'precheck': service.precheck(row['payload'], row['template_snapshot'], application, user)}


@router.patch('/{draft_id}')
async def update(draft_id: str, body: dict = Body(...), application: ApplicationCtx = Depends(get_current_application), user: User = Depends(writer)):
    row = service.load(draft_id, application, user)
    if type(body.get('revision')) is not int:
        raise HTTPException(400, '请提供草稿版本号')
    row = service.update(row, body, body['revision'], application, user)
    return {'data': service.public(row)}
