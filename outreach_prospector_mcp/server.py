#!/usr/bin/env python3
"""
========================================================================================
OUTREACH PROSPECTOR MCP SERVER (Stdio JSON-RPC 2.0 + CLI)
Author: Andrew Anderson (BridgingTheAIGap.com)
License: MIT
========================================================================================
Zero-dependency Model Context Protocol (MCP) server combining:
1. Clean Markdown Web & ATS Scraper (`scrape_clean_markdown`):
   - Firecrawl API -> 100% Free Jina Reader (`https://r.jina.ai/{url}`) -> HTML fallback.
2. Live 6-ATS Public API Scanner (`scan_live_ats_career_ops`):
   - Scans Greenhouse, Ashby, Lever, Workable, SmartRecruiters, and Recruitee public
     endpoints + live DuckDuckGo ATS board discovery across Operations, Marketing, and AI.
3. 4-Stage Executive Waterfall Enrichment (`waterfall_find_decision_maker`):
   - Stage 1: Apollo.io People Search & Match API
   - Stage 2: Snov.io Domain Prospect Search
   - Stage 3: Web/LinkedIn Named Executive Discovery -> Name-to-Email Resolution
   - Stage 4: Hunter.io / Website Direct Contact Fallback
4. Hard Pre-Send Quality Gates (`validate_outreach_payload`):
   - Blocks 75+ generic/shared role aliases (`info@`, `careers@`, `dataprotection@`, etc.)
   - Blocks board chairmen, advisors, podcast hosts, and former employees (`ex-`, `former`)
   - Verifies headline-to-company token alignment across all separators (`at`, `@`, `-`, `|`)
   - Approval-gated LinkedIn outreach drafting (`prepare_linkedin_outreach_for_approval`)
========================================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

GENERIC_EMAIL_PREFIXES: Set[str] = {
    "jobs", "careers", "talent", "recruiting", "recruitment", "hr", "people",
    "apply", "work", "cv", "resumes", "applicant", "noreply", "no-reply",
    "donotreply", "bounce", "mailer-daemon", "privacy", "legal", "security",
    "abuse", "billing", "invoices", "compliance", "unsubscribe", "info",
    "information", "media", "press", "pr", "enquiries", "inquiries", "enquiry",
    "inquiry", "hello", "hi", "contact", "contactus", "support", "help",
    "helpdesk", "customercare", "customerservice", "service", "office", "admin",
    "administration", "team", "sales", "marketing", "reservations", "booking",
    "bookings", "general", "reception", "mail", "email", "accounts", "finance",
    "orders", "events", "partnerships", "complaints", "complaint",
    "dataprotection", "dpo", "gdpr", "tellmemore", "feedback", "governance",
    "ethics", "whistleblowing", "pressoffice", "communications", "comms",
    "investor", "investors", "procurement", "tenders", "facilities", "property",
    "estates", "membership", "donations", "fundraising", "boxoffice", "tickets",
    "safeguarding", "webmaster", "postmaster", "hostmaster", "registrar",
}

GENERIC_STEMS = (
    "enquir", "inquir", "info", "media", "press", "support", "customer",
    "career", "reserv", "hello", "contact", "complaint", "dataprotect",
    "privacy", "gdpr", "tellme", "feedback", "safeguard", "fundrais",
    "donat", "member", "ticket", "boxoffice", "procure", "tender",
    "jobs", "recrui", "talent", "recept", "booking", "orders", "office",
)

BLOCKED_SALUTATION_NAMES: Set[str] = {
    "team", "hiring", "talent", "hr", "recruiting", "recruitment",
    "operations", "marketing", "admin", "sales", "commercial", "lead",
    "info", "hello", "support", "office", "media", "press", "enquiries",
    "inquiries", "contact", "director", "manager", "partner", "there",
    "unknown", "general", "reception", "department", "dept", "division",
}


def load_env_vars() -> Dict[str, str]:
    """Load environment variables from os.environ and local .env if present."""
    env: Dict[str, str] = dict(os.environ)
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            pass
    return env


def sanitize_scraped_email(email: str) -> str:
    """Strip leading HTML unicode escapes (u003e, u003c, %20) and punctuation from scraped emails."""
    if not email:
        return ""
    clean = email.strip().lower()
    clean = re.sub(r"^(?:\\?u00[0-9a-f]{2}|%[0-9a-f]{2}|&#x?[0-9a-f]+;)+", "", clean, flags=re.I)
    return clean.lstrip("<>\"' \t\r\n;:,")


def is_generic_or_role_alias(email: str, learned_prefixes_path: Optional[str] = None) -> bool:
    """Returns True if the email is a generic or departmental alias (`info@`, `careers@`, `dataprotection@`)."""
    clean_email = sanitize_scraped_email(email)
    if not clean_email or "@" not in clean_email:
        return True
    prefix = clean_email.split("@")[0]
    prefix_clean = re.sub(r"[^a-z]", "", prefix)

    learned: Set[str] = set()
    lpath = Path(learned_prefixes_path) if learned_prefixes_path else (Path.cwd() / "learned_generic_prefixes.json")
    if lpath.exists():
        try:
            data = json.loads(lpath.read_text(encoding="utf-8"))
            if isinstance(data, list):
                learned = {str(x).strip().lower() for x in data if x}
            elif isinstance(data, dict):
                learned = {str(x).strip().lower() for x in data.get("prefixes", []) if x}
        except Exception:
            pass

    all_prefixes = GENERIC_EMAIL_PREFIXES | learned
    if prefix in all_prefixes or prefix_clean in all_prefixes:
        return True
    for stem in GENERIC_STEMS:
        if prefix_clean.startswith(stem) or prefix_clean.endswith(stem):
            return True
    return False


def clean_company_name(company_name: str) -> str:
    """
    Normalize a company name without mangling mid-name words:
    - Strips surrounding quotes, job-board badges ('NEW', 'URGENT'), pipe descriptors, and trailing legal suffixes ('Ltd', 'Inc', 'GmbH').
    """
    if not company_name:
        return "your team"
    s = str(company_name).replace("\xa0", " ").strip()
    s = re.sub(r'^["\'“”‘’]+|["\'“”‘’]+$', "", s).strip()
    s = s.replace("—", "-").replace("–", "-")
    if "|" in s:
        s = s.split("|")[0].strip()
    s = re.sub(r"\s+\b(?:NEW|HIRING|URGENT|FEATURED)\b\s*$", "", s).strip()
    for _ in range(2):
        s = re.sub(
            r"[\s,]+(?:Ltd|Limited|PLC|Inc|LLC|LLP|DAC|Corp|Corporation|GmbH|Co)\.?$",
            "",
            s,
            flags=re.IGNORECASE,
        ).strip()
    s = re.sub(r"\s{2,}", " ", s).strip(" ,;-|&")
    return s or company_name.strip()


def extract_safe_first_name(contact_name: str, default: str = "Team") -> str:
    """Extract a verified human first name while blocking role words ('Operations Lead', 'Marketing Team')."""
    if not contact_name:
        return default
    parts = [p.strip(".,;:!()[]\"'") for p in str(contact_name).strip().split() if p.strip(".,;:!()[]\"'")]
    if not parts:
        return default
    if parts[0].lower().rstrip(".") in ("mr", "mrs", "ms", "miss", "dr", "prof") and len(parts) > 1:
        parts = parts[1:]
    first = parts[0]
    if (
        first.lower() not in BLOCKED_SALUTATION_NAMES
        and (len(parts) == 1 or parts[1].lower() not in BLOCKED_SALUTATION_NAMES)
        and re.match(r"^[A-Za-z][A-Za-z'\-]*$", first)
        and not (first.isupper() and len(first) <= 4)
        and 2 <= len(first) <= 20
    ):
        return first.capitalize()
    return default


def verify_headline_company_match(headline: str, company_name: str) -> bool:
    """Verify extracted company tokens across all headline separators (`at`, `@`, `-`, `–`, `|`)."""
    if not headline or not company_name:
        return False
    norm_co = clean_company_name(company_name).lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", norm_co) if len(t) >= 2]
    if not tokens:
        return False
    hl_low = headline.lower()
    return all(tok in hl_low for tok in tokens)


def validate_outreach_payload(
    recipient_email: str,
    subject: str,
    body: str,
    contact_name: str = "",
    headline: str = "",
    company_name: str = "",
) -> Dict[str, Any]:
    """
    Hard Pre-Send Quality Gate for B2B and Executive Outreach.
    Checks for generic aliases, unreplaced `{...}` placeholders, localhost URLs, em-dashes,
    and headline-to-company mismatches.
    """
    reasons: List[str] = []
    if recipient_email and is_generic_or_role_alias(recipient_email):
        reasons.append(f"Rejected generic/shared inbox alias: {recipient_email}")

    combined = f"{subject or ''}\n{body or ''}"
    placeholders = re.findall(r"\{[a-zA-Z0-9_.\-\s]+\}", combined)
    if placeholders:
        reasons.append(f"Rejected unreplaced template placeholders: {', '.join(placeholders)}")

    if "127.0.0.1" in combined or "localhost" in combined.lower():
        reasons.append("Rejected localhost/127.0.0.1 link in external message")

    if "—" in combined or "–" in combined:
        reasons.append("Contains prohibited em/en dash")

    if headline and company_name and not verify_headline_company_match(headline, company_name):
        reasons.append(f"Headline '{headline}' does not match target company '{company_name}'")

    return {
        "valid": len(reasons) == 0,
        "reasons": reasons,
        "safe_first_name": extract_safe_first_name(contact_name, default="there"),
        "clean_company": clean_company_name(company_name),
    }


def scrape_clean_markdown(url: str, max_chars: int = 8000) -> str:
    """
    Firecrawl / Jina Reader Clean Markdown Web Scraper.
    1. Uses Firecrawl API if FIRECRAWL_API_KEY is configured.
    2. Uses 100% Free Jina Reader API (https://r.jina.ai/{url}) to render JS-heavy pages into clean LLM-ready Markdown.
    3. Falls back to direct HTML-to-text extraction if offline.
    """
    if not url.startswith("http"):
        url = f"https://{url}"

    env = load_env_vars()
    firecrawl_key = env.get("FIRECRAWL_API_KEY", "")

    if firecrawl_key:
        try:
            payload = json.dumps({"url": url, "formats": ["markdown"], "onlyMainContent": True}).encode("utf-8")
            req = urllib.request.Request(
                "https://api.firecrawl.dev/v1/scrape",
                data=payload,
                headers={
                    "Authorization": f"Bearer {firecrawl_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                md = data.get("data", {}).get("markdown", "")
                if md and len(md.strip()) > 80:
                    return md.strip()[:max_chars]
        except Exception:
            pass

    try:
        jina_url = f"https://r.jina.ai/{url}"
        req = urllib.request.Request(
            jina_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "text/plain",
                "X-Return-Format": "markdown",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            md = resp.read().decode("utf-8", errors="ignore").strip()
            if md and len(md) > 80 and "403 Forbidden" not in md[:200]:
                return md[:max_chars]
    except Exception:
        pass

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            html = re.sub(r"<(script|style|noscript|svg|footer|nav)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:max_chars]
    except Exception:
        return ""


def discover_executives_from_web(company_name: str, domain: str, role_category: str = "executive") -> List[Dict[str, str]]:
    """
    Uses clean Markdown scraping on company /about, /team, and DuckDuckGo LinkedIn indexing
    to find real named executives (CEO, Founder, CMO, COO, VP Marketing, Talent Lead).
    Strictly blocks Board Chairmen, Podcast Hosts, Career Coaches, Advisors, and Former employees.
    """
    candidates: List[Dict[str, str]] = []
    seen_names: Set[str] = set()

    role_pattern = r"(?:CEO|Chief Executive Officer|Founder|Co-Founder|Managing Director|President|CMO|Chief Marketing Officer|COO|Chief Operating Officer|VP of Marketing|Head of Marketing|Head of Growth|Head of Operations|Head of Talent|VP People)"

    try:
        search_terms = (
            f'site:linkedin.com/in/ "{company_name}" '
            f'("CEO" OR "Founder" OR "CMO" OR "COO" OR "Managing Director" OR "Head of Marketing" OR "VP")'
        )
        ddg_url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(search_terms)
        req = urllib.request.Request(
            ddg_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            titles = re.findall(r'<a[^>]*class="result__a"[^>]*>(.*?)</a>', html, flags=re.DOTALL)
            for t in titles[:8]:
                clean_t = re.sub(r"<[^>]+>", "", t).strip()
                parts = [p.strip() for p in re.split(r"[-–|]", clean_t) if p.strip()]
                if len(parts) >= 2:
                    full_name = parts[0]
                    role_title = parts[1]
                    if any(bad in clean_t.lower() for bad in ["chairman", "board member", "non-executive", "podcast", "career coach", "former ", "ex-"]):
                        continue
                    if company_name.lower() not in clean_t.lower():
                        continue
                    name_words = full_name.split()
                    if (
                        len(name_words) == 2
                        and all(w.isalpha() for w in name_words)
                        and full_name.lower() not in seen_names
                    ):
                        seen_names.add(full_name.lower())
                        candidates.append({
                            "first_name": name_words[0],
                            "last_name": name_words[1],
                            "name": full_name,
                            "role": role_title,
                            "source": "linkedin_web_index",
                        })
    except Exception:
        pass

    if domain and len(candidates) < 2:
        for path in ["/about", "/about-us", "/team", ""]:
            md = scrape_clean_markdown(f"https://{domain}{path}", max_chars=5000)
            if not md:
                continue
            matches = re.findall(
                r"\b([A-Z][a-z]{2,15}\s+[A-Z][a-z]{2,18})\s*(?:[,-–|]|\s+is\s+(?:our|the))\s*(" + role_pattern + r")",
                md,
            )
            for full_name, role_title in matches:
                words = full_name.split()
                if len(words) == 2 and full_name.lower() not in seen_names:
                    if words[0].lower() not in {"read", "learn", "meet", "our", "the", "view", "join", "contact"}:
                        seen_names.add(full_name.lower())
                        candidates.append({
                            "first_name": words[0],
                            "last_name": words[1],
                            "name": full_name,
                            "role": role_title,
                            "source": f"https://{domain}{path}",
                        })
            if candidates:
                break

    return candidates


def _snov_get_token(client_id: str, client_secret: str) -> Optional[str]:
    try:
        payload = json.dumps({
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.snov.io/v1/oauth/access_token",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return data.get("access_token")
    except Exception:
        return None


def waterfall_find_decision_maker(
    company_name: str,
    domain: str,
    job_category: str = "executive",
) -> List[Dict[str, Any]]:
    """
    OpenProspector 4-Stage Waterfall Enrichment:
    Stage 1: Apollo.io People Search & Match API (if APOLLO_API_KEY set)
    Stage 2: Snov.io Domain Prospect Search (if SNOV_CLIENT_ID & SNOV_CLIENT_SECRET set)
    Stage 3: Web/LinkedIn Named Executive Discovery -> Hunter.io / Snov Name-to-Email Resolver
    Stage 4: Direct Website Contact Scraping Fallback (strictly rejecting generic aliases)
    """
    env = load_env_vars()
    apollo_key = env.get("APOLLO_API_KEY", "")
    snov_id = env.get("SNOV_CLIENT_ID") or env.get("SNOV_API_USER_ID", "")
    snov_secret = env.get("SNOV_CLIENT_SECRET") or env.get("SNOV_API_SECRET", "")
    hunter_key = env.get("HUNTER_API_KEY", "")
    results: List[Dict[str, Any]] = []

    # --- STAGE 1: Apollo.io API ---
    if apollo_key and domain:
        try:
            payload = json.dumps({
                "q_organization_domains": domain,
                "person_titles": [
                    "CEO", "Founder", "Co-Founder", "Managing Director",
                    "CMO", "Chief Marketing Officer", "VP Marketing", "Head of Marketing",
                    "COO", "Chief Operating Officer", "VP Operations", "Head of Talent",
                ],
                "page": 1,
                "per_page": 5,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.apollo.io/v1/mixed_people/search",
                data=payload,
                headers={
                    "X-Api-Key": apollo_key,
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                people = data.get("people", []) or data.get("contacts", [])
                for p in people:
                    email = sanitize_scraped_email(p.get("email", ""))
                    if email and "@" in email and "email_not_unlocked" not in email and not is_generic_or_role_alias(email):
                        results.append({
                            "name": f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
                            "email": email,
                            "role": p.get("title", "Executive"),
                            "linkedin_url": p.get("linkedin_url", ""),
                            "source": "apollo_waterfall_stage1",
                            "verified": True,
                        })
                        return results
        except Exception:
            pass

    # --- STAGE 2: Snov.io Domain Prospect Search ---
    token = _snov_get_token(snov_id, snov_secret) if (snov_id and snov_secret and domain) else None
    if token and domain:
        try:
            url = f"https://api.snov.io/v2/domain-emails-with-info?domain={urllib.parse.quote(domain)}&type=all&limit=20"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                for p in data.get("emails", []) or data.get("data", []):
                    email = sanitize_scraped_email(p.get("email", ""))
                    pos_low = (p.get("position") or "").lower()
                    status_low = (p.get("status") or "").lower()
                    if status_low in ("invalid", "not_verified"):
                        continue
                    if any(bad in pos_low for bad in ["chairman", "board", "podcast", "career coach", "counsel", "lawyer", "intern"]):
                        continue
                    if email and not is_generic_or_role_alias(email):
                        results.append({
                            "name": f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
                            "email": email,
                            "role": p.get("position", "Executive"),
                            "linkedin_url": p.get("sourcePage", ""),
                            "source": "snov_waterfall_stage2",
                            "verified": True,
                        })
                        return results
        except Exception:
            pass

    # --- STAGE 3: Web/LinkedIn Named Executive Discovery + Hunter.io Resolver ---
    web_execs = discover_executives_from_web(company_name, domain, role_category=job_category)
    if hunter_key and domain and web_execs:
        for exec_cand in web_execs[:2]:
            try:
                h_url = (
                    f"https://api.hunter.io/v2/email-finder?domain={urllib.parse.quote(domain)}"
                    f"&first_name={urllib.parse.quote(exec_cand['first_name'])}"
                    f"&last_name={urllib.parse.quote(exec_cand['last_name'])}"
                    f"&api_key={urllib.parse.quote(hunter_key)}"
                )
                req = urllib.request.Request(h_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    h_data = json.loads(resp.read().decode("utf-8", errors="ignore")).get("data", {})
                    email = sanitize_scraped_email(h_data.get("email", ""))
                    if email and not is_generic_or_role_alias(email):
                        results.append({
                            "name": exec_cand["name"],
                            "email": email,
                            "role": exec_cand["role"],
                            "linkedin_url": exec_cand.get("source", ""),
                            "source": "web_exec_hunter_stage3",
                            "verified": True,
                        })
                        return results
            except Exception:
                continue

    # Return discovered named executives even if email API keys aren't configured
    for exec_cand in web_execs[:3]:
        results.append({
            "name": exec_cand["name"],
            "email": "",
            "role": exec_cand["role"],
            "linkedin_url": exec_cand.get("source", ""),
            "source": "web_exec_discovery_stage3",
            "verified": False,
        })

    return results


def classify_resume_track(title: str, description: str = "") -> str:
    """Classifies a role into one of 3 single-angle tracks: 'AI', 'MARKETING', or 'OPERATIONS'."""
    t = (title or "").lower()
    d = (description or "").lower()[:1000]

    ai_title_kws = [
        "ai", "artificial intelligence", "agent", "agentic", "llm", "genai",
        "automation", "workflow", "machine learning", "ml ",
    ]
    mkt_title_kws = [
        "marketing", "cmo", "brand", "growth", "demand", "content", "creator",
        "community", "communications", "social", "gtm", "go-to-market", "performance",
    ]
    ops_title_kws = [
        "operations", "operational", "coo", "commercial", "revops", "revenue operations",
        "bizops", "business operations", "general manager", "managing director",
        "delivery", "strategy", "alliances", "partnerships", "transformation", "chief of staff",
    ]

    if any(k in t for k in ai_title_kws):
        return "AI"
    if any(k in t for k in mkt_title_kws):
        return "MARKETING"
    if any(k in t for k in ops_title_kws):
        return "OPERATIONS"

    ai_score = sum(1 for k in ai_title_kws if k in d)
    mkt_score = sum(1 for k in mkt_title_kws if k in d)
    ops_score = sum(1 for k in ops_title_kws if k in d)
    if ai_score >= mkt_score and ai_score > ops_score:
        return "AI"
    if mkt_score > ops_score:
        return "MARKETING"
    return "OPERATIONS"


def is_target_track_fit(title: str) -> bool:
    """
    Strict filter capturing senior roles across OPERATIONS, MARKETING, and AI
    (Head of, VP, Director, Chief, Lead, Architect, GM, Managing Director),
    while blocking legal/counsel, clinical, retail, hospitality, or junior roles.
    """
    t = (title or "").lower().strip()
    if not t:
        return False

    negative_disqualifiers = [
        "intern", "internship", "junior", "graduate", "trainee", "apprentice",
        "contractor", "freelance", "temp ", "temporary",
        "sdr", "bdr", "sales development representative", "business development representative",
        "account executive", "customer support", "technical support", "helpdesk",
        "software engineer", "frontend", "front-end", "backend", "back-end", "full stack",
        "fullstack", "ios ", "android ", "devops", "site reliability", "sre",
        "cloud architect", "network architect", "security architect", "data architect",
        "hardware", "mechanical", "electrical", "civil engineer", "research scientist",
        "graphic designer", "ui designer", "ux designer", "product designer", "motion designer",
        "art director", "copywriter", "recruiter", "talent acquisition",
        "counsel", "legal", "privacy", "compliance", "attorney", "lawyer", "paralegal",
        "solicitor", "accountant", "tax ", "payroll", "auditor", "controller",
        "nurse", "clinical", "physician", "pharmacist", "chef", "carer", "driver",
        "pitch runner", "shop assistant",
    ]
    if any(neg in t for neg in negative_disqualifiers):
        return False

    seniority_qualifiers = [
        "head of", "vp ", "vp,", "vice president", "director", "chief ", "cmo", "coo", "cro", "cdo",
        "general manager", "managing director", "chief of staff", "architect", "principal", "lead",
    ]
    if not any(sq in t for sq in seniority_qualifiers):
        return False

    positive_track_keywords = [
        "operations", "operational", "coo", "chief operating", "commercial",
        "revops", "revenue operations", "bizops", "business operations",
        "general manager", "managing director", "chief of staff", "strategy and operations",
        "strategy & operations", "transformation",
        "marketing", "cmo", "chief marketing", "growth", "brand", "demand generation",
        "performance marketing", "product marketing", "communications", "gtm", "go-to-market",
        "ai ", " ai", "artificial intelligence", "agentic", "ai agent", "ai systems",
        "ai architect", "ai solutions", "ai workflow", "ai automation", "ai operations",
        "ai transformation", "ai strategy", "applied ai", "genai",
    ]
    return any(pos in t for pos in positive_track_keywords)


def discover_live_ats_via_search(max_results: int = 20) -> List[Dict[str, Any]]:
    """
    Live ATS Search Discovery across Greenhouse, Ashby, Lever, Workable, SmartRecruiters, and Recruitee.
    """
    discovered: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()

    search_queries = [
        'site:apply.workable.com ("Head of Operations" OR "Head of Marketing" OR "Head of Growth" OR "AI")',
        'site:boards.greenhouse.io ("Head of Operations" OR "Head of Marketing" OR "Head of Growth" OR "AI Architect" OR "Head of AI")',
        'site:jobs.ashbyhq.com ("Operations" OR "Marketing" OR "Growth" OR "AI")',
        'site:jobs.smartrecruiters.com ("Head of Operations" OR "Head of Marketing" OR "VP Marketing" OR "AI")',
        'site:recruitee.com ("Head of Operations" OR "Head of Marketing" OR "Head of Growth" OR "AI")',
    ]

    for q in search_queries:
        if len(discovered) >= max_results:
            break
        try:
            ddg_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(q)}"
            req = urllib.request.Request(
                ddg_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                blocks = re.findall(
                    r'<a rel="nofollow" class="result__a" href="([^"]+)">(.*?)</a>.*?<a class="result__snippet"[^>]*>(.*?)</a>',
                    html,
                    flags=re.DOTALL,
                )
                for raw_href, raw_title, raw_snippet in blocks:
                    url = raw_href
                    if "uddg=" in url:
                        m = re.search(r"uddg=([^&]+)", url)
                        if m:
                            url = urllib.parse.unquote(m.group(1))
                    if not url.startswith("http") or url in seen_urls:
                        continue

                    clean_t = re.sub(r"<[^>]+>", "", raw_title).strip()
                    clean_s = re.sub(r"<[^>]+>", "", raw_snippet).strip()

                    parts = [p.strip() for p in re.split(r"\s+[-|–—@]\s+|\s+at\s+", clean_t) if p.strip()]
                    role_title = parts[0] if parts else clean_t
                    company = parts[1] if len(parts) > 1 else ""

                    if not company:
                        u_match = re.search(r"(?:greenhouse\.io|ashbyhq\.com|lever\.co|workable\.com|smartrecruiters\.com)/([^/?#]+)", url)
                        if u_match:
                            company = u_match.group(1).replace("-", " ").title()
                        else:
                            rc_match = re.search(r"https?://([^.]+)\.recruitee\.com", url)
                            if rc_match:
                                company = rc_match.group(1).replace("-", " ").title()

                    if not is_target_track_fit(role_title):
                        continue

                    seen_urls.add(url)
                    ats_name = "ats_search_discovery"
                    for k in ["greenhouse", "ashby", "lever", "workable", "smartrecruiters", "recruitee"]:
                        if k in url.lower():
                            ats_name = f"{k}_live_search"
                            break

                    track = classify_resume_track(role_title, clean_s)
                    discovered.append({
                        "ats": ats_name,
                        "company": company or "Target Company",
                        "title": role_title,
                        "resume_version": track,
                        "location": "Remote / Europe",
                        "url": url,
                        "updated_at": "",
                        "description": clean_s,
                    })
                    if len(discovered) >= max_results:
                        break
        except Exception:
            continue

    return discovered


def scan_live_ats_career_ops(
    greenhouse_boards: Optional[List[str]] = None,
    ashby_boards: Optional[List[str]] = None,
    lever_boards: Optional[List[str]] = None,
    workable_boards: Optional[List[str]] = None,
    smartrecruiters_boards: Optional[List[str]] = None,
    recruitee_boards: Optional[List[str]] = None,
    include_live_search: bool = True,
) -> List[Dict[str, Any]]:
    """
    Multi-ATS Live Scanner across Greenhouse, Ashby, Lever, Workable, SmartRecruiters, Recruitee,
    plus live DuckDuckGo ATS search discovery.
    """
    gh_list = greenhouse_boards or [
        "stripe", "cloudflare", "datadog", "scaleai", "mistral", "anthropic",
        "cohere", "vercel", "linear", "retool", "figma", "notion", "airtable",
        "vanta", "drata", "glean", "weaviate", "elevenlabs", "runwayml", "monzo",
        "intercom", "synthesia", "contentful", "remote", "mollie",
    ]
    ashby_list = ashby_boards or [
        "linear", "ramp", "deel", "posthog", "supabase", "langchain", "perplexity",
        "lovables", "n8n", "retellai", "replit",
    ]
    lever_list = lever_boards or [
        "spotify", "mistral", "palantir", "talkdesk", "swordhealth", "feedzai",
    ]
    workable_list = workable_boards or [
        "coverflex", "indie-campers", "ydata", "infraspeak", "barkyn",
        "casafari", "kencko", "sensei", "codacy", "unbabel",
    ]
    smartrecruiters_list = smartrecruiters_boards or [
        "wise", "revolut", "bosch", "visa", "celonis", "servicenow",
    ]
    recruitee_list = recruitee_boards or [
        "hotjar", "tines", "personio", "factorial", "spendesk",
    ]

    matched_jobs: List[Dict[str, Any]] = []

    for slug in gh_list[:15]:
        slug = slug.strip().lower()
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                for job in data.get("jobs", []):
                    title = job.get("title", "")
                    if is_target_track_fit(title):
                        loc = job.get("location", {}).get("name", "Remote")
                        desc = re.sub(r"<[^>]+>", " ", job.get("content", ""))[:3000]
                        matched_jobs.append({
                            "ats": "greenhouse",
                            "company": slug.capitalize(),
                            "title": title,
                            "resume_version": classify_resume_track(title, desc),
                            "location": loc,
                            "url": job.get("absolute_url", ""),
                            "updated_at": job.get("updated_at", ""),
                            "description": desc,
                        })
        except Exception:
            continue

    for slug in ashby_list[:10]:
        slug = slug.strip().lower()
        url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                for job in data.get("jobs", []):
                    title = job.get("title", "")
                    if is_target_track_fit(title):
                        desc = job.get("descriptionPlain", "")[:3000]
                        matched_jobs.append({
                            "ats": "ashby",
                            "company": slug.capitalize(),
                            "title": title,
                            "resume_version": classify_resume_track(title, desc),
                            "location": job.get("location", "Remote"),
                            "url": job.get("jobUrl", ""),
                            "updated_at": job.get("publishedAt", ""),
                            "description": desc,
                        })
        except Exception:
            continue

    for slug in lever_list[:8]:
        slug = slug.strip().lower()
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if isinstance(data, list):
                    for job in data:
                        title = job.get("text", "")
                        if is_target_track_fit(title):
                            desc = job.get("descriptionPlain", "")[:3000]
                            matched_jobs.append({
                                "ats": "lever",
                                "company": slug.capitalize(),
                                "title": title,
                                "resume_version": classify_resume_track(title, desc),
                                "location": job.get("categories", {}).get("location", "Remote"),
                                "url": job.get("hostedUrl", ""),
                                "updated_at": str(job.get("createdAt", "")),
                                "description": desc,
                            })
        except Exception:
            continue

    for slug in workable_list[:10]:
        slug = slug.strip().lower()
        url_v3 = f"https://apply.workable.com/api/v3/accounts/{slug}/jobs"
        try:
            payload = json.dumps({"query": "", "location": [], "department": [], "worktype": [], "remote": []}).encode("utf-8")
            req = urllib.request.Request(
                url_v3,
                data=payload,
                headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                for job in data.get("results", []):
                    title = job.get("title", "")
                    if is_target_track_fit(title):
                        shortcode = job.get("shortcode", "")
                        loc_obj = job.get("location", {}) or {}
                        loc_str = loc_obj.get("city") or loc_obj.get("country") or "Remote"
                        job_url = f"https://apply.workable.com/{slug}/j/{shortcode}/" if shortcode else f"https://apply.workable.com/{slug}/"
                        matched_jobs.append({
                            "ats": "workable",
                            "company": slug.replace("-", " ").title(),
                            "title": title,
                            "resume_version": classify_resume_track(title, ""),
                            "location": loc_str,
                            "url": job_url,
                            "updated_at": job.get("published", ""),
                            "description": f"{title} at {slug.replace('-', ' ').title()} ({loc_str})",
                        })
        except Exception:
            continue

    for slug in smartrecruiters_list[:8]:
        slug = slug.strip()
        url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                for job in data.get("content", []):
                    title = job.get("name", "")
                    if is_target_track_fit(title):
                        loc_obj = job.get("location", {}) or {}
                        loc_str = loc_obj.get("city") or loc_obj.get("country") or "Remote"
                        job_id = job.get("id", "")
                        comp_name = (job.get("company", {}) or {}).get("name") or slug.capitalize()
                        job_url = f"https://jobs.smartrecruiters.com/{slug}/{job_id}" if job_id else f"https://jobs.smartrecruiters.com/{slug}"
                        matched_jobs.append({
                            "ats": "smartrecruiters",
                            "company": comp_name,
                            "title": title,
                            "resume_version": classify_resume_track(title, ""),
                            "location": loc_str,
                            "url": job_url,
                            "updated_at": job.get("releasedDate", ""),
                            "description": f"{title} at {comp_name} ({loc_str})",
                        })
        except Exception:
            continue

    for slug in recruitee_list[:8]:
        slug = slug.strip().lower()
        url = f"https://{slug}.recruitee.com/api/offers/"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                for job in data.get("offers", []):
                    title = job.get("title", "")
                    if is_target_track_fit(title):
                        desc = re.sub(r"<[^>]+>", " ", job.get("description", ""))[:3000]
                        matched_jobs.append({
                            "ats": "recruitee",
                            "company": slug.capitalize(),
                            "title": title,
                            "resume_version": classify_resume_track(title, desc),
                            "location": job.get("location", "Remote"),
                            "url": job.get("careers_url", f"https://{slug}.recruitee.com/"),
                            "updated_at": job.get("published_at", ""),
                            "description": desc,
                        })
        except Exception:
            continue

    if include_live_search:
        search_jobs = discover_live_ats_via_search(max_results=15)
        seen_urls = {j.get("url") for j in matched_jobs if j.get("url")}
        for sj in search_jobs:
            if sj.get("url") not in seen_urls:
                matched_jobs.append(sj)
                seen_urls.add(sj.get("url"))

    return matched_jobs


def draft_general_linkedin_outreach(
    contact_name: str,
    contact_role: str,
    company_name: str,
    target_role: str,
    resume_version: str = "OPERATIONS",
    sender_name: str = "Andrew Anderson",
) -> str:
    """
    Drafts a tailored single-angle LinkedIn outreach message (zero Looms/videos, zero em-dashes).
    """
    first_name = extract_safe_first_name(contact_name, default="Team")
    salutation = f"Dear {first_name},"
    clean_co = clean_company_name(company_name)
    clean_role = target_role.strip() or "the open role"
    track = (resume_version or "OPERATIONS").upper()

    if track == "AI":
        why_company = f"how {clean_co} is scaling practical AI systems and operational automation"
        xyz_story = (
            "At BridgingTheAIGap.com, manual handoffs and fragile LLM prompts slowed delivery, "
            "so I built deterministic Plan, Review, Execute agentic workflows that cut production time by 50% "
            "and saved 16 hours per week per team."
        )
    elif track == "MARKETING":
        why_company = f"how {clean_co} is scaling brand affinity and commercial growth"
        xyz_story = (
            "At CULT, commodity pricing squeezed our margins, so I repositioned the brand around cultural belonging "
            "and built an 80+ creator network, driving +263% revenue growth at a +40% price premium and 122x content volume."
        )
    else:
        why_company = f"how {clean_co} is scaling commercial execution and cross-functional operations"
        xyz_story = (
            "At Eircap Media, leaking call-centre handoffs were dropping warm leads, so I overhauled routing, scripts, "
            "and cross-team workflows, lifting funnel conversion from 10% to 18% and generating €40M+ in client revenue."
        )

    msg = (
        f"{salutation}\n\n"
        f"The {clean_role} role at {clean_co} is the exact role I am looking for because of {why_company}, "
        f"and I am a strong fit.\n\n"
        f"{xyz_story}\n\n"
        f"Would you be open to a quick chat or pointing me to the right person on the team?\n\n"
        f"Best,\n"
        f"{sender_name}"
    )
    return msg.replace("—", ", ").replace("–", ", ").replace("--", ", ")


def prepare_linkedin_outreach_for_approval(
    company_name: str,
    role_title: str,
    domain: str = "",
    send_approval_email: bool = False,
) -> Dict[str, Any]:
    """
    Discovers decision-makers at the target company and stages tailored LinkedIn outreach
    messages behind an explicit approval gate (`PENDING_APPROVAL`).
    """
    track = classify_resume_track(role_title, "")
    role_cat = "marketing" if track == "MARKETING" else "executive"
    candidates = discover_executives_from_web(company_name, domain, role_category=role_cat)

    if not candidates:
        candidates = [{
            "name": "Hiring Team",
            "first_name": "Team",
            "last_name": "",
            "role": f"{track.title()} Leadership",
            "source": f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(company_name + ' ' + role_title)}",
        }]

    outreach_items: List[Dict[str, Any]] = []
    for cand in candidates[:3]:
        li_msg = draft_general_linkedin_outreach(
            contact_name=cand.get("name", "Team"),
            contact_role=cand.get("role", "Leadership"),
            company_name=company_name,
            target_role=role_title,
            resume_version=track,
        )
        outreach_items.append({
            "company": company_name,
            "role": role_title,
            "resume_version": track,
            "contact_name": cand.get("name", "Team"),
            "contact_role": cand.get("role", "Leadership"),
            "linkedin_url": cand.get("source", ""),
            "linkedin_message": li_msg,
            "approval_status": "PENDING_APPROVAL",
        })

    return {
        "company": company_name,
        "role": role_title,
        "resume_version": track,
        "outreach_drafts": outreach_items,
        "approval_gate": "AWAITING_USER_APPROVAL_BEFORE_LINKEDIN_SEND",
    }


MCP_TOOLS = [
    {
        "name": "scrape_clean_markdown",
        "description": "Firecrawl / Jina Reader clean Markdown web scraper. Renders JS-heavy career pages, Ashby/Greenhouse/Workable boards, and company sites into clean Markdown.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Website or job posting URL to scrape into Markdown"},
                "max_chars": {"type": "integer", "description": "Max characters to return (default 8000)", "default": 8000},
            },
            "required": ["url"],
        },
    },
    {
        "name": "waterfall_find_decision_maker",
        "description": "OpenProspector 4-stage waterfall enrichment (Apollo.io -> Snov.io Domain Search -> Web/LinkedIn Executive Name Lookup + Hunter/Snov Resolver) with strict generic alias filtering.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_name": {"type": "string", "description": "Company name"},
                "domain": {"type": "string", "description": "Company domain (e.g. stripe.com)"},
                "job_category": {"type": "string", "description": "Role category (executive, marketing, admin-bizdev)", "default": "executive"},
            },
            "required": ["company_name", "domain"],
        },
    },
    {
        "name": "scan_live_ats_career_ops",
        "description": "Multi-ATS live scanner across Greenhouse, Ashby, Lever, Workable, SmartRecruiters, Recruitee, and live ATS search discovery across OPERATIONS, MARKETING, and AI tracks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "greenhouse_boards": {"type": "array", "items": {"type": "string"}},
                "ashby_boards": {"type": "array", "items": {"type": "string"}},
                "lever_boards": {"type": "array", "items": {"type": "string"}},
                "workable_boards": {"type": "array", "items": {"type": "string"}},
                "smartrecruiters_boards": {"type": "array", "items": {"type": "string"}},
                "recruitee_boards": {"type": "array", "items": {"type": "string"}},
                "include_live_search": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "validate_outreach_payload",
        "description": "Hard Pre-Send Quality Gate: checks candidate email/DM payloads for generic aliases (info@, careers@), unreplaced template braces ({first_name}), em-dashes, and headline-to-company mismatches.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "recipient_email": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "contact_name": {"type": "string"},
                "headline": {"type": "string"},
                "company_name": {"type": "string"},
            },
            "required": ["recipient_email", "subject", "body"],
        },
    },
    {
        "name": "prepare_linkedin_outreach_for_approval",
        "description": "Finds LinkedIn decision-makers at a target company and drafts approval-gated single-angle LinkedIn outreach messages (OPERATIONS, MARKETING, or AI).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_name": {"type": "string"},
                "role_title": {"type": "string"},
                "domain": {"type": "string"},
            },
            "required": ["company_name", "role_title"],
        },
    },
]


def handle_rpc_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "outreach-prospector-mcp", "version": "1.2.0"},
            },
        }
    if method.startswith("notifications/"):
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "scrape_clean_markdown":
                md = scrape_clean_markdown(args.get("url", ""), int(args.get("max_chars", 8000)))
                return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": md or "No content extracted."}]}}
            elif name == "waterfall_find_decision_maker":
                contacts = waterfall_find_decision_maker(
                    args.get("company_name", ""),
                    args.get("domain", ""),
                    args.get("job_category", "executive"),
                )
                return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(contacts, indent=2)}]}}
            elif name == "scan_live_ats_career_ops":
                jobs = scan_live_ats_career_ops(
                    greenhouse_boards=args.get("greenhouse_boards"),
                    ashby_boards=args.get("ashby_boards"),
                    lever_boards=args.get("lever_boards"),
                    workable_boards=args.get("workable_boards"),
                    smartrecruiters_boards=args.get("smartrecruiters_boards"),
                    recruitee_boards=args.get("recruitee_boards"),
                    include_live_search=args.get("include_live_search", True),
                )
                return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(jobs, indent=2)}]}}
            elif name == "validate_outreach_payload":
                res = validate_outreach_payload(
                    recipient_email=args.get("recipient_email", ""),
                    subject=args.get("subject", ""),
                    body=args.get("body", ""),
                    contact_name=args.get("contact_name", ""),
                    headline=args.get("headline", ""),
                    company_name=args.get("company_name", ""),
                )
                return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(res, indent=2)}]}}
            elif name == "prepare_linkedin_outreach_for_approval":
                res = prepare_linkedin_outreach_for_approval(
                    company_name=args.get("company_name", ""),
                    role_title=args.get("role_title", ""),
                    domain=args.get("domain", ""),
                )
                return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(res, indent=2)}]}}
            else:
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown tool: {name}"}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(e)}}

    if req_id is not None:
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    return None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="outreach-prospector-mcp",
        description="Zero-Cost Waterfall Enrichment, 6-ATS Scanner & Pre-Send Gate MCP Server",
    )
    parser.add_argument("--scrape", metavar="URL", help="Scrape a URL into clean LLM-ready Markdown")
    parser.add_argument("--waterfall", nargs=2, metavar=("COMPANY", "DOMAIN"), help="Run 4-stage waterfall decision-maker enrichment")
    parser.add_argument("--scan-ats", action="store_true", help="Scan live Greenhouse, Ashby, Lever, Workable, SmartRecruiters, and Recruitee boards")
    args, _ = parser.parse_known_args(argv)

    if args.scrape:
        print(scrape_clean_markdown(args.scrape))
        return 0
    if args.waterfall:
        print(json.dumps(waterfall_find_decision_maker(args.waterfall[0], args.waterfall[1]), indent=2))
        return 0
    if args.scan_ats:
        print(json.dumps(scan_live_ats_career_ops(include_live_search=False), indent=2))
        return 0

    # Default: Run Stdio JSON-RPC 2.0 MCP Server loop
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_rpc_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
