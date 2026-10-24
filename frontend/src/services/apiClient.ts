import type {
  ApiResponse,
  AuditLogListResponse,
  AuthTokenResponse,
  AwardRequestPayload,
  AwardSimulationRequest,
  BidderComparisonRow,
  BidderProfile,
  ComplianceAnalysisResult,
  DocumentRole,
  DocumentUploadBatchResponse,
  ExportableReportData,
  HealthStatus,
  IssuerTenderSummary,
  PermitChecklistItem,
  PermitItemUpdateRequest,
  PermitReadinessResult,
  ProfileExtractionResponse,
  ReportExportRequest,
  TenderCreateRequest,
  TenderDraftExtractionResponse,
  TenderMatchSummary,
  TenderResponse,
  TenderSubmission,
  User,
  UserLoginRequest,
  UserRegisterRequest
} from "../types";

const RAW_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) || "";
export const API_BASE_URL = RAW_BASE_URL.replace(/\/+$/, "");
const TOKEN_KEY = "bid2work_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Ignore localStorage errors in private browsing
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Ignore localStorage errors
  }
}

function getAuthHeaders(hasJsonBody = true): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "application/json"
  };
  if (hasJsonBody) {
    headers["Content-Type"] = "application/json";
  }
  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

async function parseEnvelope<T>(response: Response): Promise<ApiResponse<T>> {
  const payload = (await response.json()) as ApiResponse<T>;
  if (!response.ok || !payload.success) {
    const errMsg =
      payload?.error?.message || `HTTP ${response.status}: Request failed`;
    throw new Error(errMsg);
  }
  return payload;
}

export const bid2WorkApi = {
  // Token Utilities
  getToken,
  setToken,
  clearToken,

  // Health
  async getHealth(): Promise<ApiResponse<HealthStatus>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/health`, {
      method: "GET",
      headers: { Accept: "application/json" }
    });
    return parseEnvelope<HealthStatus>(response);
  },

  // Authentication
  async register(req: UserRegisterRequest): Promise<ApiResponse<AuthTokenResponse>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(req)
    });
    const result = await parseEnvelope<AuthTokenResponse>(response);
    if (result.data?.access_token) {
      setToken(result.data.access_token);
    }
    return result;
  },

  async login(req: UserLoginRequest): Promise<ApiResponse<AuthTokenResponse>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(req)
    });
    const result = await parseEnvelope<AuthTokenResponse>(response);
    if (result.data?.access_token) {
      setToken(result.data.access_token);
    }
    return result;
  },

  async getMe(): Promise<ApiResponse<User>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
      method: "GET",
      headers: getAuthHeaders(false)
    });
    return parseEnvelope<User>(response);
  },

  // Bidder Profile
  async getProfile(): Promise<ApiResponse<BidderProfile>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/profile`, {
      method: "GET",
      headers: getAuthHeaders(false)
    });
    return parseEnvelope<BidderProfile>(response);
  },

  async updateProfile(profile: Partial<BidderProfile>): Promise<ApiResponse<BidderProfile>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/profile`, {
      method: "PUT",
      headers: getAuthHeaders(true),
      body: JSON.stringify(profile)
    });
    return parseEnvelope<BidderProfile>(response);
  },

  async uploadAndExtractProfile(file: File): Promise<ApiResponse<ProfileExtractionResponse>> {
    const formData = new FormData();
    formData.append("profile_file", file);
    const token = getToken();
    const headers: Record<string, string> = { Accept: "application/json" };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    const response = await fetch(`${API_BASE_URL}/api/v1/profile/upload-and-extract`, {
      method: "POST",
      headers,
      body: formData
    });
    return parseEnvelope<ProfileExtractionResponse>(response);
  },

  // Tenders (Publication & Issuer)
  async uploadAndExtractTender(file: File): Promise<ApiResponse<TenderDraftExtractionResponse>> {
    const formData = new FormData();
    formData.append("tender_file", file);
    const token = getToken();
    const headers: Record<string, string> = { Accept: "application/json" };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    const response = await fetch(`${API_BASE_URL}/api/v1/tenders/upload-and-extract`, {
      method: "POST",
      headers,
      body: formData
    });
    return parseEnvelope<TenderDraftExtractionResponse>(response);
  },

  async publishTender(tender: TenderCreateRequest): Promise<ApiResponse<TenderResponse>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/tenders`, {
      method: "POST",
      headers: getAuthHeaders(true),
      body: JSON.stringify(tender)
    });
    return parseEnvelope<TenderResponse>(response);
  },

  async listMyTenders(): Promise<ApiResponse<IssuerTenderSummary[]>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/tenders/my`, {
      method: "GET",
      headers: getAuthHeaders(false)
    });
    return parseEnvelope<IssuerTenderSummary[]>(response);
  },

  async getTenderSubmissions(tenderId: string): Promise<ApiResponse<BidderComparisonRow[]>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/tenders/${encodeURIComponent(tenderId)}/submissions`, {
      method: "GET",
      headers: getAuthHeaders(false)
    });
    return parseEnvelope<BidderComparisonRow[]>(response);
  },

  // Tenders (Discovery & Seeker)
  async searchTenders(params: {
    category?: string;
    maxThreshold?: number;
    location?: string;
    requiredCert?: string;
    page?: number;
    pageSize?: number;
  } = {}): Promise<ApiResponse<TenderMatchSummary[]>> {
    const q = new URLSearchParams();
    if (params.category) q.set("category", params.category);
    if (params.maxThreshold !== undefined) q.set("max_threshold", String(params.maxThreshold));
    if (params.location) q.set("location", params.location);
    if (params.requiredCert) q.set("required_cert", params.requiredCert);
    if (params.page) q.set("page", String(params.page));
    if (params.pageSize) q.set("page_size", String(params.pageSize));

    const response = await fetch(`${API_BASE_URL}/api/v1/tenders/search?${q.toString()}`, {
      method: "GET",
      headers: getAuthHeaders(false)
    });
    return parseEnvelope<TenderMatchSummary[]>(response);
  },

  async getTenderById(tenderId: string): Promise<ApiResponse<TenderResponse>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/tenders/${encodeURIComponent(tenderId)}`, {
      method: "GET",
      headers: getAuthHeaders(false)
    });
    return parseEnvelope<TenderResponse>(response);
  },

  async applyToTender(tenderId: string): Promise<ApiResponse<TenderSubmission>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/tenders/${encodeURIComponent(tenderId)}/apply`, {
      method: "POST",
      headers: getAuthHeaders(true)
    });
    return parseEnvelope<TenderSubmission>(response);
  },

  async listMySubmissions(): Promise<ApiResponse<TenderSubmission[]>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/tenders/submissions/my`, {
      method: "GET",
      headers: getAuthHeaders(false)
    });
    return parseEnvelope<TenderSubmission[]>(response);
  },

  // Document Analysis & Compliance (Legacy & Direct)
  async listAnalyses(limit = 20): Promise<ApiResponse<ComplianceAnalysisResult[]>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/analysis?limit=${limit}`, {
      method: "GET",
      headers: { Accept: "application/json" }
    });
    return parseEnvelope<ComplianceAnalysisResult[]>(response);
  },

  async getAnalysis(analysisId: string): Promise<ApiResponse<ComplianceAnalysisResult>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/analysis/${encodeURIComponent(analysisId)}`, {
      method: "GET",
      headers: { Accept: "application/json" }
    });
    return parseEnvelope<ComplianceAnalysisResult>(response);
  },

  async uploadDocuments(
    files: File[],
    roles?: DocumentRole[]
  ): Promise<ApiResponse<DocumentUploadBatchResponse>> {
    const formData = new FormData();
    files.forEach((f) => formData.append("files", f));
    if (roles && roles.length === files.length) {
      roles.forEach((r) => formData.append("roles", r));
    }
    const response = await fetch(`${API_BASE_URL}/api/v1/documents/upload`, {
      method: "POST",
      body: formData
    });
    return parseEnvelope<DocumentUploadBatchResponse>(response);
  },

  async analyzeCompliance(
    tenderFile: File,
    bidderFiles: File[]
  ): Promise<ApiResponse<ComplianceAnalysisResult>> {
    const formData = new FormData();
    formData.append("tender_file", tenderFile);
    bidderFiles.forEach((bf) => formData.append("bidder_files", bf));

    const response = await fetch(`${API_BASE_URL}/api/v1/compliance/analyze`, {
      method: "POST",
      body: formData
    });
    return parseEnvelope<ComplianceAnalysisResult>(response);
  },

  async createAnalysisFromIds(
    tenderDocumentId: string,
    bidderDocumentIds: string[]
  ): Promise<ApiResponse<ComplianceAnalysisResult>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/analysis`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        tender_document_id: tenderDocumentId,
        bidder_document_ids: bidderDocumentIds
      })
    });
    return parseEnvelope<ComplianceAnalysisResult>(response);
  },

  // Work Permit Readiness & Award Simulation
  async simulateAward(
    request: AwardSimulationRequest
  ): Promise<ApiResponse<PermitReadinessResult>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/permits/simulate-award`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request)
    });
    return parseEnvelope<PermitReadinessResult>(response);
  },

  async simulateAwardForAnalysis(
    analysisId: string,
    payload: AwardRequestPayload = {}
  ): Promise<ApiResponse<PermitReadinessResult>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/analysis/${encodeURIComponent(analysisId)}/award`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        contract_reference: payload.contract_reference || "CTR-SIM-001",
        planned_start_date: payload.planned_start_date || null,
        site_location: payload.site_location || "Primary Operational Site"
      })
    });
    return parseEnvelope<PermitReadinessResult>(response);
  },

  async getPermitReadiness(
    analysisId: string,
    autoSimulate = false
  ): Promise<ApiResponse<PermitReadinessResult | null>> {
    const response = await fetch(
      `${API_BASE_URL}/api/v1/analysis/${encodeURIComponent(analysisId)}/permit-readiness?auto_simulate=${autoSimulate}`,
      {
        method: "GET",
        headers: { Accept: "application/json" }
      }
    );
    return parseEnvelope<PermitReadinessResult | null>(response);
  },

  async updatePermitItem(
    itemId: string,
    update: PermitItemUpdateRequest
  ): Promise<ApiResponse<PermitChecklistItem>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/permit-items/${encodeURIComponent(itemId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(update)
    });
    return parseEnvelope<PermitChecklistItem>(response);
  },

  async downloadReportCsv(analysisId: string): Promise<string> {
    const response = await fetch(
      `${API_BASE_URL}/api/v1/analysis/${encodeURIComponent(analysisId)}/report`,
      {
        method: "GET",
        headers: { Accept: "text/csv" }
      }
    );
    if (!response.ok) {
      let errMsg = `Failed to download CSV: HTTP ${response.status}`;
      try {
        const errJson = await response.json();
        errMsg = errJson?.error?.message || errMsg;
      } catch {
        // Fall back to HTTP status message
      }
      throw new Error(errMsg);
    }
    const csvText = await response.text();
    const blob = new Blob([csvText], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `compliance_report_${analysisId.toLowerCase()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    return csvText;
  },

  async listAuditEvents(
    analysisId?: string,
    limit = 50
  ): Promise<ApiResponse<AuditLogListResponse>> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (analysisId) {
      params.set("analysis_id", analysisId);
    }
    const response = await fetch(`${API_BASE_URL}/api/v1/audit/events?${params.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" }
    });
    return parseEnvelope<AuditLogListResponse>(response);
  },

  async exportReport(
    request: ReportExportRequest
  ): Promise<ApiResponse<ExportableReportData>> {
    const response = await fetch(`${API_BASE_URL}/api/v1/reports/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request)
    });
    return parseEnvelope<ExportableReportData>(response);
  }
};
