# `outreach-prospector-mcp` — Zero-Cost Waterfall Enrichment, 6-ATS Scanner & Pre-Send Gate MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776AB.svg)](https://www.python.org/)
[![MCP: Stdio JSON-RPC 2.0](https://img.shields.io/badge/MCP-Stdio%20JSON--RPC%202.0-8A2BE2)](https://modelcontextprotocol.io)
[![andrew4522-cr/outreach-prospector-mcp MCP server](https://glama.ai/mcp/servers/andrew4522-cr/outreach-prospector-mcp/badges/score.svg)](https://glama.ai/mcp/servers/andrew4522-cr/outreach-prospector-mcp)

> **Enterprise B2B & Executive Prospecting without the $500/mo SaaS bloat.** A zero-dependency Model Context Protocol (MCP) server combining clean Markdown web scraping, live 6-ATS job board discovery, 4-stage executive waterfall enrichment, and hard pre-send quality gates.

Built by **Andrew Anderson** ([BridgingTheAIGap.com](https://www.bridgingtheaigap.com)).

---

## Architecture Overview

```mermaid
flowchart TD
    A["MCP Client (Claude Desktop / Cursor / Antigravity)"] -->|JSON-RPC 2.0 Stdio| B["outreach-prospector-mcp"]
    B --> C["1. scrape_clean_markdown"]
    B --> D["2. scan_live_ats_career_ops"]
    B --> E["3. waterfall_find_decision_maker"]
    B --> F["4. validate_outreach_payload"]
    C --> C1["Firecrawl API -> Free Jina Reader -> HTML Fallback"]
    D --> D1["Greenhouse + Ashby + Lever + Workable + SmartRecruiters + Recruitee"]
    E --> E1["Stage 1: Apollo -> Stage 2: Snov -> Stage 3: Web/LinkedIn Exec -> Stage 4: Hunter"]
    F --> F1["Blocks 75+ Generic Aliases, Unreplaced {braces}, & Headline Mismatches"]
```

---

## Key Features

### 1. Clean Markdown Web & ATS Scraper (`scrape_clean_markdown`)
- Renders JS-heavy Next.js/React career pages, company `/about` pages, and ATS postings into clean, LLM-ready Markdown.
- Automatic 3-tier waterfall: **Firecrawl API** (if `FIRECRAWL_API_KEY` set) $\rightarrow$ **100% Free Jina Reader (`r.jina.ai`)** $\rightarrow$ **Direct HTML-to-Markdown fallback**.

### 2. Live 6-ATS Public API Scanner (`scan_live_ats_career_ops`)
- Directly queries the public JSON posting APIs of **6 major Applicant Tracking Systems** with zero paid API keys required:
  - **Greenhouse** (`boards-api.greenhouse.io`)
  - **Ashby** (`api.ashbyhq.com`)
  - **Lever** (`api.lever.co`)
  - **Workable** (`apply.workable.com/api/v3`)
  - **SmartRecruiters** (`api.smartrecruiters.com`)
  - **Recruitee** (`*.recruitee.com/api/offers`)
- Includes live search discovery to find newly posted roles outside static company slug lists and automatically classifies roles into single-angle tracks (`AI`, `MARKETING`, `OPERATIONS`).

### 3. 4-Stage Executive Waterfall Enrichment (`waterfall_find_decision_maker`)
- **Stage 1:** Apollo.io People Search & Match API (`APOLLO_API_KEY`).
- **Stage 2:** Snov.io Domain Prospect Search (`SNOV_CLIENT_ID` / `SNOV_CLIENT_SECRET`), automatically rejecting `invalid` and `not_verified` guesses.
- **Stage 3:** Web & LinkedIn Named Executive Discovery (`discover_executives_from_web`) across `/about`, `/team`, and search indexes, chained into Hunter.io / Snov Name-to-Email resolution.
- **Strict Role Hygiene:** Automatically excludes board chairmen, non-executive directors, podcast hosts, career coaches, legal counsel, and former employees (`ex-`, `former`).

### 4. Hard Pre-Send Quality Gates (`validate_outreach_payload`)
- **75+ Generic Inbox Blocklist:** Blocks `info@`, `careers@`, `talent@`, `support@`, `dataprotection@`, `press@`, `tellmemore@`, and leading HTML unicode escape artifacts (`u003e`).
- **Zero Unreplaced Placeholders:** Blocks any outbound payload containing raw `{first_name}` or `{{company}}` braces.
- **Headline-to-Company Verification:** Verifies extracted company tokens across all headline separators (`at`, `@`, `-`, `–`, `|`) before sending any LinkedIn DM.
- **Approval-Gated LinkedIn Drafting (`prepare_linkedin_outreach_for_approval`):** Stages tailored single-angle `X -> Y -> Z` outreach drafts in `PENDING_APPROVAL` state.

---

## Installation

```bash
pip install git+https://github.com/andrew4522-cr/outreach-prospector-mcp.git
```

Or clone locally:
```bash
git clone https://github.com/andrew4522-cr/outreach-prospector-mcp.git
cd outreach-prospector-mcp
pip install -e .
```

---

## MCP Client Configuration (Claude Desktop / Cursor / Antigravity)

Add to your `mcp_config.json` or `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "outreach_prospector": {
      "command": "outreach-prospector-mcp",
      "env": {
        "APOLLO_API_KEY": "optional_apollo_key",
        "SNOV_CLIENT_ID": "optional_snov_id",
        "SNOV_CLIENT_SECRET": "optional_snov_secret",
        "FIRECRAWL_API_KEY": "optional_firecrawl_key"
      }
    }
  }
}
```

---

## Standalone CLI Usage

```bash
# 1. Scrape any URL into clean Markdown (zero API keys required)
outreach-prospector-mcp --scrape "https://stripe.com/jobs"

# 2. Scan live Greenhouse, Ashby, Lever, Workable, SmartRecruiters & Recruitee boards
outreach-prospector-mcp --scan-ats

# 3. Run 4-stage waterfall decision-maker discovery for a target company
outreach-prospector-mcp --waterfall "ElevenLabs" "elevenlabs.io"
```

---

## Running Tests

```bash
python -m unittest discover -s tests -v
```

---

## License

MIT License © 2026 [Andrew Anderson](https://www.bridgingtheaigap.com)
