"""多级超温规则引擎。

规则围绕温度上下限建立：每一级规则用「超出上下限的幅度（℃）」表达，并给出
业务优先级 priority——温度同时命中多条规则（例如超 8℃ 必然也超 2℃）时，
取 priority 最大的一条作为唯一超温结论，报警待办也只回写这一条。

规则列表按业务优先级从低到高排列；要调整业务口径（新增级别、改阈值、改优先级）
只改这张表即可。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OverTempRule:
    """一条超温/临界限规则。

    direction: 规则适用方向——上限超限 upper、下限超限 lower、不区分方向 both。
    min_delta: 超出边界的最小幅度（含边界，>=）；None 表示不要求超出（临界限规则用）。
    max_delta: 超出边界的最大幅度（不含边界，<）；None 表示上不封顶。
    alarm:     命中是否生成报警待办：只有真正超温才生成，临界限只预警不报警。
    """

    code: str
    name: str
    status: str
    direction: str  # upper / lower / both
    min_delta: float | None
    max_delta: float | None
    priority: int
    alarm_type: str
    alarm: bool = True

    def matches(self, direction: str, delta: float) -> bool:
        if self.direction != "both" and self.direction != direction:
            return False
        if self.min_delta is not None and delta < self.min_delta:
            return False
        if self.max_delta is not None and delta >= self.max_delta:
            return False
        return True


# 业务优先级：一级超温 < 二级超温 < 三级超温；临界限预警优先级低于所有超温。
# 超温各级都只设下限阈值（超 2℃/5℃/8℃ 即命中），因此高温会同时命中多条规则
# （例如超 8℃ 同时满足三级的全部阈值），正好覆盖
# 「多规则同时命中时以业务优先级为准」的场景。
RULES: list[OverTempRule] = [
    OverTempRule("WARN_HIGH", "接近上限预警", "接近临界", "upper", None, 2.0, 10, "温度预警", alarm=False),
    OverTempRule("WARN_LOW", "接近下限预警", "接近临界", "lower", None, 2.0, 10, "温度预警", alarm=False),
    OverTempRule("L0", "超限", "超温", "both", 0.0, 2.0, 15, "超温报警"),
    OverTempRule("L1", "一级超温", "超温", "both", 2.0, None, 20, "一级超温报警"),
    OverTempRule("L2", "二级超温", "超温", "both", 5.0, None, 30, "二级超温报警"),
    OverTempRule("L3", "三级超温", "超温", "both", 8.0, None, 40, "三级超温报警"),
]

NORMAL = "正常"
NEAR_LIMIT = "接近临界"
OVER_TEMP = "超温"
DATA_MISSING = "数据缺失"

# 判定原因：上下限缺失/无法解析、温度无法解析时不能做任何判定。
REASON_MISSING_LIMIT = "温度上下限缺失，维持当前判定"
REASON_BAD_LIMIT = "温度上下限无法解析，维持当前判定"
REASON_MISSING_TEMP = "当前温度缺失，暂不判定"
REASON_BAD_TEMP = "当前温度无法解析，暂不判定"


def to_float(value: object) -> float | None:
    """把接口/导入里可能是数字、字符串（如 '12.5℃'）的温度值解析成 float。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("℃", "").replace("°C", "").replace(" ", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class Judgment:
    """对一条温度记录执行规则后的判定结论。"""

    status: str
    rule: OverTempRule | None
    matched: list[OverTempRule]
    direction: str | None          # upper / lower / both / None
    delta: float | None            # 超出边界的幅度（非负）
    rule_code: str | None
    rule_name: str | None
    levels: int                    # 同时命中的规则条数（不含临界限）
    reason: str | None = None

    @property
    def is_over_temp(self) -> bool:
        return self.status == OVER_TEMP

    @property
    def alarm_type(self) -> str | None:
        return self.rule.alarm_type if self.rule is not None and self.rule.alarm else None

    def threshold_text(self) -> str:
        """报警待办「报警阈值」列展示口径。"""
        if self.rule is None or self.delta is None:
            return ""
        side = "上限" if self.direction == "upper" else "下限"
        if self.rule.max_delta is not None:
            return f"超{side}{self.rule.min_delta:g}~{self.rule.max_delta:g}℃"
        return f"超{side}≥{self.rule.min_delta:g}℃"


def matched_rules(direction: str, delta: float, *, in_band: bool = False) -> list[OverTempRule]:
    """返回某条记录同时命中的全部规则，按业务优先级升序。

    临界限预警（alarm=False）只在温度仍在限内（in_band）时参与；一旦越界，
    只由超温规则判定，避免「已经超限却只记预警」。
    """
    return [
        rule
        for rule in RULES
        if (in_band != rule.alarm) and rule.matches(direction, delta)
    ]


def evaluate(current: object, upper: object, lower: object) -> Judgment | None:
    """按上下限对一条温度记录跑多级规则。

    上下限缺失或无法解析时返回 None（上层维持当前判定）；温度本身缺失/无法解析时
    返回数据缺失判定，但不改变既有超温结论。
    """
    temp = to_float(current)
    hi = to_float(upper)
    lo = to_float(lower)

    if hi is None or lo is None:
        return None
    if hi <= lo:
        return None
    if temp is None:
        return Judgment(DATA_MISSING, None, [], None, None, None, None, 0,
                        REASON_MISSING_TEMP if str(current or "").strip() == "" else REASON_BAD_TEMP)

    if temp > hi:
        direction = "upper"
        delta = round(temp - hi, 4)
    elif temp < lo:
        direction = "lower"
        delta = round(lo - temp, 4)
    else:
        # 带内只可能命中临界限预警：按到最近边界的距离判定，贴边（距离 0）算正常。
        gap_hi = round(hi - temp, 4)
        gap_lo = round(temp - lo, 4)
        if gap_hi == 0 or gap_lo == 0:
            return Judgment(NORMAL, None, [], None, None, None, None, 0)
        if gap_hi <= gap_lo:
            direction, delta = "upper", gap_hi
        else:
            direction, delta = "lower", gap_lo

    hits = matched_rules(direction, delta, in_band=temp <= hi and temp >= lo)
    if not hits:
        # 在限内且不贴临界限：正常。
        return Judgment(NORMAL, None, [], direction, delta, None, None, 0)

    # 业务优先级仲裁：多规则同时命中时只保留优先级最高的一条。
    winner = max(hits, key=lambda rule: rule.priority)
    over_hits = [rule for rule in hits if rule.alarm]
    return Judgment(
        winner.status,
        winner,
        hits,
        direction,
        delta,
        winner.code,
        winner.name,
        len(over_hits),
    )


def rule_catalog() -> list[dict[str, object]]:
    """规则清单（看板/接口展示用），按业务优先级排序。"""
    return [
        {
            "code": rule.code,
            "name": rule.name,
            "status": rule.status,
            "direction": {"upper": "上限", "lower": "下限", "both": "上下限"}[rule.direction],
            "min_delta": rule.min_delta,
            "max_delta": rule.max_delta,
            "priority": rule.priority,
            "alarm_type": rule.alarm_type,
            "alarm": rule.alarm,
        }
        for rule in sorted(RULES, key=lambda rule: rule.priority)
    ]
