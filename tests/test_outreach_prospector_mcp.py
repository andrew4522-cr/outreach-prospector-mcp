import json
import unittest

from outreach_prospector_mcp import (
    classify_resume_track,
    clean_company_name,
    extract_safe_first_name,
    handle_rpc_request,
    is_generic_or_role_alias,
    is_target_track_fit,
    sanitize_scraped_email,
    validate_outreach_payload,
    verify_headline_company_match,
)


class TestOutreachProspectorMcp(unittest.TestCase):
    def test_generic_inbox_and_escape_sanitization(self):
        self.assertEqual(sanitize_scraped_email("u003esales@stripe.com"), "sales@stripe.com")
        self.assertTrue(is_generic_or_role_alias("u003esales@stripe.com"))
        self.assertTrue(is_generic_or_role_alias("careers@linear.app"))
        self.assertTrue(is_generic_or_role_alias("dataprotection@acme.co.uk"))
        self.assertFalse(is_generic_or_role_alias("patrick@stripe.com"))

    def test_track_classification_and_seniority_filter(self):
        self.assertTrue(is_target_track_fit("Head of AI & Workflow Automation"))
        self.assertTrue(is_target_track_fit("VP of Marketing & Growth"))
        self.assertTrue(is_target_track_fit("Director of Revenue Operations"))
        self.assertFalse(is_target_track_fit("Junior Marketing Intern"))
        self.assertFalse(is_target_track_fit("General Counsel & Legal Director"))
        self.assertFalse(is_target_track_fit("Shop Assistant"))

        self.assertEqual(classify_resume_track("Head of AI Systems"), "AI")
        self.assertEqual(classify_resume_track("VP of Brand & Growth Marketing"), "MARKETING")
        self.assertEqual(classify_resume_track("Head of Commercial Operations"), "OPERATIONS")

    def test_pre_send_quality_gate(self):
        bad = validate_outreach_payload(
            recipient_email="info@acme.com",
            subject="Hello {first_name}",
            body="Check out http://localhost:3000 — great fit",
            contact_name="Marketing Lead",
            headline="VP Marketing at OtherCo",
            company_name="Acme Ltd.",
        )
        self.assertFalse(bad["valid"])
        self.assertGreaterEqual(len(bad["reasons"]), 4)
        self.assertEqual(bad["safe_first_name"], "there")
        self.assertEqual(bad["clean_company"], "Acme")

        good = validate_outreach_payload(
            recipient_email="claire@stripe.com",
            subject="Quick question about Stripe",
            body="Hi Claire, saw how Stripe is scaling global GTM operations.",
            contact_name="Claire Hughes",
            headline="CMO at Stripe",
            company_name="Stripe, Inc.",
        )
        self.assertTrue(good["valid"])
        self.assertEqual(good["safe_first_name"], "Claire")
        self.assertEqual(good["clean_company"], "Stripe")

    def test_json_rpc_mcp_protocol(self):
        init_resp = handle_rpc_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(init_resp["result"]["serverInfo"]["name"], "outreach-prospector-mcp")

        tools_resp = handle_rpc_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tool_names = {t["name"] for t in tools_resp["result"]["tools"]}
        self.assertIn("scrape_clean_markdown", tool_names)
        self.assertIn("waterfall_find_decision_maker", tool_names)
        self.assertIn("scan_live_ats_career_ops", tool_names)
        self.assertIn("validate_outreach_payload", tool_names)


if __name__ == "__main__":
    unittest.main()
