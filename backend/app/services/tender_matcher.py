"""Tender compliance matching, deterministic qualification checks, scoring, and ranking engine."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.core.logging import get_logger
from app.schemas.compliance import (
    BidderEvidence,
    ComplianceStatus,
    ComplianceSummaryMetrics,
    RequirementAssessment,
    RequirementCategory,
    RequirementPriority,
    TenderRequirement,
)
from app.schemas.profile import BidderProfile
from app.schemas.tender import TenderMatchSummary, TenderResponse

logger = get_logger(__name__)

DISCLAIMER_TEXT = (
    "Automated screening estimate for decision-support only. "
    "This calculation does not constitute legal eligibility determination or formal contract adjudication. "
    "Human verification by qualified procurement personnel is required."
)

SORTING_RULE_LABEL = "Compliance Score (highest first) → Mandatory Requirements Satisfied → Earliest Closing Date"


class TenderMatcherService:
    """Evaluates tenders against bidder qualification profile with deterministic rules and scoring."""

    def evaluate_tender_against_profile(
        self,
        tender: TenderResponse,
        profile: BidderProfile,
        today_str: Optional[str] = None,
    ) -> Tuple[List[RequirementAssessment], ComplianceSummaryMetrics, bool, List[str], List[str]]:
        """Run deterministic checks for every requirement of the tender against bidder profile data."""
        today = today_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_date = date.fromisoformat(today)

        assessments: List[RequirementAssessment] = []
        mandatory_missing: List[str] = []
        conflicts: List[str] = []

        requirements = tender.extracted_requirements

        for req in requirements:
            status = ComplianceStatus.MISSING
            evidence_items: List[BidderEvidence] = []
            discrepancies: List[str] = []
            rationale = ""
            action = ""

            # Check by Category
            if req.category == RequirementCategory.FINANCIAL:
                # Compare turnover
                if tender.financial_threshold and tender.financial_threshold > 0:
                    req_threshold = tender.financial_threshold
                    req_curr = tender.financial_currency or "USD"
                    bidder_turnover = profile.annual_turnover
                    bidder_curr = profile.currency

                    if req_curr != bidder_curr:
                        status = ComplianceStatus.NEEDS_REVIEW
                        rationale = f"Currency conversion required: tender requires {req_curr} but bidder specifies {bidder_curr}."
                        discrepancies.append(rationale)
                        action = "Verify currency exchange conversion rate."
                    elif bidder_turnover >= req_threshold:
                        status = ComplianceStatus.EVIDENCE_FOUND
                        rationale = (
                            f"Bidder audited turnover ({bidder_turnover:,.0f} {bidder_curr}) "
                            f"meets or exceeds required threshold ({req_threshold:,.0f} {req_curr})."
                        )
                        action = "Retain certified financial statement."
                    else:
                        status = ComplianceStatus.CONFLICTING
                        rationale = (
                            f"Bidder turnover ({bidder_turnover:,.0f} {bidder_curr}) is below "
                            f"the required threshold ({req_threshold:,.0f} {req_curr})."
                        )
                        discrepancies.append(rationale)
                        conflicts.append(f"Financial threshold shortfall for '{req.title}'")
                        action = "Assess consortium or joint venture options."
                else:
                    if profile.financial_audited and profile.annual_turnover > 0:
                        status = ComplianceStatus.EVIDENCE_FOUND
                        rationale = f"Audited financial statements confirmed ({profile.annual_turnover:,.0f} {profile.currency})."
                    else:
                        status = ComplianceStatus.MISSING
                        rationale = "Audited financial statements not confirmed in profile."
                        action = "Attach audited balance sheet."

                evidence_items.append(
                    BidderEvidence(
                        evidence_id=f"EVD-FIN-{profile.profile_id[:6]}",
                        requirement_id=req.requirement_id,
                        source_document_id=profile.profile_id,
                        filename="bidder_profile.json",
                        page_number=1,
                        excerpt=f"Audited Annual Turnover: {profile.annual_turnover:,.0f} {profile.currency}",
                        extracted_value=str(profile.annual_turnover),
                        confidence=0.95,
                    )
                )

            elif req.category == RequirementCategory.EXPERIENCE:
                req_years = tender.min_experience_years or 0.0
                if req.threshold_or_criteria:
                    m = re.search(r"(\d+)", req.threshold_or_criteria)
                    if m:
                        req_years = max(req_years, float(m.group(1)))

                if profile.experience_years >= req_years:
                    status = ComplianceStatus.EVIDENCE_FOUND
                    rationale = (
                        f"Operating experience of {profile.experience_years:.0f} years "
                        f"satisfies requirement of {req_years:.0f} years."
                    )
                else:
                    status = ComplianceStatus.CONFLICTING
                    rationale = (
                        f"Operating experience of {profile.experience_years:.0f} years "
                        f"is below required {req_years:.0f} years."
                    )
                    discrepancies.append(rationale)
                    conflicts.append(f"Operating experience shortfall for '{req.title}'")

                evidence_items.append(
                    BidderEvidence(
                        evidence_id=f"EVD-EXP-{profile.profile_id[:6]}",
                        requirement_id=req.requirement_id,
                        source_document_id=profile.profile_id,
                        filename="bidder_profile.json",
                        page_number=1,
                        excerpt=f"{profile.experience_summary} ({profile.experience_years:.0f} years)",
                        extracted_value=f"{profile.experience_years:.0f} years",
                        confidence=0.92,
                    )
                )

            elif req.category == RequirementCategory.CERTIFICATION:
                # Find matching certification in profile
                title_lower = (req.title + " " + req.description + " " + (req.threshold_or_criteria or "")).lower()
                matched_cert = None
                for cert in profile.certifications:
                    cert_name_clean = cert.name.lower().replace(":", "").replace("-", " ")
                    cert_num_parts = cert_name_clean.split()
                    if any(part in title_lower for part in cert_num_parts if len(part) >= 3):
                        matched_cert = cert
                        break

                if matched_cert:
                    if matched_cert.valid_until:
                        try:
                            exp_date = date.fromisoformat(matched_cert.valid_until)
                            if exp_date < today_date:
                                status = ComplianceStatus.CONFLICTING
                                rationale = (
                                    f"Certificate '{matched_cert.name}' expired on {matched_cert.valid_until} "
                                    f"(prior to reference date {today})."
                                )
                                discrepancies.append(rationale)
                                conflicts.append(f"Expired certificate: {matched_cert.name} ({matched_cert.valid_until})")
                                action = "Renew or update certificate prior to bid submission."
                            else:
                                status = ComplianceStatus.EVIDENCE_FOUND
                                rationale = (
                                    f"Active accredited certificate '{matched_cert.name}' valid until "
                                    f"{matched_cert.valid_until} (accredited by {matched_cert.accredited_by or 'Registrar'})."
                                )
                        except ValueError:
                            status = ComplianceStatus.NEEDS_REVIEW
                            rationale = f"Certificate date format invalid: {matched_cert.valid_until}."
                            discrepancies.append(rationale)
                    else:
                        status = ComplianceStatus.NEEDS_REVIEW
                        rationale = f"Certificate '{matched_cert.name}' has no recorded expiry date."
                        discrepancies.append(rationale)

                    evidence_items.append(
                        BidderEvidence(
                            evidence_id=f"EVD-CERT-{profile.profile_id[:6]}",
                            requirement_id=req.requirement_id,
                            source_document_id=profile.profile_id,
                            filename="bidder_profile.json",
                            page_number=1,
                            excerpt=f"{matched_cert.name} (License #{matched_cert.cert_number or 'N/A'}, Valid Until: {matched_cert.valid_until})",
                            extracted_value=matched_cert.name,
                            valid_until=matched_cert.valid_until,
                            confidence=0.90,
                        )
                    )
                else:
                    status = ComplianceStatus.MISSING
                    rationale = f"Certificate matching '{req.title}' was not found in bidder profile."
                    discrepancies.append("Required accreditation is absent from bidder profile.")
                    action = "Upload valid copy of required certificate."

            elif req.category == RequirementCategory.SAFETY:
                if profile.safety_manual_approved:
                    status = ComplianceStatus.EVIDENCE_FOUND
                    rationale = "Corporate HSE manual and safety procedures confirmed approved in bidder profile."
                    evidence_items.append(
                        BidderEvidence(
                            evidence_id=f"EVD-SAFE-{profile.profile_id[:6]}",
                            requirement_id=req.requirement_id,
                            source_document_id=profile.profile_id,
                            filename="bidder_profile.json",
                            page_number=1,
                            excerpt="Approved Corporate HSE Manual and Work-Permit Procedures.",
                            extracted_value="HSE Manual Approved",
                            confidence=0.90,
                        )
                    )
                else:
                    status = ComplianceStatus.MISSING
                    rationale = "Approved HSE manual / safety procedures not recorded in profile."
                    action = "Upload approved corporate safety policy and work-permit procedure."

            elif req.category == RequirementCategory.ELIGIBILITY:
                if profile.business_identifiers:
                    ident_str = ", ".join(f"{b.id_type}: {b.value}" for b in profile.business_identifiers)
                    status = ComplianceStatus.EVIDENCE_FOUND
                    rationale = f"Legal registration verified ({ident_str})."
                    evidence_items.append(
                        BidderEvidence(
                            evidence_id=f"EVD-ELIG-{profile.profile_id[:6]}",
                            requirement_id=req.requirement_id,
                            source_document_id=profile.profile_id,
                            filename="bidder_profile.json",
                            page_number=1,
                            excerpt=ident_str,
                            extracted_value=ident_str,
                            confidence=0.95,
                        )
                    )
                else:
                    status = ComplianceStatus.MISSING
                    rationale = "Business registration / commercial registration missing in profile."
                    action = "Add commercial trade license or tax ID."

            else:
                # Other / General: check if profile has general qualifications
                if profile.other_qualifications or profile.is_verified:
                    status = ComplianceStatus.EVIDENCE_FOUND
                    rationale = "Standard technical and qualification requirements satisfied by verified profile."
                else:
                    status = ComplianceStatus.NEEDS_REVIEW
                    rationale = "Specific technical specification requires human review."

            if req.priority == RequirementPriority.MANDATORY:
                if status == ComplianceStatus.MISSING:
                    mandatory_missing.append(req.title)
                elif status == ComplianceStatus.CONFLICTING:
                    conflicts.append(f"Conflict in mandatory requirement '{req.title}'")

            assessments.append(
                RequirementAssessment(
                    requirement_id=req.requirement_id,
                    requirement=req,
                    status=status,
                    matched_evidence=evidence_items,
                    rationale=rationale,
                    discrepancies=discrepancies,
                    recommended_action=action or "Review and retain for final bid filing.",
                )
            )

        # Build summary metrics
        total = len(requirements)
        evidence_found = sum(1 for a in assessments if a.status == ComplianceStatus.EVIDENCE_FOUND)
        missing_count = sum(1 for a in assessments if a.status == ComplianceStatus.MISSING)
        conflicting_count = sum(1 for a in assessments if a.status == ComplianceStatus.CONFLICTING)
        needs_review_count = sum(1 for a in assessments if a.status == ComplianceStatus.NEEDS_REVIEW)

        mandatory_reqs = [a for a in assessments if a.requirement.priority == RequirementPriority.MANDATORY]
        mandatory_gaps = sum(1 for a in mandatory_reqs if a.status in (ComplianceStatus.MISSING, ComplianceStatus.CONFLICTING))

        readiness_score = round((evidence_found / total) * 100.0, 1) if total > 0 else 0.0

        summary = ComplianceSummaryMetrics(
            total_requirements=total,
            evidence_found_count=evidence_found,
            missing_count=missing_count,
            conflicting_count=conflicting_count,
            needs_review_count=needs_review_count,
            mandatory_gap_count=mandatory_gaps,
            safety_requirements_count=sum(1 for a in assessments if a.requirement.category == RequirementCategory.SAFETY),
            overall_readiness_score=readiness_score,
            by_category={},
        )

        has_gaps = (len(mandatory_missing) > 0) or (len(conflicts) > 0) or (mandatory_gaps > 0)
        return assessments, summary, has_gaps, mandatory_missing, conflicts

    def match_all_tenders(
        self,
        tenders: List[TenderResponse],
        profile: BidderProfile,
        today_str: Optional[str] = None,
        category_filter: Optional[str] = None,
        max_financial_threshold: Optional[float] = None,
        location_filter: Optional[str] = None,
        required_cert_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[TenderMatchSummary], int]:
        """Evaluate and rank all eligible tenders against the bidder profile."""
        today = today_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_date = date.fromisoformat(today)

        matched_summaries: List[TenderMatchSummary] = []

        for tender in tenders:
            # Apply supported filters
            if category_filter and tender.category.upper() != category_filter.upper():
                continue

            if max_financial_threshold is not None:
                if tender.financial_threshold and tender.financial_threshold > max_financial_threshold:
                    continue

            if location_filter and tender.geographic_restrictions:
                loc_match = any(location_filter.lower() in loc.lower() for loc in tender.geographic_restrictions)
                if not loc_match:
                    continue

            if required_cert_filter:
                cert_match = any(
                    required_cert_filter.lower() in c.lower() for c in tender.required_certifications
                )
                if not cert_match:
                    continue

            (
                assessments,
                summary,
                has_mandatory_gaps,
                mandatory_missing,
                conflicts,
            ) = self.evaluate_tender_against_profile(tender, profile, today)

            # Mandatory vs optional breakdown
            mandatory_items = [
                a for a in assessments if a.requirement.priority == RequirementPriority.MANDATORY
            ]
            optional_items = [
                a for a in assessments if a.requirement.priority != RequirementPriority.MANDATORY
            ]

            mandatory_satisfied = sum(
                1 for a in mandatory_items if a.status == ComplianceStatus.EVIDENCE_FOUND
            )
            optional_satisfied = sum(
                1 for a in optional_items if a.status == ComplianceStatus.EVIDENCE_FOUND
            )

            # Scoring: Mandatory carries 80% weight, optional carries 20%
            mandatory_total = len(mandatory_items)
            optional_total = len(optional_items)

            mand_ratio = (mandatory_satisfied / mandatory_total) if mandatory_total > 0 else 1.0
            opt_ratio = (optional_satisfied / optional_total) if optional_total > 0 else 1.0

            raw_score = round((mand_ratio * 80.0) + (opt_ratio * 20.0), 1)

            # Missing mandatory evidence MUST prevent tender from being labelled fully compliant
            if has_mandatory_gaps or mandatory_satisfied < mandatory_total:
                compliance_score = min(raw_score, 74.9)
            else:
                compliance_score = raw_score

            # Days remaining
            try:
                deadline_dt = date.fromisoformat(tender.submission_deadline)
                days_rem = (deadline_dt - today_date).days
            except ValueError:
                days_rem = 0

            # Match explanation
            if not has_mandatory_gaps:
                explanation = (
                    f"Strong compliance ({mandatory_satisfied}/{mandatory_total} mandatory met). "
                    f"Profile turnover ({profile.annual_turnover:,.0f} {profile.currency}) and credentials address specifications."
                )
                next_action = "Ready to apply with saved bidder profile."
            else:
                gap_reasons = []
                if mandatory_missing:
                    gap_reasons.append(f"Missing mandatory items: {', '.join(mandatory_missing[:2])}")
                if conflicts:
                    gap_reasons.append(f"Discrepancies: {', '.join(conflicts[:2])}")
                explanation = " / ".join(gap_reasons) if gap_reasons else "Mandatory qualifications require review."
                next_action = "Review and address outstanding mandatory gaps before submitting proposal."

            matched_summaries.append(
                TenderMatchSummary(
                    tender=tender,
                    compliance_score=compliance_score,
                    has_mandatory_gaps=has_mandatory_gaps,
                    mandatory_satisfied_count=mandatory_satisfied,
                    mandatory_total_count=mandatory_total,
                    optional_satisfied_count=optional_satisfied,
                    optional_total_count=optional_total,
                    missing_mandatory_titles=mandatory_missing,
                    conflicting_items=conflicts,
                    supporting_evidence_count=sum(len(a.matched_evidence) for a in assessments),
                    match_explanation=explanation,
                    days_remaining=days_rem,
                    next_action=next_action,
                    sorting_rule=SORTING_RULE_LABEL,
                    disclaimer=DISCLAIMER_TEXT,
                    requirement_assessments=assessments,
                )
            )

        # Multi-factor Deterministic Tie-Breakers:
        # 1. Compliance score descending
        # 2. Mandatory satisfied count descending
        # 3. Unresolved/conflicting items count ascending
        # 4. Closing date ascending (sooner deadline first)
        def _sort_key(m: TenderMatchSummary):
            return (
                -m.compliance_score,
                -m.mandatory_satisfied_count,
                len(m.conflicting_items) + len(m.missing_mandatory_titles),
                m.days_remaining if m.days_remaining >= 0 else 99999,
            )

        matched_summaries.sort(key=_sort_key)

        total_count = len(matched_summaries)
        offset = (page - 1) * page_size
        paginated_results = matched_summaries[offset : offset + page_size]

        return paginated_results, total_count
