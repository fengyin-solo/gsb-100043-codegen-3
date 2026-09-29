"""接口出入参模型：列表分页、动作结果与各模块的明细结构。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    """登记或修改一条业务记录时提交的字段集合。"""

    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class TempIngestPayload(BaseModel):
    """设备/接口批量上报的温度记录。seq 为流内全局递增序号，用作断点。"""

    records: list[dict[str, Any]] = Field(default_factory=list)
    stream: str = "default"
    fail_after: int | None = None


class TempIngestResult(BaseModel):
    """接入结果：含断点序号，中断时把断点带回去，恢复后从这里继续。"""

    ok: bool = True
    stream: str = "default"
    checkpoint: int = 0
    processed: int = 0
    ingested: int = 0
    updated: int = 0
    skipped: int = 0
    new_alarms: int = 0
    open_over_temp_alarms: int = 0
    interrupted: bool = False
    message: str = ""



class ShipmentEntry(BaseModel):
    """发运单明细结构。"""

    field_0: str | None = None  # 运单编号
    field_1: str | None = None  # 发货方
    field_2: str | None = None  # 收货方
    field_3: str | None = None  # 货物名称
    field_4: str | None = None  # 温层要求
    field_5: str | None = None  # 发运日期
    field_6: str | None = None  # 预计到达
    field_7: str | None = None  # 运单状态

class TempMonitorEntry(BaseModel):
    """温度记录明细结构。"""

    field_0: str | None = None  # 记录编号
    field_1: str | None = None  # 运单编号
    field_2: str | None = None  # 当前温度
    field_3: str | None = None  # 温度上限
    field_4: str | None = None  # 温度下限
    field_5: str | None = None  # 记录时间
    field_6: str | None = None  # 设备编号
    field_7: str | None = None  # 记录状态

class VehicleEntry(BaseModel):
    """冷藏车辆明细结构。"""

    field_0: str | None = None  # 车辆编号
    field_1: str | None = None  # 车牌号
    field_2: str | None = None  # 车型类别
    field_3: str | None = None  # 温层能力
    field_4: str | None = None  # 制冷机组型号
    field_5: str | None = None  # 上次维保日
    field_6: str | None = None  # 当前位置
    field_7: str | None = None  # 车辆状态

class DriverEntry(BaseModel):
    """驾驶人员明细结构。"""

    field_0: str | None = None  # 司机编号
    field_1: str | None = None  # 姓名
    field_2: str | None = None  # 驾驶证号
    field_3: str | None = None  # 从业资格证
    field_4: str | None = None  # 健康证有效期
    field_5: str | None = None  # 联系手机
    field_6: str | None = None  # 所属车队
    field_7: str | None = None  # 司机状态

class ColdStorageEntry(BaseModel):
    """冷库库区明细结构。"""

    field_0: str | None = None  # 库区编号
    field_1: str | None = None  # 库区名称
    field_2: str | None = None  # 设定温度
    field_3: str | None = None  # 当前温度
    field_4: str | None = None  # 库容利用率
    field_5: str | None = None  # 作业班组
    field_6: str | None = None  # 巡检时间
    field_7: str | None = None  # 库区状态

class LoadingEntry(BaseModel):
    """装卸记录明细结构。"""

    field_0: str | None = None  # 记录编号
    field_1: str | None = None  # 运单编号
    field_2: str | None = None  # 装卸类型
    field_3: str | None = None  # 月台编号
    field_4: str | None = None  # 开门时长
    field_5: str | None = None  # 装卸人员
    field_6: str | None = None  # 开始时间
    field_7: str | None = None  # 装卸状态

class AlertEntry(BaseModel):
    """报警记录明细结构。"""

    field_0: str | None = None  # 报警编号
    field_1: str | None = None  # 报警类型
    field_2: str | None = None  # 关联设备
    field_3: str | None = None  # 报警阈值
    field_4: str | None = None  # 触发值
    field_5: str | None = None  # 触发时间
    field_6: str | None = None  # 处置措施
    field_7: str | None = None  # 报警状态

class RouteEntry(BaseModel):
    """运输线路明细结构。"""

    field_0: str | None = None  # 线路编号
    field_1: str | None = None  # 始发地
    field_2: str | None = None  # 到达地
    field_3: str | None = None  # 标准里程
    field_4: str | None = None  # 预估耗时
    field_5: str | None = None  # 途经节点
    field_6: str | None = None  # 路况等级
    field_7: str | None = None  # 线路状态

class ReeferUnitEntry(BaseModel):
    """制冷设备明细结构。"""

    field_0: str | None = None  # 机组编号
    field_1: str | None = None  # 所属车辆
    field_2: str | None = None  # 机组型号
    field_3: str | None = None  # 设定温度
    field_4: str | None = None  # 回风温度
    field_5: str | None = None  # 运转时长
    field_6: str | None = None  # 上次保养日
    field_7: str | None = None  # 机组状态

class FuelEntry(BaseModel):
    """加油记录明细结构。"""

    field_0: str | None = None  # 记录编号
    field_1: str | None = None  # 车辆编号
    field_2: str | None = None  # 油料类型
    field_3: str | None = None  # 加油量
    field_4: str | None = None  # 加油金额
    field_5: str | None = None  # 油站名称
    field_6: str | None = None  # 加油日期
    field_7: str | None = None  # 记录状态

class DeliveryEntry(BaseModel):
    """签收记录明细结构。"""

    field_0: str | None = None  # 签收编号
    field_1: str | None = None  # 运单编号
    field_2: str | None = None  # 签收人
    field_3: str | None = None  # 签收时间
    field_4: str | None = None  # 货物状况
    field_5: str | None = None  # 温度记录
    field_6: str | None = None  # 签收照片
    field_7: str | None = None  # 签收状态

class BreakChainEntry(BaseModel):
    """断链事件明细结构。"""

    field_0: str | None = None  # 事件编号
    field_1: str | None = None  # 运单编号
    field_2: str | None = None  # 断链环节
    field_3: str | None = None  # 超温时长
    field_4: str | None = None  # 超温幅度
    field_5: str | None = None  # 责任判定
    field_6: str | None = None  # 处理结论
    field_7: str | None = None  # 事件状态

class DockEntry(BaseModel):
    """装卸月台明细结构。"""

    field_0: str | None = None  # 月台编号
    field_1: str | None = None  # 月台类型
    field_2: str | None = None  # 温层分区
    field_3: str | None = None  # 占用状态
    field_4: str | None = None  # 滑升门状态
    field_5: str | None = None  # 高度调节板
    field_6: str | None = None  # 月台照明
    field_7: str | None = None  # 月台状态

class PackageEntry(BaseModel):
    """保温包装明细结构。"""

    field_0: str | None = None  # 包装编号
    field_1: str | None = None  # 包装类型
    field_2: str | None = None  # 保温材料
    field_3: str | None = None  # 适用温层
    field_4: str | None = None  # 使用次数
    field_5: str | None = None  # 上次消毒日
    field_6: str | None = None  # 破损情况
    field_7: str | None = None  # 包装状态

class TollEntry(BaseModel):
    """过路记录明细结构。"""

    field_0: str | None = None  # 记录编号
    field_1: str | None = None  # 车辆编号
    field_2: str | None = None  # 收费站名称
    field_3: str | None = None  # 收费金额
    field_4: str | None = None  # 通行方向
    field_5: str | None = None  # 通行日期
    field_6: str | None = None  # 凭证编号
    field_7: str | None = None  # 记录状态

class SanitationEntry(BaseModel):
    """消杀记录明细结构。"""

    field_0: str | None = None  # 消杀编号
    field_1: str | None = None  # 车辆编号
    field_2: str | None = None  # 消杀方式
    field_3: str | None = None  # 消毒剂名称
    field_4: str | None = None  # 消杀区域
    field_5: str | None = None  # 操作人员
    field_6: str | None = None  # 消杀日期
    field_7: str | None = None  # 消杀状态

class ContractEntry(BaseModel):
    """运输合同明细结构。"""

    field_0: str | None = None  # 合同编号
    field_1: str | None = None  # 托运方
    field_2: str | None = None  # 承运方
    field_3: str | None = None  # 合同期限
    field_4: str | None = None  # 温层要求
    field_5: str | None = None  # 违约条款
    field_6: str | None = None  # 结算方式
    field_7: str | None = None  # 合同状态

class InsuranceEntry(BaseModel):
    """保险单明细结构。"""

    field_0: str | None = None  # 保单编号
    field_1: str | None = None  # 运单编号
    field_2: str | None = None  # 投保险种
    field_3: str | None = None  # 保额金额
    field_4: str | None = None  # 保险费率
    field_5: str | None = None  # 起保日期
    field_6: str | None = None  # 止保日期
    field_7: str | None = None  # 保单状态
