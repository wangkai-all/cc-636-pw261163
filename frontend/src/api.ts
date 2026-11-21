import type {
  ColumnCells,
  FormatInfo,
  PreviewResult,
  RecheckReport,
  ResultManifest,
  ResultRows,
  SampleInfo,
  Spec,
  UploadListItem,
  UploadSummary,
} from "./types";

const BASE = "/api";

interface ApiErrorBody {
  detail?: unknown;
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function describeDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          const loc = Array.isArray((item as { loc?: unknown }).loc)
            ? (item as { loc: unknown[] }).loc.join(".")
            : "";
          return `${loc ? `${loc}: ` : ""}${String((item as { msg: unknown }).msg)}`;
        }
        return JSON.stringify(item);
      })
      .join("；");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, init);
  } catch (error) {
    throw new ApiError(
      `无法连接后端服务（${error instanceof Error ? error.message : String(error)}）`,
      0,
    );
  }
  if (!response.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      body = null;
    }
    const message = describeDetail(body?.detail) || `请求失败（HTTP ${response.status}）`;
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as T;
}

function jsonInit(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  samples: () => request<{ samples: SampleInfo[] }>("/samples"),

  formats: () => request<{ formats: FormatInfo[] }>("/formats"),

  uploadFile: (file: File) => {
    const data = new FormData();
    data.append("file", file);
    return request<UploadSummary>("/uploads", { method: "POST", body: data });
  },

  uploadSample: (name: string) =>
    request<UploadSummary>(`/uploads/sample/${encodeURIComponent(name)}`, { method: "POST" }),

  getUpload: (uploadId: string) => request<UploadSummary>(`/uploads/${uploadId}`),

  listUploads: () => request<{ uploads: UploadListItem[] }>("/uploads"),

  columnCells: (uploadId: string, column: string, limit = 100, offset = 0) =>
    request<ColumnCells>(
      `/uploads/${uploadId}/cells?column=${encodeURIComponent(column)}&limit=${limit}&offset=${offset}`,
    ),

  preview: (uploadId: string, spec: Spec) =>
    request<PreviewResult>(`/uploads/${uploadId}/preview`, jsonInit(spec)),

  createResult: (uploadId: string, spec: Spec, format: string, previewToken: string) =>
    request<ResultManifest>(
      `/uploads/${uploadId}/results`,
      jsonInit({ spec, format, preview_token: previewToken }),
    ),

  getResult: (resultId: string) => request<ResultManifest>(`/results/${resultId}`),

  resultRows: (resultId: string, q: string, limit = 100, offset = 0) =>
    request<ResultRows>(
      `/results/${resultId}/rows?limit=${limit}&offset=${offset}${
        q ? `&q=${encodeURIComponent(q)}` : ""
      }`,
    ),

  addExport: (resultId: string, fmt: string) =>
    request<ResultManifest>(`/results/${resultId}/exports/${fmt}`, { method: "POST" }),

  verification: (resultId: string) =>
    request<{ verifications: ResultManifest["exports"][number]["verification"][] }>(
      `/results/${resultId}/verification`,
    ),

  recheck: (resultId: string) => request<RecheckReport>(`/results/${resultId}/recheck`),

  downloadUrl: (resultId: string, fmt?: string) =>
    `${BASE}/results/${resultId}/download${fmt ? `?fmt=${fmt}` : ""}`,
};
