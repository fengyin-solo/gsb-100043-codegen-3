"""温控监测业务规则。

温度记录接入（接口批量导入或人工登记）后，统一交给
:mod:`app.services.temp_rules` 多级超温规则引擎判定：

* 多规则同时命中时按业务优先级取最高一条，超温结论回写报警待办；
* 报警待办、温控看板、记录明细都直接读同一份判定字段，保证三处一致；
* 上下限缺失或无法解析时不做新判定，维持记录当前结论；
* 接口接入带断点（checkpoint + 来源记录幂等），中断恢复后从断点继续，
  已处理的记录不会重复生成报警；
* 同一轮超温事件全程只对应一条报警待办，温度恢复后自动消除。
"""
from __future__ import annotations

from typing import Any

from app.services import temp_rules as rules
from app.services.alert import AlertService
from app.store import store

MODULE = "temp_monitor"
REQUIRED_FIELDS = ["记录编号", "运单编号", "当前温度"]
OPTIONAL_FIELDS = ["温度上限", "温度下限", "记录时间", "设备编号"]
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS
STATUS_ORDER = ["正常", "接近临界", "超温", "数据缺失"]
ACTION_RULES = {"标记预警": "接近临界", "确认超温": "超温", "数据补录": "正常"}
NEGATIVE_ACTIONS = []

# 判定字段回写到记录上，看板和明细都读这些字段，避免各算各的。
JUDGMENT_KEYS = (
    "命中规则", "同时命中", "规则优先级", "超温方向", "超温幅度", "判定依据", "关联报警",
)


class TempMonitorService:
    def __init__(self) -> None:
        self.alerts = AlertService()
        # 接口接入断点：每个流（stream）记已处理到的全局序号与已处理来源记录。
        # 真实项目落库；内存版放在服务实例里即可演示「中断恢复」。
        self._checkpoints: dict[str, dict[str, Any]] = {}
        self._bootstrapped = False

    # ------------------------------------------------------------------
    # 查询 / 看板
    # ------------------------------------------------------------------

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
            rows = [
                row
                for row in rows
                if keyword in str(row.get("记录编号", "")) or keyword in str(row.get("运单编号", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def dashboard(self) -> dict[str, Any]:
        """温控看板：统计口径与记录明细、报警待办完全同源。"""
        rows = store.rows(MODULE)
        by_status = {status: 0 for status in STATUS_ORDER}
        by_level = {"超限": 0, "一级超温": 0, "二级超温": 0, "三级超温": 0}
        open_alert_records: set[str] = set()
        for alert in store.rows("alert"):
            if alert.get("来源记录编号") and alert.get("status") != "已消除":
                open_alert_records.add(str(alert["来源记录编号"]))
        for row in rows:
            status = str(row.get("status") or "")
            if status in by_status:
                by_status[status] += 1
            rule_name = str(row.get("命中规则") or "")
            if rule_name in by_level:
                by_level[rule_name] += 1
        return {
            "total": len(rows),
            "正常": by_status["正常"],
            "接近临界": by_status["接近临界"],
            "超温": by_status["超温"],
            "数据缺失": by_status["数据缺失"],
            "超限": by_level["超限"],
            "一级超温": by_level["一级超温"],
            "二级超温": by_level["二级超温"],
            "三级超温": by_level["三级超温"],
            "待处理超温报警": len(open_alert_records),
            "rules": rules.rule_catalog(),
        }

    def rule_catalog(self) -> list[dict[str, Any]]:
        return rules.rule_catalog()

    # ------------------------------------------------------------------
    # 人工登记 / 动作
    # ------------------------------------------------------------------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in ALL_FIELDS})
        entry.setdefault("记录时间", "")
        entry.setdefault("设备编号", "")
        self._init_entry_flags(entry, "数据缺失")
        rows.append(entry)
        # 登记即接入规则；上下限缺失时维持初始判定，不生成报警。
        self._apply_judgment(entry, reason_when_skipped="已登记，等待温度上下限后判定")
        return entry, []

    def run_action(self, entry_id: int, action: str, values: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"温度记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于温控监测可执行范围"
        values = values or {}

        if action == "数据补录":
            # 允许补录温度/上下限后重新跑规则，结论与报警自动对齐。
            for field in ("当前温度", "温度上限", "温度下限", "记录时间", "设备编号", "运单编号"):
                text = str(values.get(field) or "").strip()
                if text:
                    entry[field] = text
            outcome, _ = self._apply_judgment(entry)
            if outcome is None:
                return entry, "温度上下限缺失，已维持当前判定"
            return entry, f"数据补录完成，重新判定为{entry['status']}"

        if action == "确认超温":
            # 以规则引擎为准重算；若数据完整则同步/新建报警，避免人工与规则打架。
            outcome, _ = self._apply_judgment(entry)
            if outcome is not None and outcome.is_over_temp:
                return entry, f"已确认超温：命中{entry['命中规则']}，报警待办已同步"
            if outcome is not None:
                return entry, f"规则判定为{outcome.status}，未生成超温报警"
            return entry, "温度上下限缺失，已维持当前判定"

        # 标记预警：人工临界限动作，不改变规则结论之外的报警。
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["记录状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = target in ("接近临界", "超温")
        entry["判定依据"] = "人工标记预警"
        return entry, "温度记录已标记预警"

    # ------------------------------------------------------------------
    # 接口接入：批量导入 + 断点续传 + 幂等
    # ------------------------------------------------------------------

    def ingest(self, records: list[dict[str, Any]], *, stream: str = "default", fail_after: int | None = None) -> dict[str, Any]:
        """接入一批温度记录并逐条判定。

        * fail_after 模拟接口中断：处理满该条数后抛出（演示用），断点保留；
        * 断点 checkpoint 记已处理的全局序号 seq；
        * 同时按来源记录编号幂等去重，重试/补传不会重复建记录、重复报警；
        * 恢复后再次调用同一批（或补传的后续批次）即从断点继续。
        """
        checkpoint = self._checkpoints.setdefault(stream, {"seq": 0, "records": []})
        processed: list[str] = list(checkpoint["records"])
        seen: set[str] = set(processed)

        ingested, updated, skipped, alarms = 0, 0, 0, 0
        new_alarms = 0
        for item in records:
            seq = int(item.get("seq") or 0)
            record_no = str(item.get("记录编号") or "").strip()
            if not record_no or seq <= 0:
                skipped += 1
                continue
            if seq <= int(checkpoint["seq"]) or record_no in seen:
                # 断点之前/已处理过：幂等跳过，不重复判定、不重复报警。
                skipped += 1
                continue

            existed = self._upsert_record(item)
            if existed is None:
                skipped += 1
                continue

            entry, created = existed
            _judgment, alarm_created = self._apply_judgment(entry)
            if created:
                ingested += 1
            else:
                updated += 1
            if alarm_created:
                new_alarms += 1
            if entry.get("关联报警"):
                alarms += 1

            checkpoint["seq"] = seq
            checkpoint["records"].append(record_no)
            seen.add(record_no)

            if fail_after is not None and (ingested + updated) >= fail_after:
                raise IngestInterrupted(
                    stream=stream,
                    checkpoint=int(checkpoint["seq"]),
                    processed=ingested + updated,
                )

        return {
            "stream": stream,
            "checkpoint": int(checkpoint["seq"]),
            "processed": ingested + updated,
            "ingested": ingested,
            "updated": updated,
            "skipped": skipped,
            "new_alarms": new_alarms,
            "open_over_temp_alarms": alarms,
            "interrupted": False,
        }

    def checkpoint(self, stream: str = "default") -> dict[str, Any]:
        checkpoint = self._checkpoints.get(stream)
        return {"stream": stream, "seq": int(checkpoint["seq"]) if checkpoint else 0,
                "processed": len(checkpoint["records"]) if checkpoint else 0}

    # ------------------------------------------------------------------
    # 启动引导：对种子数据统一跑一遍规则，使看板/明细/报警初始即一致
    # ------------------------------------------------------------------

    def bootstrap(self) -> None:
        if self._bootstrapped:
            return
        self._bootstrapped = True
        for entry in store.rows(MODULE):
            self._apply_judgment(entry)

    # ------------------------------------------------------------------
    # 内部：记录落库、判定应用与报警回写
    # ------------------------------------------------------------------

    def _upsert_record(self, item: dict[str, Any]) -> tuple[dict[str, Any], bool] | None:
        record_no = str(item.get("记录编号") or "").strip()
        if not record_no:
            return None
        rows = store.rows(MODULE)
        entry = next((row for row in rows if str(row.get("记录编号") or "") == record_no), None)
        created = entry is None
        if created:
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            self._init_entry_flags(entry, "数据缺失")
            rows.append(entry)
        for field in ("记录编号", "运单编号", "当前温度", "温度上限", "温度下限", "记录时间", "设备编号"):
            if field in item and str(item.get(field) or "") != "":
                entry[field] = str(item.get(field))
        entry.setdefault("运单编号", "")
        entry.setdefault("记录时间", "")
        entry.setdefault("设备编号", "")
        if created:
            # 判定前先把一致性字段占位，保证上下限缺失维持判定时明细结构也完整。
            for key in JUDGMENT_KEYS:
                entry.setdefault(key, "")
        return entry, created

    @staticmethod
    def _init_entry_flags(entry: dict[str, Any], status: str) -> None:
        entry["status"] = status
        entry["记录状态"] = status
        entry["pending"] = status != STATUS_ORDER[-1]
        entry["abnormal"] = status in ("接近临界", "超温")
        for key in JUDGMENT_KEYS:
            entry.setdefault(key, "")

    def _apply_judgment(self, entry: dict[str, Any], *, reason_when_skipped: str | None = None) -> tuple[rules.Judgment | None, bool]:
        """对单条记录执行规则并把结论写回记录 + 同步报警待办。

        上下限缺失/无法解析时返回 None，记录维持当前判定（status 等一律不动）。
        返回 (判定结论, 本次是否新建了报警待办)；数据缺失判定也会返回。
        """
        judgment = rules.evaluate(entry.get("当前温度"), entry.get("温度上限"), entry.get("温度下限"))
        if judgment is None:
            if reason_when_skipped:
                entry["判定依据"] = reason_when_skipped
            else:
                temp_hi = rules.to_float(entry.get("温度上限"))
                temp_lo = rules.to_float(entry.get("温度下限"))
                entry["判定依据"] = rules.REASON_MISSING_LIMIT if temp_hi is None or temp_lo is None else rules.REASON_BAD_LIMIT
            return None, False

        # 数据缺失（温度本身取不到）：标记状态但不清空既有超温/报警信息。
        if judgment.status == rules.DATA_MISSING:
            entry["status"] = rules.DATA_MISSING
            entry["记录状态"] = rules.DATA_MISSING
            entry["pending"] = True
            entry["abnormal"] = False
            for key in JUDGMENT_KEYS:
                entry.setdefault(key, "")
            entry["判定依据"] = judgment.reason or "温度数据缺失，维持当前判定"
            return judgment, False

        record_no = str(entry.get("记录编号") or "")
        prior_status = str(entry.get("status") or "")
        entry["status"] = judgment.status
        entry["记录状态"] = judgment.status
        entry["pending"] = judgment.status != "正常"
        entry["abnormal"] = judgment.status in ("接近临界", "超温")
        entry["命中规则"] = judgment.rule_name or ""
        entry["规则优先级"] = judgment.rule.priority if judgment.rule else 0
        entry["同时命中"] = "、".join(rule.name for rule in judgment.matched)
        entry["超温方向"] = {"upper": "超上限", "lower": "超下限"}.get(judgment.direction or "", "")
        entry["超温幅度"] = f"{judgment.delta:g}℃" if judgment.delta is not None else ""
        if judgment.levels > 1:
            entry["判定依据"] = f"同时命中{judgment.levels}级规则，按业务优先级采用「{judgment.rule_name}」"
        elif judgment.rule is not None:
            entry["判定依据"] = f"命中规则「{judgment.rule_name}」"
        else:
            entry["判定依据"] = "温度在上下限范围内"

        alarm_created = False
        if judgment.is_over_temp and record_no:
            trigger_value = f"{entry.get('当前温度')}（{entry['超温方向']}{entry['超温幅度']}）"
            alert, alarm_created = self.alerts.raise_temp_alert(
                source_record=record_no,
                device=str(entry.get("设备编号") or ""),
                alarm_type=judgment.alarm_type or "超温报警",
                threshold=judgment.threshold_text(),
                trigger_value=trigger_value,
                trigger_time=str(entry.get("记录时间") or ""),
                rule_name=judgment.rule_name or "超温",
                waybill=str(entry.get("运单编号") or ""),
            )
            entry["关联报警"] = alert["报警编号"]
        else:
            # 恢复正常/临界限：自动消除该记录未消除的超温报警。
            if prior_status == rules.OVER_TEMP and record_no:
                self.alerts.resolve_temp_alert(record_no)
            open_alert = self.alerts.open_temp_alert(record_no) if record_no else None
            entry["关联报警"] = open_alert["报警编号"] if open_alert else ""
        return judgment, alarm_created


class IngestInterrupted(RuntimeError):
    """接口中断（演示用）：断点已保留，恢复后可从 checkpoint 继续。"""

    def __init__(self, *, stream: str, checkpoint: int, processed: int) -> None:
        super().__init__(f"温度记录接口在断点 {checkpoint} 处中断，已处理 {processed} 条")
        self.stream = stream
        self.checkpoint = checkpoint
        self.processed = processed
