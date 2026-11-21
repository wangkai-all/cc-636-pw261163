import type {
  FieldSpec,
  Interpretation,
  Layer,
  MissingRule,
  OverrideAction,
  StateCounts,
  Variable,
} from "../types";

export const LAYERS: Layer[] = ["raw", "label", "analysis", "state"];

export const LAYER_TITLES: Record<Layer, string> = {
  raw: "原始值",
  label: "显示标签",
  analysis: "分析值",
  state: "缺失/有效性",
};

export const STATE_TITLES: Record<string, string> = {
  valid: "有效",
  system_missing: "系统缺失",
  user_missing: "用户定义缺失",
  extended_missing: "扩展缺失",
  unsupported: "不支持",
  invalid: "无效",
};

export const ACTION_TITLES: Record<OverrideAction, string> = {
  missing: "保持原义",
  valid: "恢复为有效值",
  set: "设为指定值",
  system: "转为系统缺失",
};

export const ACTION_HINTS: Record<OverrideAction, string> = {
  missing: "不改变缺失含义，仅用于核对影响范围。",
  valid: "把缺失码按原存储值重新当作有效值（扩展缺失码没有原值）。",
  set: "提供一个明确的数值/日期/文本作为分析值。",
  system: "分析值置空，缺失码仍保留在原始值与状态列。",
};

export function formatNumber(value: number, digits = 3): string {
  if (!Number.isFinite(value)) return "—";
  if (Number.isInteger(value)) return String(value);
  return Number(value.toFixed(digits)).toString();
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatTime(ts: number): string {
  if (!ts) return "—";
  const date = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

export function showValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return formatNumber(value, 6);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export function isEmptyCell(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

export function stateTone(state: string): "good" | "warn" | "bad" | "muted" | "info" {
  if (state.startsWith("valid")) return "good";
  if (state.startsWith("user_missing")) return "warn";
  if (state.startsWith("extended_missing")) return "info";
  if (state.startsWith("system_missing")) return "muted";
  return "bad";
}

export function stateLabel(state: string): string {
  const base = state.split("->")[0].split(":")[0];
  const suffix = state.split("->")[1];
  const title = STATE_TITLES[base] ?? base;
  if (state.startsWith("extended_missing:")) {
    const code = state.split(":")[1];
    return suffix ? `扩展缺失 ${code} → ${suffix}` : `扩展缺失 ${code}`;
  }
  return suffix ? `${title} → ${suffix}` : title;
}

export function totalCounts(counts: StateCounts): number {
  return Object.values(counts).reduce((sum, value) => sum + value, 0);
}

export function ruleTitle(rule: MissingRule): string {
  if (rule.kind === "system") return "系统缺失（空值）";
  if (rule.kind === "extended") return `扩展缺失码 ${rule.code ?? ""}`;
  if (rule.value_kind === "string") return `字符串取值 “${rule.code ?? ""}”`;
  if (rule.code !== null) return `离散码 ${rule.code}`;
  return `范围 ${showValue(rule.low)} … ${showValue(rule.high)}`;
}

export function ruleRange(rule: MissingRule): string {
  if (rule.kind === "extended") return rule.code ?? "";
  if (rule.value_kind === "string") return rule.code ?? "";
  if (rule.code !== null) return String(rule.code);
  return `${showValue(rule.low)} … ${showValue(rule.high)}`;
}

export function isTemporal(variable: Variable): boolean {
  return variable.time !== null;
}

export function defaultField(variable: Variable): FieldSpec {
  return {
    name: variable.name,
    layers: [...LAYERS],
    time_mode: "interpret",
    overrides: [],
  };
}

export function defaultFields(interpretation: Interpretation): FieldSpec[] {
  return interpretation.variables.map(defaultField);
}

export function shortHash(hash: string): string {
  return hash ? `${hash.slice(0, 12)}…` : "—";
}

export function countSummary(counts: StateCounts): string {
  const parts: string[] = [];
  if (counts.valid) parts.push(`有效 ${counts.valid}`);
  if (counts.system_missing) parts.push(`系统 ${counts.system_missing}`);
  if (counts.user_missing) parts.push(`用户 ${counts.user_missing}`);
  if (counts.extended_missing) parts.push(`扩展 ${counts.extended_missing}`);
  if (counts.unsupported) parts.push(`不支持 ${counts.unsupported}`);
  if (counts.invalid) parts.push(`无效 ${counts.invalid}`);
  return parts.join(" · ");
}

export function previewValuePlaceholder(variable: Variable): string {
  if (variable.time) {
    if (variable.time.kind === "date") return "2024-01-31";
    if (variable.time.kind === "datetime") return "2024-01-31T09:30:00";
    if (variable.time.kind === "month" || variable.time.kind === "quarter" || variable.time.kind === "half_year")
      return "2024-01-01";
    return "数值，例如 12";
  }
  return variable.storage_type === "string" ? "文本" : "数值";
}
