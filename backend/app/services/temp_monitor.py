"""温控监测业务规则：多级超温判定、报警回写、断点续传都收在这里。

核心约定：
- 温度记录接入后，按温度上下限建立多级超温规则；多规则同时命中时以业务优先级为准。
- 超温结论回写报警待办（alert 模块），报警待办、温控看板与记录明细共用同一份判定结果。
- 上下限缺失或接口中断时维持当前判定，恢复后从断点继续，不重复生成报警。
"""
from __future__ import annotations

from typing import Any, Callable

from app.store import store

MODULE = "temp_monitor"
ALERT_MODULE = "alert"
REQUIRED_FIELDS = ["记录编号", "运单编号", "当前温度"]
STATUS_ORDER = ["正常", "接近临界", "超温", "严重超温", "数据缺失"]

# 手动动作：保留原有入口，动作执行后仍按规则重新判定，保证结论一致。
ACTION_RULES = {"标记预警": "接近临界", "确认超温": "超温", "数据补录": "正常"}

# 回写状态：not_required 无需回写 | pending 待回写 | done 已回写
WRITE_BACK_NOT_REQUIRED = "not_required"
WRITE_BACK_PENDING = "pending"
WRITE_BACK_DONE = "done"

# 接口状态：normal 正常 | interrupted 中断
INTERFACE_NORMAL = "normal"
INTERFACE_INTERRUPTED = "interrupted"

# 多级超温阈值：距上下限多少度以内算接近临界，超出多少度算严重超温。
WARN_DELTA = 1.0
SEVERE_DELTA = 3.0


def _to_number(value: Any) -> float | None:
    """把值转成数字；无法解析时返回 None，表示该字段缺失。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _rule_normal(t: float, u: float, l: float) -> bool:
    return True


def _rule_warning(t: float, u: float, l: float) -> bool:
    return t > u - WARN_DELTA or t < l + WARN_DELTA


def _rule_overtemp(t: float, u: float, l: float) -> bool:
    return t > u or t < l


def _rule_severe(t: float, u: float, l: float) -> bool:
    return t > u + SEVERE_DELTA or t < l - SEVERE_DELTA


# 多级超温规则：按业务优先级从高到低匹配，命中即止。
# priority 越大越优先；多条规则同时命中时以高优先级为准。
TEMP_RULES: list[dict[str, Any]] = [
    {"name": "严重超温", "priority": 40, "match": _rule_severe},
    {"name": "超温", "priority": 30, "match": _rule_overtemp},
    {"name": "接近临界", "priority": 20, "match": _rule_warning},
    {"name": "正常", "priority": 10, "match": _rule_normal},
]

# 需要回写报警的状态
ALERT_STATUSES = {"超温", "严重超温"}


def judge_temperature(current: Any, upper: Any, lower: Any) -> str | None:
    """根据温度上下限判定状态。

    上下限缺失或无法解析时返回 None，表示维持当前判定、不重新判定。
    多规则同时命中时按业务优先级从高到低匹配，命中即止。
    """
    t = _to_number(current)
    u = _to_number(upper)
    l = _to_number(lower)
    if t is None or u is None or l is None:
        return None
    for rule in sorted(TEMP_RULES, key=lambda r: -int(r["priority"])):
        match: Callable[[float, float, float], bool] = rule["match"]
        if match(t, u, l):
            return str(rule["name"])
    return "正常"


class TempMonitorService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["温度上限"] = values.get("温度上限")
        entry["温度下限"] = values.get("温度下限")
        entry["记录时间"] = values.get("记录时间")
        entry["设备编号"] = values.get("设备编号")
        # 按规则自动判定；上下限缺失时维持「数据缺失」判定。
        judged = judge_temperature(entry.get("当前温度"), entry.get("温度上限"), entry.get("温度下限"))
        if judged is None:
            entry["status"] = "数据缺失"
            entry["记录状态"] = "数据缺失"
            entry["回写状态"] = WRITE_BACK_NOT_REQUIRED
        else:
            entry["status"] = judged
            entry["记录状态"] = judged
            entry["回写状态"] = WRITE_BACK_PENDING if judged in ALERT_STATUSES else WRITE_BACK_NOT_REQUIRED
        entry["pending"] = entry["status"] != "正常"
        entry["abnormal"] = entry["status"] in ALERT_STATUSES
        rows.append(entry)
        # 超温结论回写报警待办
        self._write_back_alert(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"温度记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于温控监测可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        # 手动动作后仍按规则重新判定，保证结论一致
        judged = judge_temperature(entry.get("当前温度"), entry.get("温度上限"), entry.get("温度下限"))
        if judged is not None:
            entry["status"] = judged
            entry["记录状态"] = judged
        else:
            entry["status"] = target
            entry["记录状态"] = target
        entry["pending"] = entry["status"] != "正常"
        entry["abnormal"] = entry["status"] in ALERT_STATUSES
        # 状态变化后重新评估回写需求
        if entry["status"] in ALERT_STATUSES:
            if entry.get("回写状态") != WRITE_BACK_DONE:
                entry["回写状态"] = WRITE_BACK_PENDING
        else:
            entry["回写状态"] = WRITE_BACK_NOT_REQUIRED
        self._write_back_alert(entry)
        return entry, f"温度记录已{action}"

    def ingest_readings(self, readings: list[dict[str, Any]]) -> dict[str, Any]:
        """批量接入温度记录：逐条判定并回写，接口中断时维持当前判定。

        返回处理结果与断点信息；接口中断时不推进断点，恢复后从断点继续。
        """
        interface = store.state("temp_monitor_interface") or INTERFACE_NORMAL
        checkpoint = int(store.state("temp_monitor_checkpoint") or 0)
        processed = 0
        skipped = 0
        write_back = 0
        # 接口中断：不推进、不回写，维持当前判定
        if interface == INTERFACE_INTERRUPTED:
            return {
                "ok": False,
                "message": "温度记录接入接口已中断，维持当前判定，恢复后从断点继续",
                "processed": 0,
                "skipped": len(readings),
                "write_back": 0,
                "checkpoint": checkpoint,
                "interface": interface,
            }
        for reading in readings:
            record_id = reading.get("id")
            if record_id is not None and int(record_id) <= checkpoint:
                skipped += 1
                continue
            entry, missing = self.create_entry(reading)
            if entry is None:
                skipped += 1
                continue
            processed += 1
            if entry.get("回写状态") == WRITE_BACK_DONE:
                write_back += 1
            # 推进断点
            store.set_state("temp_monitor_checkpoint", int(entry["id"]))
            checkpoint = int(entry["id"])
        return {
            "ok": True,
            "message": f"接入完成：处理 {processed} 条，跳过 {skipped} 条，回写报警 {write_back} 条",
            "processed": processed,
            "skipped": skipped,
            "write_back": write_back,
            "checkpoint": checkpoint,
            "interface": interface,
        }

    def retry_pending_write_backs(self) -> dict[str, Any]:
        """从断点继续：补写所有待回写的超温结论，不重复生成报警。"""
        interface = store.state("temp_monitor_interface") or INTERFACE_NORMAL
        if interface == INTERFACE_INTERRUPTED:
            return {
                "ok": False,
                "message": "报警回写接口已中断，维持当前判定，恢复后从断点继续",
                "write_back": 0,
                "checkpoint": int(store.state("temp_monitor_checkpoint") or 0),
                "interface": interface,
            }
        write_back = 0
        for entry in store.rows(MODULE):
            if entry.get("回写状态") == WRITE_BACK_PENDING:
                self._write_back_alert(entry)
                if entry.get("回写状态") == WRITE_BACK_DONE:
                    write_back += 1
        return {
            "ok": True,
            "message": f"断点续传完成：补写报警 {write_back} 条",
            "write_back": write_back,
            "checkpoint": int(store.state("temp_monitor_checkpoint") or 0),
            "interface": interface,
        }

    def set_interface(self, state: str) -> dict[str, Any]:
        """设置接口状态：normal 恢复 | interrupted 中断。"""
        if state not in (INTERFACE_NORMAL, INTERFACE_INTERRUPTED):
            return {"ok": False, "message": f"非法接口状态：{state}"}
        store.set_state("temp_monitor_interface", state)
        return {
            "ok": True,
            "message": f"接口已{'恢复' if state == INTERFACE_NORMAL else '中断'}",
            "interface": state,
            "checkpoint": int(store.state("temp_monitor_checkpoint") or 0),
        }

    def get_checkpoint(self) -> dict[str, Any]:
        return {
            "checkpoint": int(store.state("temp_monitor_checkpoint") or 0),
            "interface": store.state("temp_monitor_interface") or INTERFACE_NORMAL,
            "pending_write_back": sum(
                1 for row in store.rows(MODULE) if row.get("回写状态") == WRITE_BACK_PENDING
            ),
        }

    def get_rules(self) -> dict[str, Any]:
        return {
            "rules": [
                {"name": r["name"], "priority": r["priority"]} for r in TEMP_RULES
            ],
            "warn_delta": WARN_DELTA,
            "severe_delta": SEVERE_DELTA,
            "statuses": STATUS_ORDER,
        }

    def _write_back_alert(self, entry: dict[str, Any]) -> None:
        """超温结论回写报警待办；已生成过报警的不重复生成。"""
        if entry.get("回写状态") == WRITE_BACK_DONE:
            return
        status = entry.get("status")
        if status not in ALERT_STATUSES:
            entry["回写状态"] = WRITE_BACK_NOT_REQUIRED
            return
        # 去重：同一温度记录只生成一条报警
        record_id = entry.get("id")
        existing = [
            a for a in store.rows(ALERT_MODULE)
            if a.get("关联温度记录") == record_id
        ]
        if existing:
            entry["回写状态"] = WRITE_BACK_DONE
            return
        rows = store.rows(ALERT_MODULE)
        alert_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        alert_entry: dict[str, Any] = {
            "id": alert_id,
            "status": "未处理",
            "pending": True,
            "abnormal": True,
            "报警编号": f"ALER-TEMP-{record_id}",
            "报警类型": "温度超温",
            "关联设备": entry.get("设备编号") or "",
            "报警阈值": f"{entry.get('温度下限')}~{entry.get('温度上限')}",
            "触发值": str(entry.get("当前温度")),
            "触发时间": entry.get("记录时间") or "",
            "处置措施": "",
            "报警状态": "未处理",
            "关联温度记录": record_id,
            "关联运单": entry.get("运单编号") or "",
            "超温等级": status,
        }
        rows.append(alert_entry)
        entry["回写状态"] = WRITE_BACK_DONE
