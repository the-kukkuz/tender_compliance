/**
 * Shared TypeScript data contracts for Bid2Work AI.
 * Mirrors backend Pydantic schemas in backend/app/schemas/.
 */

export type ProcessingState =
  | "IDLE"
  | "UPLOADING"
  | "EXTRACTING"
  | "ANALYZING"
  | "COMPLETED"
  | "FAILED";

export type ErrorCode =
  | "VALIDATION_ERROR"
  | "UPLOAD_LIMIT_EXCEEDED"
  | "INVALID_FILE_TYPE"
  | "PDF_EXTRACTION_ERROR"
  | "LLM_PROVIDER_ERROR"
  | "NOT_FOUND"
  | "INTERNAL_ERROR";

export interface ApiErrorDetail {
  field?: string | null;
  message: string;
  code?: string | null;
}

export interface ApiError {
  code: ErrorCode;
  message: string;
  details: ApiErrorDetail[];
  request_id: string;
  timestamp: string;
}

export interface ApiMeta {
  request_id: string;
  timestamp: string;
  processing_state: ProcessingState;
  version: string;
  warnings: string[];
}

export interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: ApiError | null;
  meta: ApiMeta;
}

export interface HealthStatus {
  status: string;
  service: string;
  version: string;
  environment: string;
  llm_configured: boolean;
  llm_provider: string;
  llm_model: string;
  database_ready: boolean;
  max_upload_size_mb: number;
  max_bidder_files: number;
  timestamp: string;
}

/* -------------------------------------------------------------------------- */
/* 1. Document Metadata & Extraction Results                                  */
/* -------------------------------------------------------------------------- */

export type DocumentRole = "TENDER" | "BIDDER_SUPPORTING" | "SAFETY_PERMIT";

export interface ExtractedPage {
  page_number: number;
  text: string;
  char_count: number;
  word_count: number;
}

export interface DocumentMetadata {
  document_id: string;
  filename: string;
  role: DocumentRole;
  file_size_bytes: number;
  page_count: number;
  content_type: string;
  uploaded_at: string;
  sha256_hash?: string | null;
}

export interface DocumentExtractionResult {
  metadata: DocumentMetadata;
  pages: ExtractedPage[];
  total_chars: number;
  is_text_based: boolean;
  extraction_warnings: string[];
}

/* -------------------------------------------------------------------------- */
/* 2. Tender Requirements, Bidder Evidence & Compliance Analysis              */
/* -------------------------------------------------------------------------- */

export type RequirementCategory =
  | "ELIGIBILITY"
  | "EXPERIENCE"
  | "FINANCIAL"
  | "CERTIFICATION"
  | "DEADLINE"
  | "SAFETY";

export type RequirementPriority =
  | "MANDATORY"
  | "RECOMMENDED"
  | "INFORMATIONAL";

export type ComplianceStatus =
  | "Evidence Found"
  | "Missing"
  | "Conflicting"
  | "Needs Review";

export interface SourceReference {
  filename: string;
  page_number: number;
  excerpt: string;
  section_hint?: string | null;
}

export interface TenderRequirement {
  requirement_id: string;
  category: RequirementCategory;
  title: string;
  description: string;
  priority: RequirementPriority;
  source: SourceReference;
  threshold_or_criteria?: string | null;
  requires_permit_carryover: boolean;
}

export interface BidderEvidence {
  evidence_id: string;
  requirement_id?: string | null;
  source_document_id: string;
  filename: string;
  page_number: number;
  excerpt: string;
  extracted_value?: string | null;
  valid_until?: string | null;
  confidence: number;
}

export interface RequirementAssessment {
  requirement_id: string;
  requirement: TenderRequirement;
  status: ComplianceStatus;
  matched_evidence: BidderEvidence[];
  rationale: string;
  discrepancies: string[];
  recommended_action?: string | null;
  reviewed_at: string;
}

export interface ComplianceSummaryMetrics {
  total_requirements: number;
  evidence_found_count: number;
  missing_count: number;
  conflicting_count: number;
  needs_review_count: number;
  mandatory_gap_count: number;
  safety_requirements_count: number;
  overall_readiness_score: number;
  by_category: Record<string, number>;
}

export interface ComplianceAnalysisResult {
  analysis_id: string;
  created_at: string;
  processing_state: ProcessingState;
  tender_document: DocumentMetadata;
  bidder_documents: DocumentMetadata[];
  requirements: TenderRequirement[];
  assessments: RequirementAssessment[];
  summary: ComplianceSummaryMetrics;
  disclaimer: string;
}

/* -------------------------------------------------------------------------- */
/* 3. Work-Permit Readiness Checklist & Award Simulation                      */
/* -------------------------------------------------------------------------- */

export type PermitItemStatus =
  | "Verified"
  | "Pending Evidence"
  | "Expired"
  | "Conflicting"
  | "Needs Review";

export type PermitCategory =
  | "HSE_POLICY"
  | "WORKER_QUALIFICATION"
  | "EQUIPMENT_CERTIFICATION"
  | "SITE_APPROVAL"
  | "INSURANCE_LIABILITY"
  | "EMERGENCY_RESPONSE"
  | "HAZARD_CONTROL";

export type HumanReviewStatus =
  | "incomplete"
  | "requires_verification"
  | "ready_for_review"
  | "approved_by_reviewer";

export interface PermitChecklistItem {
  item_id: string;
  source_requirement_id?: string | null;
  category: PermitCategory;
  title: string;
  description: string;
  status: PermitItemStatus;
  required_document_type: string;
  supporting_evidence: BidderEvidence[];
  approval_authority?: string | null;
  qualification_reference?: string | null;
  expiry_date?: string | null;
  is_expired: boolean;
  unresolved_conditions: string[];
  remediation_steps: string[];
  review_status: HumanReviewStatus;
  reviewer_name?: string | null;
  reviewer_role?: string | null;
  reviewer_notes?: string | null;
  reviewed_at?: string | null;
  attached_evidence_ids?: string[];
}

export interface PermitItemUpdateRequest {
  review_status?: HumanReviewStatus;
  reviewer_name?: string | null;
  reviewer_role?: string | null;
  reviewer_notes?: string | null;
  is_authorized_reviewer?: boolean | null;
  attached_evidence_ids?: string[] | null;
}

export interface AwardRequestPayload {
  contract_reference?: string;
  planned_start_date?: string | null;
  site_location?: string;
}

export interface DocumentUploadBatchResponse {
  uploaded_documents: DocumentMetadata[];
  tender_document?: DocumentMetadata | null;
  bidder_documents: DocumentMetadata[];
  total_files: number;
  warnings: string[];
}

export interface AwardSimulationRequest {
  analysis_id: string;
  contract_reference?: string | null;
  planned_start_date?: string | null;
  site_location?: string | null;
  tender_requirements: TenderRequirement[];
  assessments: RequirementAssessment[];
}

export interface PermitReadinessSummary {
  total_items: number;
  verified_count: number;
  pending_count: number;
  expired_count: number;
  conflicting_count: number;
  needs_review_count: number;
  readiness_percentage: number;
  blocking_conditions_count: number;
}

export interface PermitReadinessResult {
  permit_pack_id: string;
  analysis_id: string;
  contract_reference?: string | null;
  simulated_award_date: string;
  planned_start_date?: string | null;
  site_location?: string | null;
  processing_state: ProcessingState;
  checklist_items: PermitChecklistItem[];
  summary: PermitReadinessSummary;
  unresolved_conditions: string[];
  disclaimer: string;
}

/* -------------------------------------------------------------------------- */
/* 4. Audit Events & Exportable Reports                                       */
/* -------------------------------------------------------------------------- */

export type AuditEventType =
  | "DOCUMENTS_UPLOADED"
  | "PDF_EXTRACTED"
  | "REQUIREMENTS_IDENTIFIED"
  | "COMPLIANCE_EVALUATED"
  | "CONTRACT_AWARD_SIMULATED"
  | "PERMIT_CHECKLIST_GENERATED"
  | "REPORT_EXPORTED"
  | "ANALYSIS_ERROR";

export type AuditActorType = "SYSTEM" | "USER";

export interface AuditEvent {
  event_id: string;
  analysis_id?: string | null;
  event_type: AuditEventType;
  actor: AuditActorType;
  summary: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface AuditLogListResponse {
  events: AuditEvent[];
  total: number;
}

export type ReportFormat = "JSON" | "MARKDOWN" | "HTML";

export interface ReportExportRequest {
  analysis_id: string;
  format: ReportFormat;
  include_permit_checklist: boolean;
  include_audit_trail: boolean;
  compliance_result: ComplianceAnalysisResult;
  permit_result?: PermitReadinessResult | null;
}

export interface ExportableReportData {
  report_id: string;
  analysis_id: string;
  generated_at: string;
  format: ReportFormat;
  title: string;
  executive_summary: string;
  compliance_analysis: ComplianceAnalysisResult;
  permit_readiness?: PermitReadinessResult | null;
  audit_trail: AuditEvent[];
  content: string;
  filename: string;
  mime_type: string;
  disclaimer: string;
}

/* -------------------------------------------------------------------------- */
/* 5. User Roles, Authentication, and Multi-Mode                              */
/* -------------------------------------------------------------------------- */

export type UserRole = "SEEKER" | "ISSUER" | "BOTH";

export interface User {
  user_id: string;
  email: string;
  name: string;
  organisation_name: string;
  role: UserRole;
  created_at: string;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface UserRegisterRequest {
  email: string;
  password: string;
  name: string;
  organisation_name: string;
  role: UserRole;
}

export interface UserLoginRequest {
  email: string;
  password: string;
}

/* -------------------------------------------------------------------------- */
/* 6. Bidder Profile                                                         */
/* -------------------------------------------------------------------------- */

export interface BusinessIdentifier {
  id_type: string;
  value: string;
}

export interface CertificationItem {
  name: string;
  cert_number?: string | null;
  valid_until?: string | null;
  accredited_by?: string | null;
}

export interface PastProjectItem {
  title: string;
  client: string;
  value?: number | null;
  currency?: string | null;
  completion_year?: number | null;
}

export interface BidderProfile {
  profile_id: string;
  user_id: string;
  organisation_name: string;
  business_identifiers: BusinessIdentifier[];
  categories: string[];
  experience_years: number;
  experience_summary: string;
  past_projects: PastProjectItem[];
  certifications: CertificationItem[];
  annual_turnover: number;
  currency: string;
  financial_audited: boolean;
  locations: string[];
  safety_manual_approved: boolean;
  other_qualifications: string[];
  supporting_document_ids: string[];
  is_verified: boolean;
  updated_at: string;
}

export interface ProfileExtractionResponse {
  document_id: string;
  filename: string;
  extracted_profile: BidderProfile;
  review_notes: string[];
}

/* -------------------------------------------------------------------------- */
/* 7. Tenders, Matching, and Bidder Comparison Matrix                         */
/* -------------------------------------------------------------------------- */

export type TenderStatus = "DRAFT" | "PUBLISHED" | "CLOSED";

export interface TenderCreateRequest {
  title: string;
  description: string;
  category: string;
  submission_deadline: string;
  financial_threshold?: number | null;
  financial_currency?: string;
  geographic_restrictions?: string[];
  required_certifications?: string[];
  min_experience_years?: number;
  safety_requirements?: string[];
  required_documents?: string[];
  document_id: string;
  extracted_requirements: TenderRequirement[];
}

export interface TenderResponse {
  tender_id: string;
  issuer_user_id: string;
  issuer_organisation: string;
  title: string;
  description: string;
  category: string;
  status: TenderStatus;
  submission_deadline: string;
  financial_threshold?: number | null;
  financial_currency?: string;
  geographic_restrictions: string[];
  required_certifications: string[];
  min_experience_years: number;
  safety_requirements: string[];
  required_documents: string[];
  document_id: string;
  extracted_requirements: TenderRequirement[];
  requirement_version: number;
  created_at: string;
  updated_at: string;
}

export interface TenderDraftExtractionResponse {
  document_id: string;
  filename: string;
  extracted_tender: TenderCreateRequest;
  review_notes: string[];
}

export interface TenderMatchSummary {
  tender: TenderResponse;
  compliance_score: number;
  has_mandatory_gaps: boolean;
  mandatory_satisfied_count: number;
  mandatory_total_count: number;
  optional_satisfied_count: number;
  optional_total_count: number;
  missing_mandatory_titles: string[];
  conflicting_items: string[];
  supporting_evidence_count: number;
  match_explanation: string;
  days_remaining: number;
  next_action: string;
  sorting_rule: string;
  disclaimer: string;
  requirement_assessments?: RequirementAssessment[];
}

export interface TenderSubmission {
  submission_id: string;
  tender_id: string;
  requirement_version: number;
  bidder_user_id: string;
  bidder_organisation: string;
  profile_snapshot: BidderProfile;
  bidder_document_ids: string[];
  compliance_score: number;
  status: string;
  assessment: RequirementAssessment[];
  summary: ComplianceSummaryMetrics;
  submitted_at: string;
  updated_at: string;
}

export interface IssuerTenderSummary {
  tender: TenderResponse;
  submission_count: number;
  compliant_submissions_count: number;
  submissions_with_gaps_count: number;
  avg_compliance_score: number;
}

export interface BidderComparisonRow {
  submission_id: string;
  tender_id: string;
  requirement_version: number;
  bidder_organisation: string;
  compliance_score: number;
  mandatory_satisfied: string;
  missing_evidence: string[];
  conflicting_evidence: string[];
  submission_date: string;
  status: string;
  assessment: RequirementAssessment[];
}

