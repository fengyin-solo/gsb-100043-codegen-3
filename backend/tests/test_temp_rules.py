"""多级超温规则引擎单测。"""
from __future__ import annotations

import unittest

from app.services import temp_rules as rules


class RuleEngineTest(unittest.TestCase):
    def judge(self, temp: object, hi: object = 8, lo: object = 0) -> rules.Judgment:
        return rules.evaluate(temp, hi, lo)  # type: ignore[return-value]

    def test_normal_and_warning(self) -> None:
        self.assertEqual(self.judge(4.2).status, rules.NORMAL)
        self.assertEqual(self.judge(6.0).status, rules.NORMAL)  # 距上限恰好 2.0 不预警
        warning = self.judge(7.1)
        self.assertEqual((warning.status, warning.rule_name), (rules.NEAR_LIMIT, "接近上限预警"))
        self.assertEqual(self.judge(0.9).rule_name, "接近下限预警")
        self.assertEqual(self.judge(8.0).status, rules.NORMAL)

    def test_over_temp_levels_and_priority(self) -> None:
        l1 = self.judge(10.6)
        self.assertEqual((l1.rule_name, l1.levels), ("一级超温", 1))
        l2 = self.judge(13.8)
        self.assertEqual((l2.rule_name, l2.levels), ("二级超温", 2))
        self.assertEqual([r.name for r in l2.matched], ["一级超温", "二级超温"])
        l3 = self.judge(17.2)
        self.assertEqual((l3.rule_name, l3.levels), ("三级超温", 3))
        self.assertEqual(l3.rule.priority, 40)
        self.assertEqual(self.judge(-9).rule_name, "三级超温")

    def test_missing_limits_keeps_current_judgment(self) -> None:
        # 上下限缺失/不可解析 -> None，由上层维持当前判定
        self.assertIsNone(rules.evaluate(12, None, 0))
        self.assertIsNone(rules.evaluate(12, 8, ""))
        self.assertIsNone(rules.evaluate(12, "bad", 0))

    def test_missing_temperature(self) -> None:
        self.assertEqual(self.judge(None).status, rules.DATA_MISSING)
        self.assertEqual(self.judge("abc").status, rules.DATA_MISSING)
        self.assertEqual(self.judge("13.8℃").rule_name, "二级超温")


if __name__ == "__main__":
    unittest.main()
