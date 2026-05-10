import tempfile
import unittest
from pathlib import Path

from tbm_diag.config import load_config
from tbm_diag.react_env.runner import run_react_environment


class ReactEnvironmentTests(unittest.TestCase):
    def test_rule_environment_reaches_verifier_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.csv"
            lines = [
                "日期时间,刀盘转矩(kNm),推进速度平均值(mm/min),贯入度(mm/r),总推进力(KN)",
            ]
            for i in range(12):
                lines.append(f"2026-01-01 00:00:{i:02d},4000,10,2,1200")
            path.write_text("\n".join(lines), encoding="utf-8-sig")

            result = run_react_environment(path, load_config(None), max_steps=8)
            state = result.state

            self.assertEqual(result.error, "")
            self.assertTrue(state.finalized)
            self.assertEqual(
                [item.action for item in state.trace],
                [
                    "inspect_schema",
                    "run_detection",
                    "map_risk_families",
                    "check_claim_level",
                    "identify_evidence_gaps",
                    "finalize",
                ],
            )
            self.assertGreaterEqual(state.event_count, 1)
            self.assertIn("L1_csv_signal", state.supported_claim_levels)
            self.assertIn("L2_project_risk_candidate", state.supported_claim_levels)
            self.assertNotIn("L4_confirmed_by_site_log", state.supported_claim_levels)
            self.assertIn(
                "excavation_resistance_tooling",
                {item["risk_id"] for item in state.risk_candidates},
            )
            self.assertTrue(state.verifier_blockers)


if __name__ == "__main__":
    unittest.main()
