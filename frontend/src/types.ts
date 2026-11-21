export type Layer = "raw" | "label" | "analysis" | "state";
export type TimeMode = "interpret" | "numeric";
export type OverrideAction = "missing" | "valid" | "set" | "system";

export interface ValueLabel {
  value: string;
  numeric: number | null;
  label: string;
}

export interface MissingRule {
  id: string;
  kind: "user" | "extended" | "system";
  code: string | null;
  low: unknown;
  high: unknown;
  label: string | null;
  source: string;
  description: string;
  value_kind: "numeric" | "string";
}

export interface TimeSpec {
  supported: boolean;
  kind: string;
  source_format: string;
  unit: string | null;
  epoch: string | null;
  reason: string | null;
  partial_display: boolean;
  leap_seconds: boolean;
  notes: string[];
}

export interface StateCounts {
  valid: number;
  system_missing: number;
  user_missing: number;
  extended_missing: number;
  unsupported: number;
  invalid: number;
  [key: string]: number;
}

export interface SampleCell {
  row: number;
  raw: unknown;
  label: unknown;
  analysis: unknown;
  state: string;
  rule: string | null;
  ext_code: string | null;
}

export interface Variable {
  name: string;
  index: number;
  label: string | null;
  storage_type: string;
  storage_width: number | null;
  display_width: number | null;
  source_format: string | null;
  format_base: string | null;
  measure: string | null;
  encoding: string | null;
  value_labels: ValueLabel[];
  missing_rules: MissingRule[];
  time: TimeSpec | null;
  classification: string;
  notes: string[];
  is_strl: boolean;
  observed_max_bytes: number;
  observed_max_chars: number;
  counts: StateCounts;
  sample_cells: SampleCell[];
}

export interface Interpretation {
  file_type: string;
  row_count: number;
  column_count: number;
  encoding: string | null;
  file_label: string | null;
  file_format: string;
  variables: Variable[];
  notes: string[];
  label_conflicts: { value: string; meanings: { label: string; variables: string[] }[] }[];
}

export interface UploadRecord {
  upload_id: string;
  filename: string;
  original_name: string;
  file_type: string;
  size_bytes: number;
  sha256: string;
  created_at: number;
}

export interface UploadSummary {
  upload: UploadRecord;
  interpretation: Interpretation;
  results: ResultManifest[];
}

export interface SampleInfo {
  filename: string;
  size_bytes: number;
  file_type: string;
}

export interface FormatInfo {
  id: string;
  title: string;
  notes: string;
  limits: string[];
}

export interface FieldSpec {
  name: string;
  layers: Layer[];
  overrides: { rule_id: string; action: OverrideAction; value?: unknown; label?: string | null }[];
  time_mode: TimeMode;
}

export interface Spec {
  fields: FieldSpec[];
}

export interface Stats {
  n: number;
  mean: number | null;
  std: number | null;
  min: number | null;
  max: number | null;
  zeros: number;
}

export interface RulePreview {
  rule_id: string;
  action: OverrideAction;
  value: unknown;
  label: string | null;
  affected_rows: number[];
  affected_count: number;
  rows_truncated: boolean;
  before: Stats;
  after: Stats;
  states_before: string[];
  raw_values: string[];
}

export interface FieldPreview {
  name: string;
  title: string;
  classification: string;
  storage_type: string;
  source_format: string | null;
  time: TimeSpec | null;
  layers: Layer[];
  time_mode: TimeMode;
  counts: StateCounts;
  rules: MissingRule[];
  overrides: RulePreview[];
  warnings: string[];
}

export interface PreviewScope {
  fields: string[];
  rows: number;
  output_columns: string[];
  layer_count: number;
  export_formats: string[];
}

export interface PreviewResult {
  preview_token: string;
  canonical_spec: { fields: FieldSpec[] };
  fields: FieldPreview[];
  scope: PreviewScope;
  notes: string[];
  warnings: string[];
  confirmation_required: boolean;
  original_immutable: boolean;
  formats: FormatInfo[];
  dataset: {
    row_count: number;
    column_count: number;
    file_type: string;
    file_format: string;
    encoding: string | null;
  };
}

export interface VerificationReport {
  format: string;
  ok: boolean;
  value_mismatches: unknown[];
  label_mismatches: unknown[];
  missing_mismatches: unknown[];
  column_mismatches: unknown[];
  notes: string[];
  checked_columns: number;
  checked_cells: number;
  error?: string;
}

export interface ExportInfo {
  id: string;
  filename: string;
  size_bytes: number;
  notes: string[];
  limits: string[];
  verification: VerificationReport;
  sidecar?: string;
}

export interface OverrideApplied {
  field: string;
  rule_id: string;
  action: OverrideAction;
  value: unknown;
  label: string | null;
  affected_rows: number[];
  affected_count: number;
}

export interface CompiledColumnMeta {
  name: string;
  source: string;
  layer: Layer;
  dtype: "number" | "string";
  title: string;
  description: string;
  value_labels: ValueLabel[];
  missing_rules: MissingRule[];
  time: TimeSpec | null;
  notes: string[];
}

export interface ResultManifest {
  result_id: string;
  upload_id: string;
  upload_sha256: string;
  created_at: number;
  format: string;
  format_title: string;
  spec: Spec;
  preview_token: string;
  row_count: number;
  columns: CompiledColumnMeta[];
  overrides: OverrideApplied[];
  notes: string[];
  scope: PreviewScope;
  preview?: { fields: FieldPreview[]; warnings: string[] };
  exports: ExportInfo[];
  original: {
    filename: string;
    original_name: string;
    sha256: string;
    unchanged: boolean;
  };
  error?: string;
}

export interface ResultRows {
  schema: CompiledColumnMeta[];
  rows: Record<string, unknown>[];
  total: number;
  offset: number;
  limit: number;
  overrides: OverrideApplied[];
  manifest: Pick<ResultManifest, "result_id" | "created_at" | "format" | "row_count" | "notes">;
}

export interface RecheckReport {
  result_id: string;
  reports: (VerificationReport & { filename?: string })[];
}

export interface CellLayerRow {
  row_id: number;
  raw: unknown;
  label: unknown;
  analysis: unknown;
  state: string;
  rule: string | null;
  ext_code: string | null;
}

export interface ColumnCells {
  column: Variable;
  rows: CellLayerRow[];
  total: number;
  offset: number;
  limit: number;
}

export interface UploadListItem extends UploadRecord {
  result_count: number;
}
