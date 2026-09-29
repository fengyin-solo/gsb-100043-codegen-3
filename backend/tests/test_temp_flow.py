"""温控接入 -> 多级判定 -> 报警待办回写 -> 断点续传 的端到端回归。

运行：PYTHONPATH=. python -m unittest tests.test_temp_flow -v
"""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import app


class TempMonitorFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def _alerts(self) -> list[dict]:
        return self.client.get("/api/alert?size=200").json()["items"]

    def test_full_flow(self) -> None:
        client = self.client

        # 启动引导：看板、明细、报警待办三处一致
        dash = client.get("/api/temp_monitor/dashboard").json()
        self.assertEqual((dash["正常"], dash["接近临界"], dash["超温"]), (1, 1, 3))
        self.assertEqual(dash["待处理超温报警"], 3)
        auto = [a for a in self._alerts() if a.get("来源记录编号")]
        self.assertEqual({a["来源记录编号"] for a in auto},
                         {"TEMP-0003", "TEMP-0004", "TEMP-0005"})

        # 批量接入：三级超温只生成一条报警；上下限缺失维持待判定
        batch = [
            {"seq": 101, "记录编号": "TEMP-I01", "运单编号": "S1", "当前温度": "4", "温度上限": "8", "温度下限": "0", "记录时间": "t", "设备编号": "D"},
            {"seq": 102, "记录编号": "TEMP-I02", "运单编号": "S2", "当前温度": "16.5", "温度上限": "8", "温度下限": "0", "记录时间": "t", "设备编号": "D"},
            {"seq": 103, "记录编号": "TEMP-I03", "运单编号": "S3", "当前温度": "12", "温度上限": "", "温度下限": "", "记录时间": "t", "设备编号": "D"},
        ]
        res = client.post("/api/temp_monitor/ingest", json={"records": batch}).json()
        self.assertTrue(res["ok"])
        self.assertEqual((res["ingested"], res["new_alarms"]), (3, 1))
        missing = client.get("/api/temp_monitor?keyword=TEMP-I03").json()["items"][0]
        self.assertEqual(missing["status"], "数据缺失")
        self.assertIn("上下限缺失", missing["判定依据"])

        # 幂等：整批重发不重复生成报警
        res = client.post("/api/temp_monitor/ingest", json={"records": batch}).json()
        self.assertEqual((res["skipped"], res["new_alarms"]), (3, 0))
        self.assertEqual(len([a for a in self._alerts() if a.get("来源记录编号") == "TEMP-I02"]), 1)

        # 接口中断 -> 从断点继续
        batch2 = [
            {"seq": 201, "记录编号": "TEMP-X01", "当前温度": "9", "温度上限": "8", "温度下限": "0", "记录时间": "t", "设备编号": "D"},
            {"seq": 202, "记录编号": "TEMP-X02", "当前温度": "14", "温度上限": "8", "温度下限": "0", "记录时间": "t", "设备编号": "D"},
            {"seq": 203, "记录编号": "TEMP-X03", "当前温度": "20", "温度上限": "8", "温度下限": "0", "记录时间": "t", "设备编号": "D"},
        ]
        res = client.post("/api/temp_monitor/ingest",
                          json={"records": batch2, "stream": "S2", "fail_after": 2}).json()
        self.assertTrue(res["interrupted"])
        self.assertEqual(res["checkpoint"], 202)
        res = client.post("/api/temp_monitor/ingest", json={"records": batch2, "stream": "S2"}).json()
        self.assertEqual((res["ingested"], res["skipped"], res["new_alarms"]), (1, 2, 1))
        self.assertEqual(len([
            a for a in self._alerts()
            if a.get("来源记录编号") in {"TEMP-X01", "TEMP-X02", "TEMP-X03"}
        ]), 3)

        # 恢复正常自动消除报警；再次超温不复活旧单
        iid = client.get("/api/temp_monitor?keyword=TEMP-I02").json()["items"][0]["id"]
        old_no = client.get("/api/temp_monitor?keyword=TEMP-I02").json()["items"][0]["关联报警"]
        res = client.post(f"/api/temp_monitor/{iid}/actions",
                          json={"values": {"action": "数据补录", "当前温度": "4"}}).json()
        self.assertEqual(res["entry"]["status"], "正常")
        closed = [a for a in self._alerts() if a["报警编号"] == old_no][0]
        self.assertEqual(closed["status"], "已消除")
        res = client.post(f"/api/temp_monitor/{iid}/actions",
                          json={"values": {"action": "数据补录", "当前温度": "11"}}).json()
        self.assertNotEqual(res["entry"]["关联报警"], old_no)
        # 级别升级（持续超温）复用同一报警，不新建
        res = client.post(f"/api/temp_monitor/{iid}/actions",
                          json={"values": {"action": "确认超温", "当前温度": "14"}}).json()
        self.assertEqual(len([a for a in self._alerts() if a.get("来源记录编号") == "TEMP-I02"]), 2)


if __name__ == "__main__":
    unittest.main()
