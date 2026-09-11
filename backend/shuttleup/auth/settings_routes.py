from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AppSetting
from .service import require_csrf, require_user

router=APIRouter(tags=["settings"])


class SettingsUpdate(BaseModel):
    timezone: str="Asia/Shanghai"
    court_hourly_cents: int|None=Field(default=None,ge=0)
    shuttle_unit_cents: int|None=Field(default=None,ge=0)
    shuttle_label: str|None=Field(default=None,max_length=80)
    guest_join_enabled: bool=True
    expected_version: int


def dto(s): return {"timezone":s.timezone,"court_hourly_cents":s.court_hourly_cents,"shuttle_unit_cents":s.shuttle_unit_cents,"shuttle_label":s.shuttle_label,"guest_join_enabled":s.guest_join_enabled,"version":s.version}


@router.get("/settings")
async def settings(request: Request,db: Session=Depends(get_db)):
    user=require_user(request,db)
    if not user.is_admin: raise HTTPException(403,detail={"code":"FORBIDDEN","message":"只有实例管理员可以查看全局设置。"})
    model=db.get(AppSetting,1) or AppSetting(id=1); db.add(model); db.commit(); return dto(model)


@router.put("/settings")
async def update_settings(body: SettingsUpdate,request: Request,db: Session=Depends(get_db)):
    user=require_user(request,db); require_csrf(request)
    if not user.is_admin: raise HTTPException(403,detail={"code":"FORBIDDEN","message":"只有实例管理员可以修改全局设置。"})
    model=db.get(AppSetting,1) or AppSetting(id=1)
    if model.version!=body.expected_version: raise HTTPException(409,detail={"code":"VERSION_CONFLICT","message":"设置刚刚有更新。","current_version":model.version})
    for key,value in body.model_dump(exclude={"expected_version"}).items(): setattr(model,key,value)
    model.version+=1; db.add(model); db.commit(); return dto(model)

