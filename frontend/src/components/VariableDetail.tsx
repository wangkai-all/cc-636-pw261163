import { useEffect, useState } from "react";
import { api } from "../api";
import type { CellLayerRow, Variable } from "../types";
import {
  countSummary,
  LAYER_TITLES,
  ruleRange,
  ruleTitle,
  showValue,
  stateLabel,
  stateTone,
} from "../lib/format";
import { Badge, Callout, Spinner } from "./ui";

const CLASSIFICATION_TITLES: Record<string, string> = {
  numeric: "普通数值",
  string: "字符串",
  date: "日期",
  datetime: "日期时间",
  duration: "时长",
  month: "月份周期",
  quarter: "季度周期",
  half_year: "半年周期",
  year: "年份",
  unsupported: "不支持的格式",
};

export function CellTable({ rows, total }: { rows: CellLayerRow[]; total: number }) {
  return (
    <div className="table-scroll">
      <table className="data-table cell-table">
        <thead>
          <tr>
            <th className="num">行</th>
            <th>{LAYER_TITLES.raw}</th>
            <th>{LAYER_TITLES.label}</th>
            <th>{LAYER_TITLES.analysis}</th>
            <th>{LAYER_TITLES.state}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((cell) => (
            <tr key={cell.row_id}>
              <td className="num muted">{cell.row_id + 1}</td>
              <td className="mono">{showValue(cell.raw) || <span className="muted">（空）</span>}</td>
              <td>{showValue(cell.label) || <span className="muted">—</span>}</td>
              <td className="mono">
                {showValue(cell.analysis) || <span className="muted">（空）</span>}
              </td>
              <td>
                <Badge tone={stateTone(cell.state)} title={cell.rule ?? undefined}>
                  {stateLabel(cell.state)}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="table-foot muted">
        显示 {rows.length} / {total} 行。三层同时保留：原始值不改动，分析值遇缺失为空。
      </p>
    </div>
  );
}

export function VariableDetail({
  variable,
  uploadId,
}: {
  variable: Variable;
  uploadId: string;
}) {
  const [cells, setCells] = useState<CellLayerRow[] | null>(null);
  const [total, setTotal] = useState<number>(variable.sample_cells.length);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCells(null);
    setError(null);
    setTotal(variable.sample_cells.length);
  }, [variable.name]);

  const loadAll = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.columnCells(uploadId, variable.name, 500, 0);
      setCells(result.rows);
      setTotal(result.total);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  };

  const previewRows: CellLayerRow[] =
    cells ??
    variable.sample_cells.map((cell) => ({
      row_id: cell.row,
      raw: cell.raw,
      label: cell.label,
      analysis: cell.analysis,
      state: cell.state,
      rule: cell.rule,
      ext_code: cell.ext_code,
    }));

  const storageText =
    variable.storage_type === "string"
      ? `${variable.is_strl ? "strL 引用" : `定长字符串`} · 存储宽度 ${
          variable.storage_width ?? "未知"
        } 字节 · 显示宽度 ${variable.display_width ?? "未定义"}`
      : `数值存储 ${variable.storage_type} · 宽度 ${variable.storage_width ?? "—"} 字节`;

  return (
    <div className="variable-detail">
      <div className="detail-grid">
        <div>
          <h4>存储与格式</h4>
          <dl className="dense-kv">
            <dt>分类</dt>
            <dd>
              <Badge
                tone={
                  variable.classification === "unsupported"
                    ? "bad"
                    : variable.classification === "string"
                      ? "info"
                      : "accent"
                }
              >
                {CLASSIFICATION_TITLES[variable.classification] ?? variable.classification}
              </Badge>
            </dd>
            <dt>存储</dt>
            <dd className="mono">{storageText}</dd>
            <dt>源格式</dt>
            <dd className="mono">{variable.source_format ?? "无"}</dd>
            {variable.encoding ? (
              <>
                <dt>编码</dt>
                <dd className="mono">{variable.encoding}</dd>
              </>
            ) : null}
            {variable.measure ? (
              <>
                <dt>测量</dt>
                <dd>{variable.measure}</dd>
              </>
            ) : null}
            <dt>状态统计</dt>
            <dd>{countSummary(variable.counts)}</dd>
          </dl>
        </div>

        <div>
          <h4>时间解释</h4>
          {variable.time ? (
            <dl className="dense-kv">
              <dt>类型</dt>
              <dd>{CLASSIFICATION_TITLES[variable.time.kind] ?? variable.time.kind}</dd>
              <dt>单位</dt>
              <dd className="mono">{variable.time.unit ?? "—"}</dd>
              <dt>起点</dt>
              <dd className="mono">{variable.time.epoch ?? "无（时长）"}</dd>
              {variable.time.leap_seconds ? (
                <>
                  <dt>备注</dt>
                  <dd>使用连续时间标度；闰秒差异未应用。</dd>
                </>
              ) : null}
            </dl>
          ) : (
            <p className="muted">该字段没有日期/时间格式，按普通{variable.classification === "string" ? "文本" : "数值"}处理。</p>
          )}
          {variable.time && !variable.time.supported ? (
            <Callout tone="bad" title="不支持的格式">
              {variable.time.reason ?? "无法确定该格式的时间含义。"}
            </Callout>
          ) : null}
        </div>

        <div>
          <h4>值标签（仅本字段）</h4>
          {variable.value_labels.length === 0 ? (
            <p className="muted">没有值标签。</p>
          ) : (
            <ul className="label-chips">
              {variable.value_labels.map((item) => (
                <li key={`${item.value}-${item.label}`}>
                  <code>{item.value}</code>
                  <span>{item.label}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <h4>缺失规则（仅本字段）</h4>
          {variable.missing_rules.length === 0 ? (
            <p className="muted">没有额外的用户缺失码；空值按系统缺失处理。</p>
          ) : (
            <ul className="rule-list">
              {variable.missing_rules.map((rule) => (
                <li key={rule.id}>
                  <Badge
                    tone={
                      rule.kind === "extended"
                        ? "info"
                        : rule.kind === "user"
                          ? "warn"
                          : "muted"
                    }
                  >
                    {rule.kind === "extended"
                      ? "扩展"
                      : rule.kind === "user"
                        ? "用户缺失"
                        : "系统"}
                  </Badge>
                  <span>{ruleTitle(rule)}</span>
                  <code className="muted">{rule.id}</code>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {variable.notes.length > 0 ? (
        <ul className="note-list">
          {variable.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}

      {variable.classification === "string" ? (
        <p className="muted small">
          观测最大长度：{variable.observed_max_chars} 字符 / {variable.observed_max_bytes} 字节。
          编码、存储宽度与实际字符数是三件事，分别在上表中记录。
        </p>
      ) : null}

      <div className="detail-cells">
        <div className="detail-cells-head">
          <h4>逐格三层对照</h4>
          {cells === null ? (
            <button type="button" className="btn btn-small" onClick={loadAll} disabled={loading}>
              {loading ? <Spinner label="读取中" /> : "读取全部行"}
            </button>
          ) : (
            <span className="muted small">已读取全部 {total} 行</span>
          )}
        </div>
        {error ? <Callout tone="bad">{error}</Callout> : null}
        <CellTable rows={previewRows} total={total} />
      </div>

      {variable.missing_rules.some((rule) => rule.kind !== "system") ? (
        <p className="muted small">
          规则的取值范围：{variable.missing_rules.map((rule) => `${rule.id} = ${ruleRange(rule)}`).join("；")}
        </p>
      ) : null}
    </div>
  );
}
