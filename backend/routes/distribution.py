from fastapi import APIRouter, Depends, HTTPException, Query
from auth import User, get_current_user
from core.application import ApplicationCtx, get_current_application
from services import distribution_service as service

router = APIRouter(prefix='/distribution', tags=['发行中心'])


def reader(user: User = Depends(get_current_user)):
    from services.panel_service import resolve_allowed_panels
    if 'creatives' not in resolve_allowed_panels(user.username, user.role):
        raise HTTPException(403, '当前账号没有素材与发行访问权限')
    return user


def writer(user: User = Depends(reader)):
    if user.role not in ('admin', 'super_admin', 'optimizer', 'designer'):
        raise HTTPException(403, '当前账号没有发行编辑权限')
    return user


@router.get('/channels')
def channels(app: ApplicationCtx = Depends(get_current_application), user: User = Depends(reader)):
    return {'data': service.channels(app)}


@router.post('/channels')
def add_channel(body: service.ChannelInput, app: ApplicationCtx = Depends(get_current_application), user: User = Depends(writer)):
    return {'data': service.create_channel(body, app)}


@router.get('/drafts')
def drafts(page: int = Query(1, ge=1), app: ApplicationCtx = Depends(get_current_application), user: User = Depends(reader)):
    return {'data': service.list_drafts(app, page)}


@router.post('/drafts')
def create(body: service.DraftInput, app: ApplicationCtx = Depends(get_current_application), user: User = Depends(writer)):
    return {'data': service.save(body, app, user)}


@router.put('/drafts/{row_id}')
def update(row_id: str, body: service.DraftUpdate, app: ApplicationCtx = Depends(get_current_application), user: User = Depends(writer)):
    return {'data': service.save(body, app, user, row_id)}


@router.post('/drafts/{row_id}/check')
def check(row_id: str, app: ApplicationCtx = Depends(get_current_application), user: User = Depends(reader)):
    return {'data': service.precheck(service.load(row_id, app), app)}
