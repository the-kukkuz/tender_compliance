"""Tender requirement extraction service converting tender text into structured requirements."""

from __future__ import annotations

import asyncio
import concurrent.futures
import re
from typing import List, Optional, Tuple

from app.core.config import Settings, get_settings
from app.core.exceptions import ExternalLLMError
from app.core.logging import get_logger
from app.schemas.compliance import (
    RequirementCategory,
    RequirementPriority,
    SourceReference,
    TenderRequirement,
)
from app.schemas.document import DocumentExtractionResult
from app.services.grounding import verify_grounded_citation
from app.services.llm_provider import LLMProviderService

logger = get_logger(__name__)

# Category patterns: (Category, Default Title, Keywords, Expected Evidence, Default Permit Carryover)
_CATEGORY_CONFIG: List[Tuple[RequirementCategory, str, List[str], str, bool]] = [
    (
        RequirementCategory.SAFETY,
        "HSE Plan, Work-Permit & Site Safety Compliance",
        [
            "safety",
            "hse",
            "work permit",
            "ppe",
            "hazard",
            "incident",
            "confined space",
            "lifting",
            "occupational health",
        ],
        "Approved Corporate HSE Manual, Site Safety Plan, and Work-Permit Procedures.",
        True,
    ),
    (
        RequirementCategory.CERTIFICATION,
        "Quality & Management System Certifications",
        [
            "iso 9001",
            "iso 14001",
            "iso 45001",
            "certification",
            "accredited",
            "certificate",
            "api spec",
            "asme",
        ],
        "Valid copy of accredited ISO certificate with active validity period.",
        True,
    ),
    (
        RequirementCategory.FINANCIAL,
        "Minimum Annual Turnover & Financial Capacity",
        [
            "turnover",
            "financial",
            "net worth",
            "audited",
            "liquidity",
            "solvency",
            "annual revenue",
            "balance sheet",
            "banker's certificate",
            "bankers certificate",
            "bid capacity",
            "estimated cost",
            "earnest money",
            "emd",
            "tender fees",
            "tender fee",
        ],
        "Audited Financial Statements, certified balance sheets, CA net worth certificate, or EMD / tender fee proof.",
        False,
    ),
    (
        RequirementCategory.EXPERIENCE,
        "Similar Project Track Record & Experience",
        [
            "similar work",
            "similar works",
            "similar completed work",
            "similar completed works",
            "completed works",
            "experience",
            "similar project",
            "track record",
            "years of experience",
            "past performance",
            "completion certificate",
            "completion certificates",
            "reference letter",
            "client reference",
        ],
        "Client completion certificates with LOA, agreement copy, and executive engineer sign-off.",
        False,
    ),
    (
        RequirementCategory.ELIGIBILITY,
        "Bidder Statutory Registration & Eligibility",
        [
            "permanent account number",
            "pan",
            "gst",
            "gstin",
            "provident fund",
            "pf registration",
            "esi",
            "esi registration",
            "integrity pact",
            "make in india",
            "local content",
            "blacklisted",
            "debarred",
            "digital signature",
            "dsc",
            "eligible",
            "eligibility",
            "registered",
            "incorporation",
            "license",
            "trade license",
        ],
        "Valid PAN card, GST registration, EPF & ESI certificates, signed Integrity Pact, and non-debarment declaration.",
        False,
    ),
    (
        RequirementCategory.DEADLINE,
        "Submission & Completion Milestones",
        [
            "deadline",
            "submission date",
            "closing date",
            "completion period",
            "schedule",
            "milestone",
            "mobilization date",
        ],
        "Stipulated completion schedule adherence statement and milestone timeline.",
        False,
    ),
    (
        RequirementCategory.OTHER,
        "General Technical & Operational Specifications",
        [
            "specification",
            "warranty",
            "technical compliance",
            "qap",
            "quality assurance plan",
            "methodology",
            "soil investigation",
            "tender drawings",
        ],
        "Technical compliance statement, methodology, and quality assurance plan (QAP).",
        False,
    ),
]

_MONEY_PATTERN = re.compile(
    r"\b((?:Rs\.?|INR|USD|EUR|GBP|CAD|AUD|\$|€|£)\s*[\d,.]+(?:\s*(?:Crores?|Lakhs?|M|million|k|thousand|B|billion|/-))?|[\d,.]+\s*(?:Crores?|Lakhs?|M|million|k|thousand|B|billion)\s*(?:Rs\.?|INR|USD|EUR|GBP)?)\b",
    re.IGNORECASE,
)
_ISO_PATTERN = re.compile(r"\b(ISO\s*\d{4,5}(?::\d{4})?)\b", re.IGNORECASE)
_DATE_PATTERN = re.compile(r"\b(\d{2}[./-]\d{2}[./-]\d{4}|20\d{2}-\d{2}-\d{2})\b")
_YEARS_PATTERN = re.compile(
    r"\b(\d+\s*(?:\+)?\s*years?(?:\s*of\s*experience)?)\b", re.IGNORECASE
)

_MANDATORY_MARKERS = [
    "must",
    "shall",
    "required",
    "mandatory",
    "compulsory",
    "minimum",
    "is required to",
]
_OPTIONAL_MARKERS = [
    "optional",
    "recommended",
    "should",
    "preferred",
    "may",
    "if available",
]


class RequirementExtractorService:
    """Extracts structured TenderRequirement items with page-level source references."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        llm_provider: Optional[LLMProviderService] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm_provider = llm_provider or LLMProviderService(self.settings)

    def extract_requirements(
        self, tender_extraction: DocumentExtractionResult
    ) -> List[TenderRequirement]:
        """Extract requirements synchronously; calls LLM in live mode or rule engine in mock mode."""
        if not self.settings.llm_enabled:
            return self._extract_deterministic(tender_extraction)

        # In live mode, execute extract_requirements_async safely across event loop contexts
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run, self.extract_requirements_async(tender_extraction)
                ).result()
        return asyncio.run(self.extract_requirements_async(tender_extraction))

    async def extract_requirements_async(
        self, tender_extraction: DocumentExtractionResult
    ) -> List[TenderRequirement]:
        """Extract requirements using the configured LLM provider with grounding validation."""
        if not self.settings.llm_enabled:
            return self._extract_deterministic(tender_extraction)

        # Validate configuration before making external calls
        self.settings.validate_live_llm_config()

        requirements: List[TenderRequirement] = []
        filename = tender_extraction.metadata.filename
        req_counter = 1
        seen_criteria: set[str] = set()

        # Bounded page chunking: process up to 3000 chars per chunk
        for page in tender_extraction.pages:
            if not page.text or not page.text.strip():
                continue

            page_text = page.text
            chunk_size = 3000
            chunks = [
                page_text[i : i + chunk_size]
                for i in range(0, len(page_text), chunk_size)
            ]

            for chunk in chunks:
                try:
                    llm_res = await self.llm_provider.extract_requirements_from_chunk(
                        document_filename=filename,
                        page_number=page.page_number,
                        page_text=chunk,
                    )
                except ExternalLLMError as exc:
                    logger.warning(
                        f"LLM extraction unavailable ({exc}); gracefully falling back to deterministic extraction."
                    )
                    return self._extract_deterministic(tender_extraction)

                for item in llm_res.requirements:
                    # Grounding verification: check if item.excerpt exists in the actual page text
                    is_grounded, ground_err = verify_grounded_citation(
                        excerpt=item.excerpt,
                        page_number=item.page_number,
                        pages=tender_extraction.pages,
                    )

                    # Deduplication
                    fp = f"{item.title.lower()[:30]}_{item.excerpt.lower()[:40]}"
                    if fp in seen_criteria:
                        continue
                    seen_criteria.add(fp)

                    # Category mapping
                    cat_str = item.category.upper().strip()
                    try:
                        category = RequirementCategory(cat_str)
                    except ValueError:
                        category = RequirementCategory.OTHER

                    # Priority mapping
                    priority = (
                        RequirementPriority.MANDATORY
                        if item.priority.upper() == "MANDATORY"
                        else RequirementPriority.RECOMMENDED
                    )

                    # Deterministic criteria parsing in Python
                    det_thresh, det_unit, det_valid = self._extract_criteria_fields(
                        item.excerpt, category
                    )

                    threshold = item.threshold_or_criteria or det_thresh
                    unit_curr = item.unit_or_currency or det_unit
                    validity = item.validity_period or det_valid

                    # If grounding verification failed, mark needs_review
                    needs_review = (not is_grounded) or (threshold is None and priority == RequirementPriority.MANDATORY)
                    confidence = item.confidence if is_grounded else 0.40
                    desc = item.description
                    if not is_grounded:
                        desc = f"[Source Unverified: {ground_err}] {desc}"

                    carryover = item.requires_permit_carryover or (
                        category == RequirementCategory.SAFETY
                    )

                    req_id = f"REQ-{req_counter:03d}"
                    req_counter += 1

                    requirements.append(
                        TenderRequirement(
                            requirement_id=req_id,
                            category=category,
                            title=item.title,
                            description=desc[:400],
                            priority=priority,
                            source=SourceReference(
                                filename=filename,
                                page_number=item.page_number,
                                excerpt=item.excerpt[:240],
                            ),
                            threshold_or_criteria=threshold,
                            expected_evidence=(
                                "Supporting documentation addressing tender specification."
                            ),
                            unit_or_currency=unit_curr,
                            validity_period=validity,
                            confidence=round(confidence, 2),
                            needs_review=needs_review,
                            requires_permit_carryover=carryover,
                        )
                    )

        # Baseline fallback if LLM found 0 requirements
        if not requirements and tender_extraction.pages:
            return self._extract_deterministic(tender_extraction)

        return requirements

    def _extract_deterministic(
        self, tender_extraction: DocumentExtractionResult
    ) -> List[TenderRequirement]:
        """Extract requirements using deterministic keyword and modal verb matching."""
        requirements: List[TenderRequirement] = []
        filename = tender_extraction.metadata.filename
        req_counter = 1
        seen_criteria: set[str] = set()

        for page in tender_extraction.pages:
            if not page.text:
                continue

            raw_clauses = [
                s.strip()
                for s in re.split(r"(?<=[.!?;\n])\s+", page.text)
                if len(s.strip()) >= 15
            ]

            for clause in raw_clauses:
                lower_clause = clause.lower()

                has_requirement_intent = any(
                    marker in lower_clause
                    for marker in _MANDATORY_MARKERS
                    + _OPTIONAL_MARKERS
                    + [
                        "clause",
                        "section",
                        "criteria",
                        "standard",
                        "certified",
                        "turnover",
                        "certificate",
                        "iso",
                        "deadline",
                        "submission",
                        "schedule",
                        "experience",
                        "reference",
                        "safety",
                        "permit",
                        "ppe",
                    ]
                )
                if not has_requirement_intent:
                    continue

                for (
                    category,
                    default_title,
                    keywords,
                    expected_evidence,
                    carryover,
                ) in _CATEGORY_CONFIG:
                    if any(kw in lower_clause for kw in keywords):
                        clause_fingerprint = lower_clause[:60]
                        if clause_fingerprint in seen_criteria:
                            continue
                        seen_criteria.add(clause_fingerprint)

                        is_mandatory = not any(
                            opt in lower_clause for opt in _OPTIONAL_MARKERS
                        )
                        priority = (
                            RequirementPriority.MANDATORY
                            if is_mandatory
                            else RequirementPriority.RECOMMENDED
                        )

                        (
                            threshold_or_criteria,
                            unit_or_currency,
                            validity_period,
                        ) = self._extract_criteria_fields(clause, category)

                        confidence = (
                            0.92 if (is_mandatory and threshold_or_criteria) else 0.85
                        )
                        needs_review = threshold_or_criteria is None and is_mandatory

                        req_id = f"REQ-{req_counter:03d}"
                        req_counter += 1

                        requirements.append(
                            TenderRequirement(
                                requirement_id=req_id,
                                category=category,
                                title=default_title,
                                description=clause[:400],
                                priority=priority,
                                source=SourceReference(
                                    filename=filename,
                                    page_number=page.page_number,
                                    excerpt=clause[:240],
                                ),
                                threshold_or_criteria=threshold_or_criteria,
                                expected_evidence=expected_evidence,
                                unit_or_currency=unit_or_currency,
                                validity_period=validity_period,
                                confidence=confidence,
                                needs_review=needs_review,
                                requires_permit_carryover=carryover
                                or (category == RequirementCategory.SAFETY),
                            )
                        )
                        break

        if not requirements and tender_extraction.pages:
            first_page = tender_extraction.pages[0]
            excerpt = (first_page.text or "General tender compliance criteria.")[:200]
            requirements.append(
                TenderRequirement(
                    requirement_id="REQ-001",
                    category=RequirementCategory.ELIGIBILITY,
                    title="General Tender Eligibility & Submission Compliance",
                    description="Verify general bidder eligibility against tender terms.",
                    priority=RequirementPriority.MANDATORY,
                    source=SourceReference(
                        filename=filename,
                        page_number=first_page.page_number,
                        excerpt=excerpt,
                    ),
                    threshold_or_criteria="Standard Bidder Eligibility",
                    expected_evidence="Valid registration documentation and trade license.",
                    confidence=0.85,
                    needs_review=False,
                    requires_permit_carryover=False,
                )
            )

        return requirements

    @staticmethod
    def _extract_criteria_fields(
        text: str, category: RequirementCategory
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Extract threshold, unit/currency, and validity/date from requirement clause."""
        threshold: Optional[str] = None
        unit_or_currency: Optional[str] = None
        validity: Optional[str] = None

        date_m = _DATE_PATTERN.search(text)
        if date_m:
            validity = date_m.group(1)

        if category == RequirementCategory.FINANCIAL:
            money_m = _MONEY_PATTERN.search(text)
            if money_m:
                threshold = money_m.group(1).strip()
                for curr in ["USD", "EUR", "GBP", "CAD", "AUD", "INR", "$", "€", "£"]:
                    if curr.lower() in threshold.lower():
                        unit_or_currency = curr.upper()
                        break
        elif category == RequirementCategory.CERTIFICATION:
            iso_m = _ISO_PATTERN.search(text)
            if iso_m:
                threshold = iso_m.group(1).strip()
        elif category == RequirementCategory.EXPERIENCE:
            years_m = _YEARS_PATTERN.search(text)
            if years_m:
                threshold = years_m.group(1).strip()
        elif category == RequirementCategory.DEADLINE:
            if validity:
                threshold = f"Deadline: {validity}"

        return threshold, unit_or_currency, validity
