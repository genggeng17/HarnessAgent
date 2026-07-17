"""ActionParser 的确定性协议测试。"""

import unittest

from harness_agent.agent.action_parser import (
    ActionParseError,
    ActionParseErrorCode,
    ActionParser,
)
from harness_agent.agent.actions import FinalAction, PlanAction


class ActionParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = ActionParser()

    def test_parses_final_and_assigns_runtime_identity(self) -> None:
        raw = (
            '{"schema_version":1,"type":"final",'
            '"outcome":"success","message":"完成"}'
        )

        first = self.parser.parse(raw)
        second = self.parser.parse(raw)

        self.assertIsInstance(first.action, FinalAction)
        self.assertNotEqual(first.action_id, second.action_id)
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(len(first.digest), 64)

    def test_rejects_markdown_wrapped_json(self) -> None:
        with self.assertRaises(ActionParseError) as raised:
            self.parser.parse(
                '```json\n{"schema_version":1,"type":"final",'
                '"outcome":"success","message":"完成"}\n```'
            )

        self.assertEqual(raised.exception.code, ActionParseErrorCode.INVALID_JSON)

    def test_rejects_duplicate_json_key(self) -> None:
        with self.assertRaises(ActionParseError) as raised:
            self.parser.parse(
                '{"schema_version":1,"type":"final","type":"reflect",'
                '"outcome":"success","message":"完成"}'
            )

        self.assertEqual(raised.exception.code, ActionParseErrorCode.DUPLICATE_KEY)

    def test_rejects_extra_field(self) -> None:
        with self.assertRaises(ActionParseError) as raised:
            self.parser.parse(
                '{"schema_version":1,"type":"final","outcome":"success",'
                '"message":"完成","unexpected":true}'
            )

        self.assertEqual(raised.exception.code, ActionParseErrorCode.SCHEMA_ERROR)

    def test_rejects_duplicate_plan_item_id(self) -> None:
        with self.assertRaises(ActionParseError) as raised:
            self.parser.parse(
                '{"schema_version":1,"type":"plan","items":['
                '{"id":"p1","description":"一"},'
                '{"id":"p1","description":"二"}]}'
            )

        self.assertEqual(raised.exception.code, ActionParseErrorCode.SCHEMA_ERROR)

    def test_parses_valid_plan(self) -> None:
        parsed = self.parser.parse(
            '{"schema_version":1,"type":"plan","items":['
            '{"id":"inspect","description":"检查项目"}]}'
        )

        self.assertIsInstance(parsed.action, PlanAction)
        self.assertEqual(parsed.action.items[0].id, "inspect")


if __name__ == "__main__":
    unittest.main()

