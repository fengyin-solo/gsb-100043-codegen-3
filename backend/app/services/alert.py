"""报警管理业务规则：状态流转、字段校验与筛选口径都收在这里。

除人工登记外，温控规则引擎会把超温结论回写成报警待办。回写入口集中在
``raise_temp_alert`` / ``resolve_temp_alert``：按来源温度记录编号定位同一报警
（同一轮超温事件只允许存在一条未消除报警），保证「不重复生成报警」。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "alert"
REQUIRED_FIELDS = ["报警编号", "报警类型", "关联设备"]
STATUS_ORDER = ["未处理", "已确认", "处理中", "已消除"]
ACTION_RULES = {"确认报警": "已确认", "开始处理": "处理中", "消除报警": "已消除"}
NEGATIVE_ACTIONS = []

# 由温控超温自动回写的报警统一用此前缀，和人工登记的编号区分开。
TEMP_ALERT_PREFIX = "ALER-T"


class AlertService:
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
            rows = [row for row in rows if keyword in str(row.get("报警编号", ""))]
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
        entry = {"id": self._next_id()}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"报警记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于报警管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"报警记录已{action}"

    # ------------------------------------------------------------------
    # 温控超温回写：同一来源记录的同一轮超温事件复用同一条报警待办
    # ------------------------------------------------------------------

    def open_temp_alert(self, source_record: str) -> dict[str, Any] | None:
        """找到某条温度记录当前未消除的超温报警；没有则返回 None。"""
        for row in store.rows(MODULE):
            if row.get("来源记录编号") == source_record and row.get("status") != "已消除":
                return row
        return None

    def raise_temp_alert(
        self,
        *,
        source_record: str,
        device: str,
        alarm_type: str,
        threshold: str,
        trigger_value: str,
        trigger_time: str,
        rule_name: str,
        waybill: str = "",
    ) -> tuple[dict[str, Any], bool]:
        """把超温结论回写成报警待办。

        已有未消除报警（同一轮超温）时只更新触发值/级别，不新建；
        返回 (报警记录, 是否新建)。
        """
        rows = store.rows(MODULE)
        existing = self.open_temp_alert(source_record)
        if existing is not None:
            existing["报警类型"] = alarm_type
            existing["报警阈值"] = threshold
            existing["触发值"] = trigger_value
            existing["处置措施"] = f"持续超温，按{rule_name}跟踪"
            existing["触发时间"] = trigger_time
            if device:
                existing["关联设备"] = device
            existing["报警状态"] = existing["status"]
            return existing, False

        entry = {"id": self._next_id()}
        entry.update({
            "报警编号": self._next_temp_code(rows),
            "报警类型": alarm_type,
            "关联设备": device or "未绑定设备",
            "报警阈值": threshold,
            "触发值": trigger_value,
            "触发时间": trigger_time,
            "处置措施": f"{rule_name}，等待处置",
            "报警状态": STATUS_ORDER[0],
            "来源记录编号": source_record,
            "来源运单编号": waybill,
        })
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = True
        rows.append(entry)
        return entry, True

    def resolve_temp_alert(self, source_record: str, *, measure: str = "温度恢复正常，自动消除") -> dict[str, Any] | None:
        """温度恢复后自动消除该记录未处理的超温报警；没有未消除报警则不动。"""
        existing = self.open_temp_alert(source_record)
        if existing is None:
            return None
        existing["status"] = "已消除"
        existing["报警状态"] = "已消除"
        existing["pending"] = False
        existing["abnormal"] = False
        existing["处置措施"] = measure
        return existing

    # ------------------------------------------------------------------

    def _next_id(self) -> int:
        return max((int(row.get("id", 0)) for row in store.rows(MODULE)), default=0) + 1

    def _next_temp_code(self, rows: list[dict[str, Any]]) -> str:
        used = {str(row.get("报警编号", "")) for row in rows}
        index = 1
        while f"{TEMP_ALERT_PREFIX}-{index:04d}" in used:
            index += 1
        return f"{TEMP_ALERT_PREFIX}-{index:04d}"
