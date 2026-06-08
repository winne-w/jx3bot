from __future__ import annotations

import ast
import unittest
from pathlib import Path


class StatusMonitorJobsConfigTests(unittest.TestCase):
    def test_daily_jjc_ranking_allows_two_concurrent_instances(self) -> None:
        source_path = Path(__file__).resolve().parents[1] / "src" / "plugins" / "status_monitor" / "jobs.py"
        module = ast.parse(source_path.read_text(encoding="utf-8"))

        target = None
        for node in module.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "push_daily_jjc_ranking":
                target = node
                break

        self.assertIsNotNone(target)
        decorator = target.decorator_list[0]
        self.assertIsInstance(decorator, ast.Call)

        keywords = {
            keyword.arg: keyword.value
            for keyword in decorator.keywords
            if keyword.arg is not None
        }
        self.assertEqual(ast.literal_eval(keywords["hour"]), "4,21")
        self.assertEqual(ast.literal_eval(keywords["minute"]), 0)
        self.assertEqual(ast.literal_eval(keywords["max_instances"]), 2)


if __name__ == "__main__":
    unittest.main()
