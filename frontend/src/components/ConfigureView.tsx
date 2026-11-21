import { useMemo, useState } from "react";
import type {
  FieldSpec,
  FormatInfo,
  Interpretation,
  Layer,
  MissingRule,
  OverrideAction,
  PreviewResult,
  Variable,
} from "../types";
import {
  ACTION_HINTS,
  ACTION_TITLES,
  countSummary,
  formatNumber,
  LAYERS,
  LAYER_TITLES,
  previewValuePlaceholder,
  ruleTitle,
  showValue,
  stateLabel,
  stateTone,
} from "../lib/format";
import { Badge, Callout, Empty, Panel, Spinner, Stat } from "./ui";

interface Props {
  interpretation: Interpretation;
  fields: FieldSpec[];
  onChange: (fields: FieldSpec[]) => void;
  preview: PreviewResult | null;
  previewing: boolean;
  previewError: string | null;
  formats: FormatInfo[];
  onPreview: () => void;
  onConfirm: (format: string) => void;
  creating: boolean;
  createError: string | null;
  onBack: () => void;
}

const STATE_GROUPS: { state: string; title: string }[] = [
  { state: "user_missing", title: "用户定义缺失" },
  { state: "extended_missing", title: "Stata 扩展缺失码" },
  { state: "system_missing", title: "系统缺失" },
  { state: "unsupported", title: "不支持的格式" },
];

const SYSTEM_RULE: MissingRule = {
  id: "system",
  kind: "system",
  code: null,
  low: null,
  high: null,
  label: null,
  source: "system",
  description: "系统缺失（空白数值 / 空字符串）",
  value_kind: "numeric",
};

function actionsFor(rule: MissingRule): OverrideAction[] {
  // "missing" is always offered by the leading static option.
  if (rule.kind === "system") {
    return ["set"];
  }
  if (rule.kind === "extended") {
    return ["set", "system"];
  }
  return ["valid", "set", "system"];
}

function findOverride(field: FieldSpec, ruleId: string) {
  return field.overrides.find((item) => item.rule_id === ruleId);
}

function StatsPair({ before, after }: { before: PreviewResult["fields"][number]["overrides"][number]["before"]; after: typeof before }) {
  const delta = (left: number | null, right: number | null) => {
    if (left === null || right === null) return null;
    const diff = right - left;
    return diff === 0 ? null : diff;
  };
  const meanDelta = delta(before.mean, after.mean);
  return (
    <div className="stats-pair">
      <div className="stats-col">
        <span className="stats-heading">转换前（当前分析值）</span>
        <div className="stats-grid">
          <Stat label="n" value={before.n} />
          <Stat label="均值" value={before.mean === null ? "—" : formatNumber(before.mean)} />
          <Stat label="标准差" value={before.std === null ? "—" : formatNumber(before.std)} />
          <Stat label="最小/最大" value={`${before.min === null ? "—" : formatNumber(before.min)} / ${before.max === null ? "—" : formatNumber(before.max)}`} />
          <Stat label="零值" value={before.zeros} />
        </div>
      </div>
      <div className="stats-arrow" aria-hidden="true">
        →
      </div>
      <div className="stats-col">
        <span className="stats-heading">
          转换后（试算）
          {meanDelta !== null ? (
            <Badge tone={meanDelta > 0 ? "info" : "warn"}>
              均值 {meanDelta > 0 ? "+" : ""}
              {formatNumber(meanDelta)}
            </Badge>
          ) : null}
        </span>
        <div className="stats-grid">
          <Stat label="n" value={after.n} />
          <Stat label="均值" value={after.mean === null ? "—" : formatNumber(after.mean)} />
          <Stat label="标准差" value={after.std === null ? "—" : formatNumber(after.std)} />
          <Stat label="最小/最大" value={`${after.min === null ? "—" : formatNumber(after.min)} / ${after.max === null ? "—" : formatNumber(after.max)}`} />
          <Stat label="零值" value={after.zeros} />
        </div>
      </div>
    </div>
  );
}

export function ConfigureView(props: Props) {
  const {
    interpretation,
    fields,
    onChange,
    preview,
    previewing,
    previewError,
    formats,
    onPreview,
    onConfirm,
    creating,
    createError,
    onBack,
  } = props;

  const variables = useMemo(
    () => new Map(interpretation.variables.map((variable) => [variable.name, variable])),
    [interpretation],
  );
  const [activeName, setActiveName] = useState<string | null>(
    () =>
      interpretation.variables.find((variable) =>
        variable.missing_rules.some((rule) => rule.kind !== "system"),
      )?.name ??
      interpretation.variables[0]?.name ??
      null,
  );
  const [format, setFormat] = useState<string>(formats[0]?.id ?? "csv");
  const [acknowledged, setAcknowledged] = useState(false);

  const activeField = fields.find((field) => field.name === activeName) ?? null;
  const activeVariable = activeName ? variables.get(activeName) ?? null : null;

  const selectedNames = new Set(fields.map((field) => field.name));

  const updateField = (name: string, patch: (field: FieldSpec) => FieldSpec) => {
    onChange(fields.map((field) => (field.name === name ? patch(field) : field)));
    setAcknowledged(false);
  };

  const toggleField = (variable: Variable) => {
    if (selectedNames.has(variable.name)) {
      onChange(fields.filter((field) => field.name !== variable.name));
      if (activeName === variable.name) {
        setActiveName(fields.find((field) => field.name !== variable.name)?.name ?? null);
      }
    } else {
      const next: FieldSpec = {
        name: variable.name,
        layers: [...LAYERS],
        time_mode: "interpret",
        overrides: [],
      };
      onChange([...fields, next]);
      setActiveName(variable.name);
    }
    setAcknowledged(false);
  };

  const toggleLayer = (layer: Layer) => {
    if (!activeField) return;
    const has = activeField.layers.includes(layer);
    if (has && activeField.layers.length === 1) return;
    updateField(activeField.name, (field) => ({
      ...field,
      layers: has ? field.layers.filter((item) => item !== layer) : [...field.layers, layer],
    }));
  };

  const setOverride = (rule: MissingRule, action: OverrideAction | null) => {
    if (!activeField) return;
    updateField(activeField.name, (field) => {
      const others = field.overrides.filter((item) => item.rule_id !== rule.id);
      if (action === null) return { ...field, overrides: others };
      const existing = findOverride(field, rule.id);
      return {
        ...field,
        overrides: [
          ...others,
          {
            rule_id: rule.id,
            action,
            value: existing?.value ?? defaultOverrideValue(rule, action, activeVariable),
            label: existing?.label ?? null,
          },
        ],
      };
    });
  };

  const setOverrideValue = (rule: MissingRule, value: string) => {
    if (!activeField) return;
    updateField(activeField.name, (field) => ({
      ...field,
      overrides: field.overrides.map((item) =>
        item.rule_id === rule.id ? { ...item, value } : item,
      ),
    }));
  };

  const ruleGroups = activeVariable
    ? STATE_GROUPS.map((group) => {
        const declared = activeVariable.missing_rules.filter((rule) =>
          group.state === "extended_missing"
            ? rule.kind === "extended"
            : group.state === "user_missing"
              ? rule.kind === "user"
              : rule.kind === "system",
        );
        // System missing has no metadata rule; expose it so an explicit value
        // can be supplied for blank cells.
        if (group.state === "system_missing" && declared.length === 0) {
          return { ...group, rules: [SYSTEM_RULE], counts: activeVariable.counts.system_missing ?? 0 };
        }
        return {
          ...group,
          rules: declared,
          counts: activeVariable.counts[group.state] ?? 0,
        };
      }).filter((group) => group.counts > 0 && group.rules.length > 0)
    : [];

  const specKey = canonicalKey(fields);
  const previewFresh = preview !== null && canonicalKey(preview.canonical_spec.fields) === specKey;

  const overrideCount = fields.reduce((sum, field) => sum + field.overrides.length, 0);
  const affectedTotal = (preview?.fields ?? []).reduce(
    (sum, field) => sum + field.overrides.reduce((inner, rule) => inner + rule.affected_count, 0),
    0,
  );

  return (
    <div className="configure">
      <div className="configure-head">
        <div>
          <span className="eyebrow">第 2 步</span>
          <h1>选择字段与转换方式</h1>
          <p className="muted">
            先选字段与要保留的层，再决定是否把某个缺失码当作有效值试算。任何改动都只影响新结果。
          </p>
        </div>
        <button type="button" className="btn btn-ghost" onClick={onBack}>
          返回变量定义
        </button>
      </div>

      <div className="configure-grid">
        <aside className="field-picker">
          <div className="rail-head">
            <h2>字段</h2>
            <span className="muted small">
              已选 {fields.length} / {interpretation.variables.length}
            </span>
          </div>
          <ul>
            {interpretation.variables.map((variable) => {
              const selected = selectedNames.has(variable.name);
              return (
                <li key={variable.name}>
                  <div className={`field-row ${variable.name === activeName ? "is-active" : ""}`}>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={() => toggleField(variable)}
                        aria-label={`选择字段 ${variable.name}`}
                      />
                    </label>
                    <button
                      type="button"
                      className="field-select"
                      onClick={() => setActiveName(variable.name)}
                    >
                      <span className="variable-name">
                        <code>{variable.name}</code>
                        {variable.classification === "unsupported" ? (
                          <Badge tone="bad">不支持</Badge>
                        ) : null}
                        {variable.time ? <Badge tone="info">{variable.time.kind}</Badge> : null}
                      </span>
                      <span className="variable-label">{variable.label ?? "无变量标签"}</span>
                      <span className="variable-counts">{countSummary(variable.counts)}</span>
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
          <p className="muted small rail-foot">
            字段的取值标签与缺失规则只属于该字段；同一编码在不同字段不会互相替换。
          </p>
        </aside>

        <div className="field-editor">
          {activeVariable && activeField ? (
            <Panel
              title={
                <span className="title-with-badge">
                  <code>{activeVariable.name}</code>
                  <span className="variable-title-text">{activeVariable.label ?? ""}</span>
                </span>
              }
              subtitle={`${activeVariable.storage_type}${
                activeVariable.storage_width ? `/${activeVariable.storage_width}` : ""
              } · ${activeVariable.source_format ?? "无格式"} · ${countSummary(activeVariable.counts)}`}
            >
              <div className="editor-section">
                <h4>保留的层</h4>
                <div className="layer-toggles">
                  {LAYERS.map((layer) => {
                    const enabled = activeField.layers.includes(layer);
                    const last = enabled && activeField.layers.length === 1;
                    return (
                      <label
                        key={layer}
                        className={`toggle-card ${enabled ? "is-on" : ""} ${last ? "is-locked" : ""}`}
                        title={last ? "至少保留一层" : undefined}
                      >
                        <input
                          type="checkbox"
                          checked={enabled}
                          disabled={last}
                          onChange={() => toggleLayer(layer)}
                        />
                        <span className="toggle-title">{LAYER_TITLES[layer]}</span>
                        <span className="toggle-hint">{LAYER_HINTS[layer]}</span>
                      </label>
                    );
                  })}
                </div>
              </div>

              {activeVariable.time ? (
                <div className="editor-section">
                  <h4>日期/时间处理</h4>
                  <div className="radio-row">
                    <label className={`radio-card ${activeField.time_mode === "interpret" ? "is-on" : ""}`}>
                      <input
                        type="radio"
                        name={`time-${activeVariable.name}`}
                        checked={activeField.time_mode === "interpret"}
                        onChange={() =>
                          updateField(activeVariable.name, (field) => ({
                            ...field,
                            time_mode: "interpret",
                          }))
                        }
                      />
                      <span className="toggle-title">按源格式解释</span>
                      <span className="toggle-hint">
                        {activeVariable.time.epoch
                          ? `起点 ${activeVariable.time.epoch}，单位 ${activeVariable.time.unit}`
                          : `单位 ${activeVariable.time.unit}，无日历起点`}
                      </span>
                    </label>
                    <label className={`radio-card ${activeField.time_mode === "numeric" ? "is-on" : ""}`}>
                      <input
                        type="radio"
                        name={`time-${activeVariable.name}`}
                        checked={activeField.time_mode === "numeric"}
                        onChange={() =>
                          updateField(activeVariable.name, (field) => ({
                            ...field,
                            time_mode: "numeric",
                          }))
                        }
                      />
                      <span className="toggle-title">保留原始数值</span>
                      <span className="toggle-hint">分析值用存储数值，导出后需自行按格式换算。</span>
                    </label>
                  </div>
                  {!activeVariable.time.supported ? (
                    <Callout tone="bad" title="不支持的时间格式">
                      {activeVariable.time.reason ??
                        "无法确定该格式的单位与起点，分析值将为空并标记为 unsupported。"}
                    </Callout>
                  ) : null}
                </div>
              ) : null}

              <div className="editor-section">
                <div className="section-head">
                  <h4>缺失码处理</h4>
                  <span className="muted small">只对本字段生效 · 不改变原始文件</span>
                </div>
                {ruleGroups.length === 0 ? (
                  <Empty>该字段没有需要处理的缺失码。</Empty>
                ) : (
                  <div className="rule-table">
                    {ruleGroups.map((group) => (
                      <div className="rule-group" key={group.state}>
                        <div className="rule-group-head">
                          <Badge tone={stateTone(group.state)}>{stateLabel(group.state)}</Badge>
                          <span className="muted small">{group.counts} 行</span>
                        </div>
                        {group.state === "system_missing" ? (
                          <p className="muted small rule-note">
                            空值没有可恢复的原始值；若要参与计算，只能“设为指定值”。
                          </p>
                        ) : group.rules.length === 0 ? (
                          <p className="muted small rule-note">
                            未在文件元数据中声明规则，但数据中出现了该状态。
                          </p>
                        ) : null}
                        <ul className="rule-items">
                          {group.rules.map((rule) => {
                            const override = findOverride(activeField, rule.id);
                            const options = actionsFor(rule);
                            return (
                              <li key={rule.id} className={override ? "is-changed" : ""}>
                                <div className="rule-main">
                                  <span className="rule-title">{ruleTitle(rule)}</span>
                                  <code className="muted small">{rule.id}</code>
                                </div>
                                <div className="rule-controls">
                                  <select
                                    value={override?.action ?? "missing"}
                                    onChange={(event) => {
                                      const value = event.target.value;
                                      if (value === "missing") setOverride(rule, null);
                                      else setOverride(rule, value as OverrideAction);
                                    }}
                                    aria-label={`${rule.id} 的处理方式`}
                                  >
                                    <option value="missing">保持原义（缺失）</option>
                                    {options.map((action) => (
                                      <option key={action} value={action}>
                                        {ACTION_TITLES[action]}
                                      </option>
                                    ))}
                                  </select>
                                  {override?.action === "set" ? (
                                    <input
                                      className="value-input"
                                      type="text"
                                      value={String(override.value ?? "")}
                                      placeholder={previewValuePlaceholder(activeVariable)}
                                      onChange={(event) => setOverrideValue(rule, event.target.value)}
                                      aria-label={`${rule.id} 的试算值`}
                                    />
                                  ) : null}
                                </div>
                                {override ? (
                                  <p className="rule-hint muted small">{ACTION_HINTS[override.action]}</p>
                                ) : null}
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </Panel>
          ) : (
            <Empty>在左侧勾选字段后即可设置。</Empty>
          )}
        </div>
      </div>

      <Panel
        title="预览与确认"
        subtitle={`${fields.length} 个字段 · ${overrideCount} 条转换 · 原始文件保持原样`}
        actions={
          <button type="button" className="btn btn-primary" onClick={onPreview} disabled={previewing || fields.length === 0}>
            {previewing ? <Spinner label="计算中" /> : "预览影响范围"}
          </button>
        }
      >
        {previewError ? (
          <Callout tone="bad" title="无法预览">
            {previewError}
          </Callout>
        ) : null}

        {!preview ? (
          <Empty>
            先预览：将列出受影响的行走与转换前后的统计范围，确认后才会生成新结果。
          </Empty>
        ) : (
          <div className="preview">
            <div className="preview-summary">
              <Stat label="行数" value={preview.scope.rows} />
              <Stat label="输出列" value={preview.scope.layer_count} />
              <Stat label="受影响单元格" value={affectedTotal} tone={affectedTotal ? "warn" : undefined} />
              <Stat label="导出格式" value={preview.scope.export_formats.join(" · ")} />
            </div>

            {preview.warnings.length > 0 ? (
              <Callout tone="warn" title="注意">
                <ul className="note-list">
                  {preview.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </Callout>
            ) : null}

            <div className="preview-fields">
              {preview.fields.map((field) => (
                <div className="preview-field" key={field.name}>
                  <div className="preview-field-head">
                    <h4>
                      <code>{field.name}</code> {field.title}
                    </h4>
                    <span className="muted small">
                      保留层：{field.layers.map((layer) => LAYER_TITLES[layer]).join(" · ")}
                      {field.time ? ` · 时间：${field.time_mode === "numeric" ? "保留原始数值" : "按源格式解释"}` : ""}
                    </span>
                  </div>
                  {field.overrides.length === 0 ? (
                    <p className="muted small">未做缺失码转换。</p>
                  ) : (
                    <ul className="preview-rules">
                      {field.overrides.map((rule) => (
                        <li key={rule.rule_id}>
                          <div className="preview-rule-head">
                            <code>{rule.rule_id}</code>
                            <Badge tone={rule.action === "set" || rule.action === "valid" ? "warn" : "muted"}>
                              {ACTION_TITLES[rule.action]}
                              {rule.action === "set" ? ` → ${showValue(rule.value)}` : ""}
                            </Badge>
                            <span className="muted small">
                              {rule.affected_count} 行受影响
                              {rule.rows_truncated ? `（仅列前 ${rule.affected_rows.length} 行）` : ""}
                            </span>
                          </div>
                          <p className="muted small">
                            行号：{rule.affected_rows.map((row) => row + 1).join("、") || "无"}
                            {rule.raw_values.length ? ` · 原值 ${rule.raw_values.join("、")}` : ""}
                          </p>
                          <StatsPair before={rule.before} after={rule.after} />
                        </li>
                      ))}
                    </ul>
                  )}
                  {field.warnings.length > 0 ? (
                    <ul className="note-list warn-list">
                      {field.warnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ))}
            </div>

            {preview.notes.length > 0 ? (
              <Callout tone="muted" title="影响范围说明">
                <ul className="note-list">
                  {preview.notes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              </Callout>
            ) : null}

            <div className="confirm-box">
              <div className="confirm-head">
                <h4>确认生成新结果</h4>
                <span className="muted small">
                  将另建结果目录；原始文件与首次解释保持不变（校验令牌 {preview.preview_token}）
                </span>
              </div>
              <div className="format-picker">
                {formats.map((item) => (
                  <label
                    key={item.id}
                    className={`format-card ${format === item.id ? "is-on" : ""}`}
                  >
                    <input
                      type="radio"
                      name="export-format"
                      value={item.id}
                      checked={format === item.id}
                      onChange={() => setFormat(item.id)}
                    />
                    <span className="format-title">{item.title}</span>
                    <span className="format-note">{item.notes}</span>
                    {item.limits.length > 0 ? (
                      <span className="format-limits">
                        {item.limits.map((limit) => (
                          <span key={limit}>· {limit}</span>
                        ))}
                      </span>
                    ) : null}
                  </label>
                ))}
              </div>
              <label className="acknowledge">
                <input
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(event) => setAcknowledged(event.target.checked)}
                />
                <span>
                  我已核对受影响的行、统计范围与导出格式；确认按 <strong>{format.toUpperCase()}</strong> 生成新结果，
                  原文件与原解释不变。
                </span>
              </label>
              {createError ? <Callout tone="bad">{createError}</Callout> : null}
              <div className="confirm-actions">
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!acknowledged || creating || !previewFresh}
                  onClick={() => onConfirm(format)}
                >
                  {creating ? <Spinner label="生成中" /> : `确认并生成（${format.toUpperCase()}）`}
                </button>
                <span className={`muted small ${previewFresh ? "" : "bad-text"}`}>
                  {previewFresh
                    ? "预览令牌与当前选择一致，确认后会另建结果目录。"
                    : "字段或转换在预览后发生了变化，请重新预览再确认。"}
                </span>
              </div>
            </div>
          </div>
        )}
      </Panel>

      {fields.length > 0 ? (
        <p className="muted small">
          当前选择摘要：{fields.map((field) => field.name).join("、")}
          {overrideCount ? `；转换 ${overrideCount} 条` : ""}。
        </p>
      ) : null}
    </div>
  );
}

function canonicalKey(fields: FieldSpec[]): string {
  const normalised = fields
    .map((field) => ({
      name: field.name,
      layers: [...field.layers].sort(),
      time_mode: field.time_mode,
      overrides: field.overrides
        .map((override) => ({
          rule_id: override.rule_id,
          action: override.action,
          value: override.value ?? null,
          label: override.label ?? null,
        }))
        .sort((left, right) =>
          `${left.rule_id}|${left.action}`.localeCompare(`${right.rule_id}|${right.action}`),
        ),
    }))
    .sort((left, right) => left.name.localeCompare(right.name));
  return JSON.stringify(normalised);
}

const LAYER_HINTS: Record<Layer, string> = {
  raw: "文件里实际存的值或缺失码",
  label: "软件会显示的标签/日期文本",
  analysis: "分析用值；缺失为空",
  state: "缺失类型与试算标记",
};

function defaultOverrideValue(
  rule: MissingRule,
  action: OverrideAction,
  variable: Variable | null,
): unknown {
  if (action !== "set") return null;
  if (!variable) return "";
  if (variable.time) {
    if (variable.time.kind === "date") return "2024-01-01";
    if (variable.time.kind === "datetime") return "2024-01-01T00:00:00";
    if (variable.time.kind === "month" || variable.time.kind === "quarter" || variable.time.kind === "half_year")
      return "2024-01-01";
    return 0;
  }
  if (variable.storage_type === "string") return rule.code ?? "";
  if (rule.kind === "user" && rule.code !== null) {
    const numeric = Number(rule.code);
    return Number.isFinite(numeric) ? numeric : 0;
  }
  return 0;
}
