"""
outreach-prospector-mcp: Zero-Cost Waterfall Enrichment, 6-ATS Scanner & Pre-Send Gate MCP Server.
"""

from .server import (
    scrape_clean_markdown,
    waterfall_find_decision_maker,
    discover_executives_from_web,
    scan_live_ats_career_ops,
    classify_resume_track,
    is_target_track_fit,
    is_generic_or_role_alias,
    sanitize_scraped_email,
    clean_company_name,
    extract_safe_first_name,
    verify_headline_company_match,
    validate_outreach_payload,
    handle_rpc_request,
    MCP_TOOLS,
)

__version__ = "1.2.0"
__all__ = [
    "scrape_clean_markdown",
    "waterfall_find_decision_maker",
    "discover_executives_from_web",
    "scan_live_ats_career_ops",
    "classify_resume_track",
    "is_target_track_fit",
    "is_generic_or_role_alias",
    "sanitize_scraped_email",
    "clean_company_name",
    "extract_safe_first_name",
    "verify_headline_company_match",
    "validate_outreach_payload",
    "handle_rpc_request",
    "MCP_TOOLS",
]
