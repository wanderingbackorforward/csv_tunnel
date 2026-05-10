import unittest

from tbm_diag.domain import load_project_profile, validate_profile
from tbm_diag.domain.audit import claim_levels_supported_by


class DomainConstraintTests(unittest.TestCase):
    def test_builtin_profile_is_valid(self):
        profile = load_project_profile()
        audit = validate_profile(profile)
        self.assertTrue(audit.ok, audit.errors)
        self.assertGreaterEqual(audit.risk_family_count, 5)

    def test_stoppage_is_not_the_center_of_the_ontology(self):
        profile = load_project_profile()
        risk_ids = {risk.risk_id for risk in profile.risk_families}
        self.assertIn("operational_pause", risk_ids)
        self.assertIn("excavation_resistance_tooling", risk_ids)
        self.assertIn("face_stability", risk_ids)
        self.assertGreater(len(risk_ids), 1)

    def test_csv_only_supports_csv_level_claims(self):
        profile = load_project_profile()
        supported = claim_levels_supported_by(profile, {"csv_time_series"})
        self.assertEqual(supported, ["L1_csv_signal"])

    def test_site_log_can_support_confirmed_level(self):
        profile = load_project_profile()
        supported = claim_levels_supported_by(
            profile,
            {"csv_time_series", "project_profile", "site_operation_log"},
        )
        self.assertIn("L4_confirmed_by_site_log", supported)


if __name__ == "__main__":
    unittest.main()
