"""温控监测接口：维护温度记录，覆盖标记预警、确认超温、数据补录等动作。

另外提供：
* GET  /api/temp_monitor/dashboard   温控看板（统计与明细、报警待办同源）
* GET  /api/temp_monitor/rules       多级超温规则清单（含业务优先级）
* POST /api/temp_monitor/ingest      接口批量接入温度记录（断点续传、幂等）
* GET  /api/temp_monitor/checkpoint  查看接入断点
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult, TempIngestPayload, TempIngestResult
from app.services.temp_monitor import IngestInterrupted, TempMonitorService

service = TempMonitorService()

router = APIRouter(prefix="/api/temp_monitor", tags=["温控监测"])

LIST_FIELDS = ["记录编号", "运单编号", "当前温度", "温度上限", "温度下限", "记录时间", "设备编号", "记录状态"]
STATUSES = ["正常", "接近临界", "超温", "数据缺失"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号或运单编号检索"),
    status: str | None = Query(default=None, description="正常、接近临界、超温、数据缺失"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号与状态过滤温控监测列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/dashboard")
def dashboard() -> dict[str, Any]:
    """温控看板：各状态/各级超温/待处理报警数量，直接由记录明细与报警待办汇总。"""
    return service.dashboard()


@router.get("/rules")
def list_rules() -> dict[str, Any]:
    """多级超温规则清单：按业务优先级展示阈值与是否生成报警。"""
    return {"module": "temp_monitor", "rules": service.rule_catalog()}


@router.get("/checkpoint")
def get_checkpoint(stream: str = "default") -> dict[str, Any]:
    """查看接口接入断点；恢复后从该断点继续，不会重复处理。"""
    return service.checkpoint(stream)


@router.post("/ingest", response_model=TempIngestResult)
def ingest_records(payload: TempIngestPayload) -> TempIngestResult:
    """接口批量接入温度记录：逐条判定并回写报警待办。

    中断（fail_after 模拟）时返回 202 与断点；用同一批数据重试即从断点继续，
    已处理记录幂等跳过，不会重复生成报警。
    """
    try:
        result = service.ingest(payload.records, stream=payload.stream, fail_after=payload.fail_after)
    except IngestInterrupted as exc:
        return TempIngestResult(
            ok=False,
            stream=exc.stream,
            checkpoint=exc.checkpoint,
            processed=exc.processed,
            interrupted=True,
            message=f"接口中断，断点已保留在序号 {exc.checkpoint}；恢复后重试即可继续，已接入记录不会重复生成报警",
        )
    return TempIngestResult(message="温度记录接入完成", **result)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出温控监测清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "temp_monitor", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条温度记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"温度记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条温度记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="温度记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条温度记录执行标记预警、确认超温、数据补录；不允许的动作会被拦下并说明原因。

    数据补录可在 values 里携带更新后的 当前温度/温度上限/温度下限，服务端会重新跑
    多级规则并同步报警待办。
    """
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
