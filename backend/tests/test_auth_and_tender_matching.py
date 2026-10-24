"""Comprehensive unit and integration tests for authentication, profiles, tender extraction,
matching, versioning, and cross-organisation data isolation.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import build_text_pdf_bytes


def test_registration_login_and_role_permissions(client: TestClient) -> None:
    """Test user registration, password verification, token issuance, and role isolation."""
    # 1. Register Seeker
    reg_seeker = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Alice Seeker",
            "email": "alice@buildcorp.com",
            "password": "Password123!",
            "organisation_name": "BuildCorp Engineering Ltd",
            "role": "SEEKER",
        },
    )
    assert reg_seeker.status_code == 201
    seeker_data = reg_seeker.json()["data"]
    seeker_token = seeker_data["access_token"]
    assert seeker_data["user"]["role"] == "SEEKER"

    # 2. Duplicate registration fails
    dup_reg = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Alice Duplicate",
            "email": "alice@buildcorp.com",
            "password": "Password123!",
            "organisation_name": "BuildCorp",
            "role": "SEEKER",
        },
    )
    assert dup_reg.status_code == 400

    # 3. Register Issuer
    reg_issuer = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Bob Issuer",
            "email": "bob@govprocure.gov",
            "password": "Password456!",
            "organisation_name": "Department of Public Works",
            "role": "ISSUER",
        },
    )
    assert reg_issuer.status_code == 201
    issuer_token = reg_issuer.json()["data"]["access_token"]

    # 4. Login with correct and incorrect credentials
    bad_login = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@buildcorp.com", "password": "WrongPassword"},
    )
    assert bad_login.status_code == 401

    good_login = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@buildcorp.com", "password": "Password123!"},
    )
    assert good_login.status_code == 200
    assert "access_token" in good_login.json()["data"]

    # 5. Role restrictions: Seeker cannot access issuer routes
    seeker_headers = {"Authorization": f"Bearer {seeker_token}"}
    issuer_headers = {"Authorization": f"Bearer {issuer_token}"}

    forbidden_publish = client.get("/api/v1/tenders/my", headers=seeker_headers)
    assert forbidden_publish.status_code == 403

    # Issuer cannot access seeker profile route
    forbidden_profile = client.get("/api/v1/profile", headers=issuer_headers)
    assert forbidden_profile.status_code == 403

    # 6. GET /api/v1/auth/me
    me_resp = client.get("/api/v1/auth/me", headers=seeker_headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["data"]["email"] == "alice@buildcorp.com"


def test_bidder_profile_retrieval_and_editing(client: TestClient) -> None:
    """Test retrieving and updating bidder profile data."""
    # Register seeker
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Profile Owner",
            "email": "owner@profiletest.com",
            "password": "SecurePassword1!",
            "organisation_name": "Apex Constructors",
            "role": "SEEKER",
        },
    )
    token = reg.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # GET default profile
    get_resp = client.get("/api/v1/profile", headers=headers)
    assert get_resp.status_code == 200
    profile = get_resp.json()["data"]
    assert profile["organisation_name"] == "Apex Constructors"
    assert profile["annual_turnover"] > 0

    # PUT updated profile
    put_resp = client.put(
        "/api/v1/profile",
        headers=headers,
        json={
            "annual_turnover": 12500000.0,
            "currency": "USD",
            "experience_years": 10.0,
            "certifications": [
                {
                    "name": "ISO 9001:2015",
                    "cert_number": "CERT-9001",
                    "valid_until": "2029-01-01",
                    "accredited_by": "BSI",
                },
                {
                    "name": "ISO 45001",
                    "cert_number": "CERT-45001",
                    "valid_until": "2028-06-30",
                    "accredited_by": "TUV",
                },
            ],
            "locations": ["North America", "Texas"],
            "safety_manual_approved": True,
        },
    )
    assert put_resp.status_code == 200
    updated = put_resp.json()["data"]
    assert updated["annual_turnover"] == 12500000.0
    assert updated["experience_years"] == 10.0
    assert len(updated["certifications"]) == 2


def test_single_document_tender_upload_extraction_and_publication(client: TestClient) -> None:
    """Test one-document tender PDF extraction, review, and publication."""
    # Register Issuer
    reg_issuer = client.post(
        "/api/v1/auth/register",
        json={
            "name": "City Engineer",
            "email": "city@metrogov.org",
            "password": "PasswordCity1!",
            "organisation_name": "Metropolitan Water Authority",
            "role": "ISSUER",
        },
    )
    issuer_token = reg_issuer.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {issuer_token}"}

    # Create Tender PDF
    tender_pdf = build_text_pdf_bytes(
        [
            "INVITATION TO TENDER: Municipal Water Infrastructure Upgrade 2026. "
            "Clause 1.1: Bidder must hold valid ISO 9001 and ISO 45001 certification. "
            "Clause 1.2: Minimum annual audited turnover of USD 4,000,000 required.",
            "Clause 2.1: Minimum 5 years operating experience in industrial water works. "
            "Clause 2.2: Mandatory corporate HSE plan and site safety procedure compliance. "
            "Submission deadline: 2026-11-30.",
        ]
    )

    # 1. POST /api/v1/tenders/upload-and-extract
    extract_resp = client.post(
        "/api/v1/tenders/upload-and-extract",
        headers=headers,
        files={"tender_file": ("water_tender.pdf", tender_pdf, "application/pdf")},
    )
    assert extract_resp.status_code == 200
    extracted_data = extract_resp.json()["data"]
    draft_tender = extracted_data["extracted_tender"]
    assert draft_tender["document_id"].startswith("DOC-TND-")
    assert len(draft_tender["extracted_requirements"]) >= 2

    # 2. POST /api/v1/tenders (Publish)
    publish_resp = client.post(
        "/api/v1/tenders",
        headers=headers,
        json=draft_tender,
    )
    assert publish_resp.status_code == 201
    published_tender = publish_resp.json()["data"]
    tender_id = published_tender["tender_id"]
    assert tender_id.startswith("TND-")
    assert published_tender["requirement_version"] == 1
    assert published_tender["status"] == "PUBLISHED"

    # 3. Check Issuer's tender list
    my_tenders_resp = client.get("/api/v1/tenders/my", headers=headers)
    assert my_tenders_resp.status_code == 200
    my_tenders = my_tenders_resp.json()["data"]
    assert len(my_tenders) >= 1
    assert my_tenders[0]["tender"]["tender_id"] == tender_id
    assert my_tenders[0]["submission_count"] == 0


def test_tender_matching_scoring_tiebreakers_and_versioning(client: TestClient) -> None:
    """Test seeker matching against published tenders, sorting, tie-breakers, and submission to exact tender ID."""
    # 1. Register Issuer
    issuer_resp = client.post(
        "/api/v1/auth/register",
        json={
            "name": "State Procurement",
            "email": "procure@state.gov",
            "password": "StatePassword1!",
            "organisation_name": "State Highway Dept",
            "role": "ISSUER",
        },
    )
    issuer_token = issuer_resp.json()["data"]["access_token"]
    issuer_headers = {"Authorization": f"Bearer {issuer_token}"}

    # 2. Create Tender A (Matches profile well)
    pdf_a = build_text_pdf_bytes(
        [
            "Tender Alpha: Highway Resurfacing. Mandatory ISO 9001 certification. "
            "Minimum turnover USD 2,000,000 required. Minimum 3 years experience. "
            "Submission deadline: 2026-10-31.",
        ]
    )
    ext_a = client.post(
        "/api/v1/tenders/upload-and-extract",
        headers=issuer_headers,
        files={"tender_file": ("tender_a.pdf", pdf_a, "application/pdf")},
    ).json()["data"]["extracted_tender"]
    ext_a["submission_deadline"] = "2026-10-31"
    ext_a["financial_threshold"] = 2000000.0
    ext_a["min_experience_years"] = 3.0

    pub_a = client.post("/api/v1/tenders", headers=issuer_headers, json=ext_a).json()["data"]
    tender_a_id = pub_a["tender_id"]

    # 3. Create Tender B (Higher requirements, tight deadline)
    pdf_b = build_text_pdf_bytes(
        [
            "Tender Beta: Suspension Bridge Engineering. Mandatory ISO 9001 and ISO 45001. "
            "Minimum turnover USD 15,000,000 required. Minimum 12 years experience. "
            "Submission deadline: 2026-11-15.",
        ]
    )
    ext_b = client.post(
        "/api/v1/tenders/upload-and-extract",
        headers=issuer_headers,
        files={"tender_file": ("tender_b.pdf", pdf_b, "application/pdf")},
    ).json()["data"]["extracted_tender"]
    ext_b["submission_deadline"] = "2026-11-15"
    ext_b["financial_threshold"] = 15000000.0  # Above seeker's turnover
    ext_b["min_experience_years"] = 12.0

    pub_b = client.post("/api/v1/tenders", headers=issuer_headers, json=ext_b).json()["data"]
    tender_b_id = pub_b["tender_id"]

    # 4. Register Seeker with $6.5M turnover, 5 years experience, ISO 9001 and ISO 45001
    seeker_resp = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Highway Contractor",
            "email": "contact@roadworks.com",
            "password": "RoadworksPassword1!",
            "organisation_name": "RoadWorks Ltd",
            "role": "SEEKER",
        },
    )
    seeker_token = seeker_resp.json()["data"]["access_token"]
    seeker_headers = {"Authorization": f"Bearer {seeker_token}"}

    # Update seeker profile with verified values
    client.put(
        "/api/v1/profile",
        headers=seeker_headers,
        json={
            "annual_turnover": 6500000.0,
            "currency": "USD",
            "experience_years": 5.0,
            "certifications": [
                {
                    "name": "ISO 9001:2015",
                    "cert_number": "CERT-9001",
                    "valid_until": "2028-12-31",
                    "accredited_by": "BSI",
                },
                {
                    "name": "ISO 45001",
                    "cert_number": "CERT-45001",
                    "valid_until": "2028-12-31",
                    "accredited_by": "BSI",
                },
            ],
            "safety_manual_approved": True,
        },
    )

    # 5. Search tenders and check ranking
    search_resp = client.get("/api/v1/tenders/search", headers=seeker_headers)
    assert search_resp.status_code == 200
    matches = search_resp.json()["data"]
    assert len(matches) >= 2

    # Tender Alpha should be ranked higher than Tender Beta because Seeker satisfies Tender Alpha ($6.5M >= $2M)
    # whereas Tender Beta has a financial shortfall ($6.5M < $15M) and experience shortfall (5 < 12)
    top_match = matches[0]
    assert top_match["tender"]["tender_id"] == tender_a_id
    assert top_match["compliance_score"] >= 80.0
    assert not top_match["has_mandatory_gaps"]

    # Tender Beta should have lower score and mandatory gaps flagged
    beta_match = next(m for m in matches if m["tender"]["tender_id"] == tender_b_id)
    assert beta_match["compliance_score"] <= 74.9
    assert beta_match["has_mandatory_gaps"] is True

    # 6. Seeker submits specifically to Tender Alpha
    apply_resp = client.post(f"/api/v1/tenders/{tender_a_id}/apply", headers=seeker_headers)
    assert apply_resp.status_code == 200
    submission = apply_resp.json()["data"]
    assert submission["tender_id"] == tender_a_id
    assert submission["requirement_version"] == 1
    assert submission["bidder_organisation"] == "RoadWorks Ltd"
    assert submission["compliance_score"] >= 80.0

    # 7. Issuer reviews submissions comparison matrix for Tender Alpha
    subs_resp = client.get(f"/api/v1/tenders/{tender_a_id}/submissions", headers=issuer_headers)
    assert subs_resp.status_code == 200
    sub_rows = subs_resp.json()["data"]
    assert len(sub_rows) == 1
    assert sub_rows[0]["bidder_organisation"] == "RoadWorks Ltd"
    assert sub_rows[0]["compliance_score"] >= 80.0

    # 8. Cross-organisation isolation: Another issuer cannot view Tender Alpha's submissions
    other_issuer_resp = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Different Issuer",
            "email": "other@diffgov.org",
            "password": "PasswordOther1!",
            "organisation_name": "Unrelated Agency",
            "role": "ISSUER",
        },
    )
    other_token = other_issuer_resp.json()["data"]["access_token"]
    forbidden_view = client.get(
        f"/api/v1/tenders/{tender_a_id}/submissions",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert forbidden_view.status_code == 403

    # 9. Requirement versioning: Issuer updates requirements of Tender Alpha
    updated_reqs = pub_a["extracted_requirements"]
    updated_tender = client.put(
        f"/api/v1/tenders/{tender_a_id}",
        headers=issuer_headers,
        json={
            "title": "Tender Alpha: Updated Scope",
            "extracted_requirements": updated_reqs,
        },
    )
    assert updated_tender.status_code == 200
    assert updated_tender.json()["data"]["requirement_version"] == 2
    assert updated_tender.json()["data"]["title"] == "Tender Alpha: Updated Scope"


def test_expired_certificate_and_numeric_threshold_penalties(client: TestClient) -> None:
    """Validate that expired certificates and monetary shortfalls trigger conflicts and cap compliance score."""
    # Register Issuer
    issuer_resp = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Compliance Auditor",
            "email": "audit@oilgas.com",
            "password": "PasswordAudit1!",
            "organisation_name": "Offshore Energy Corp",
            "role": "ISSUER",
        },
    )
    issuer_token = issuer_resp.json()["data"]["access_token"]
    issuer_headers = {"Authorization": f"Bearer {issuer_token}"}

    tender_pdf = build_text_pdf_bytes(
        [
            "Offshore Maintenance Contract. Mandatory requirement: ISO 45001 certification. "
            "Minimum turnover USD 10,000,000 required. Submission deadline: 2026-12-15.",
        ]
    )
    ext = client.post(
        "/api/v1/tenders/upload-and-extract",
        headers=issuer_headers,
        files={"tender_file": ("offshore.pdf", tender_pdf, "application/pdf")},
    ).json()["data"]["extracted_tender"]
    ext["financial_threshold"] = 10000000.0

    pub = client.post("/api/v1/tenders", headers=issuer_headers, json=ext).json()["data"]
    tender_id = pub["tender_id"]

    # Register Seeker with EXPIRED ISO 45001 certificate (expired in 2024)
    seeker_resp = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Expired Bidder",
            "email": "expired@bidder.com",
            "password": "PasswordBidder1!",
            "organisation_name": "Old Credentials Corp",
            "role": "SEEKER",
        },
    )
    seeker_token = seeker_resp.json()["data"]["access_token"]
    seeker_headers = {"Authorization": f"Bearer {seeker_token}"}

    client.put(
        "/api/v1/profile",
        headers=seeker_headers,
        json={
            "annual_turnover": 3000000.0,  # Below $10M threshold
            "certifications": [
                {
                    "name": "ISO 45001",
                    "cert_number": "OLD-45001",
                    "valid_until": "2024-01-01",  # Expired
                    "accredited_by": "Legacy Body",
                }
            ],
        },
    )

    # Search tenders
    search_resp = client.get("/api/v1/tenders/search", headers=seeker_headers)
    assert search_resp.status_code == 200
    matches = search_resp.json()["data"]
    matched_tender = next(m for m in matches if m["tender"]["tender_id"] == tender_id)

    # Check that score is capped and discrepancies are clearly identified
    assert matched_tender["compliance_score"] <= 74.9
    assert matched_tender["has_mandatory_gaps"] is True
    assert len(matched_tender["conflicting_items"]) >= 1
