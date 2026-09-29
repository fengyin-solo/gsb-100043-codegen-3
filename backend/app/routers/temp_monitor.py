"""温控监测接口：维护温度记录，覆盖多级超温判定、报警回写、断点续传等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.temp_monitor import TempMonitorService

router = APIRouter(prefix="/api/temp_monitor", tags=["温控监测"])

service = TempMonitorService()

LIST_FIELDS = ["记录编号", "运单编号", "当前温度", "温度上限", "温度下限", "记录时间", "设备编号", "记录状态", "回写状态"]
STATUSES = ["正常", "接近临界", "超温", "严重超温", "数据缺失"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="正常、接近临界、超温、严重超温、数据缺失"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号与状态过滤温控监测列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/rules")
def get_rules() -> dict[str, Any]:
    """读取多级超温规则与优先级配置。"""
    return service.get_rules()


@router.get("/checkpoint")
def get_checkpoint() -> dict[str, Any]:
    """读取当前断点与接口状态。"""
    return service.get_checkpoint()


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条温度记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"温度记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条温度记录，按规则自动判定超温等级并回写报警待办。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="温度记录已登记", entry=entry)


@router.post("/ingest", response_model=ActionResult)
def ingest_readings(payload: EntryPayload) -> ActionResult:
    """批量接入温度记录：逐条判定并回写，接口中断时维持当前判定。"""
    readings = payload.values.get("readings") or []
    if not isinstance(readings, list):
        return ActionResult(ok=False, message="readings 必须是温度记录数组")
    result = service.ingest_readings(readings)
    return ActionResult(ok=result["ok"], message=result["message"], entry=result)


@router.post("/retry", response_model=ActionResult)
def retry_pending() -> ActionResult:
    """从断点继续：补写所有待回写的超温结论，不重复生成报警。"""
    result = service.retry_pending_write_backs()
    return ActionResult(ok=result["ok"], message=result["message"], entry=result)


@router.post("/interface", response_model=ActionResult)
def set_interface(payload: EntryPayload) -> ActionResult:
    """设置温度记录接入接口状态：normal 恢复 | interrupted 中断。"""
    state = str(payload.values.get("state") or "").strip()
    result = service.set_interface(state)
    return ActionResult(ok=result["ok"], message=result["message"], entry=result)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条温度记录执行标记预警、确认超温、数据补录；动作后仍按规则重新判定。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出温控监测清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "temp_monitor", "total": total, "items": items}
