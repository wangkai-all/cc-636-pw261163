import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  ExportInfo,
  RecheckReport,
  ResultManifest,
  ResultRows,
  VerificationReport,
} from "../types";
import {
  ACTION_TITLES,
  formatBytes,
  formatNumber,
  formatTime,
  isEmptyCell,
  LAYER_TITLES,
  showValue,
  stateTone,
} from "../lib/format";
import { Badge, Callout, Empty, Panel, Spinner, Stat } from "./ui";

function stateBadge(value: unknown) {
  if (typeof value !== "string") return null;
  return <Badge tone={stateTone(value)}>{value}</Badge>;
}

function ColumnHead({ name, result }: { name: string; result: ResultManifest }) {
  const meta = result.columns.find((column) => column.name === name);
  if (!meta) return <th>{name}</th>;
  return (
    <th>
      <span className="col-name">{meta.source}</span>
      <span className="col-layer">{LAYER_TITLES[meta.layer]}</span>
      <span className="col-type">{meta.dtype === "number" ? "数值" : "文本"}</span>
    </th>
  );
}

function TableCell({ value, meta }: { value: unknown; meta?: ResultManifest["columns"][number] }) {
  if (isEmptyCell(value)) return <td className="muted">—</td>;
  if (meta?.layer === "state" || meta?.layer === "label") {
    return <td>{meta.layer === "state" ? stateBadge(value) ?? showValue(value) : showValue(value)}</td>;
  }
  return <td className={meta?.dtype === "number" ? "mono" : ""}>{showValue(value)}</td>;
}

function VerificationCard({ report }: { report: VerificationReport }) {
  if (!report) return null;
  const issues =
    report.value_mismatches.length +
    report.label_mismatches.length +
    report.missing_mismatches.length +
    report.column_mismatches.length;
  return (
    <div className={`verify-card ${report.ok ? "is-ok" : "is-bad"}`}>
      <div className="verify-head">
        <Badge tone={report.ok ? "good" : "bad"}>{report.ok ? "核对通过" : "核对不通过"}</Badge>
        <strong>{report.format.toUpperCase()}</strong>
        <span className="muted small">
          {report.checked_columns} 列 / {report.checked_cells} 格已重新读取比对
        </span>
      </div>
      {report.error ? <p className="bad-text small">{report.error}</p> : null}
      {issues > 0 ? (
        <div className="verify-issues">
          {report.value_mismatches.length > 0 ? (
            <details open>
              <summary>值不一致 · {report.value_mismatches.length}</summary>
              <pre>{JSON.stringify(report.value_mismatches.slice(0, 20), null, 2)}</pre>
            </details>
          ) : null}
          {report.label_mismatches.length > 0 ? (
            <details>
              <summary>标签不一致 · {report.label_mismatches.length}</summary>
              <pre>{JSON.stringify(report.label_mismatches.slice(0, 20), null, 2)}</pre>
            </details>
          ) : null}
          {report.missing_mismatches.length > 0 ? (
            <details>
              <summary>缺失含义不一致 · {report.missing_mismatches.length}</summary>
              <pre>{JSON.stringify(report.missing_mismatches.slice(0, 20), null, 2)}</pre>
            </details>
          ) : null}
          {report.column_mismatches.length > 0 ? (
            <details>
              <summary>列不一致 · {report.column_mismatches.length}</summary>
              <pre>{JSON.stringify(report.column_mismatches.slice(0, 20), null, 2)}</pre>
            </details>
          ) : null}
        </div>
      ) : (
        <p className="small muted">
          值与缺失含义逐格一致；标签与缺失规则按格式重新读取后比对。
        </p>
      )}
      {report.notes.length > 0 ? (
        <ul className="note-list small">
          {report.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function ResultsView({
  result,
  onBack,
  onRefresh,
}: {
  result: ResultManifest;
  onBack: () => void;
  onRefresh: (manifest: ResultManifest) => void;
}) {
  const [rows, setRows] = useState<ResultRows | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [recheck, setRecheck] = useState<RecheckReport | null>(null);
  const [rechecking, setRechecking] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  const limit = 50;

  const load = useCallback(
    async (q: string, skip: number) => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.resultRows(result.result_id, q, limit, skip);
        setRows(data);
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : String(exc));
      } finally {
        setLoading(false);
      }
    },
    [result.result_id],
  );

  useEffect(() => {
    setOffset(0);
    void load("", 0);
  }, [load]);

  const runSearch = () => {
    setOffset(0);
    setSearch(query.trim());
    void load(query.trim(), 0);
  };

  const goTo = (next: number) => {
    const clamped = Math.max(0, next);
    setOffset(clamped);
    void load(search, clamped);
  };

  const runRecheck = async () => {
    setRechecking(true);
    setError(null);
    try {
      const report = await api.recheck(result.result_id);
      setRecheck(report);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setRechecking(false);
    }
  };

  const addExport = async (fmt: string) => {
    setAdding(fmt);
    setAddError(null);
    try {
      const manifest = await api.addExport(result.result_id, fmt);
      onRefresh(manifest);
    } catch (exc) {
      setAddError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setAdding(null);
    }
  };

  const schema = rows?.schema ?? result.columns;
  const total = rows?.total ?? result.row_count;
  const availableExports = new Set(result.exports.map((item) => item.id));
  const missingFormats = ["csv", "xlsx", "sav", "dta"].filter((fmt) => !availableExports.has(fmt));

  const affectedRows = useMemo(() => {
    const rows = new Set<number>();
    for (const override of result.overrides) {
      for (const row of override.affected_rows) rows.add(row);
    }
    return rows;
  }, [result.overrides]);

  return (
    <div className="results">
      <Panel
        title={
          <span className="title-with-badge">
            结果 {result.result_id}
            <Badge tone={result.error ? "bad" : "good"}>{result.format.toUpperCase()}</Badge>
          </span>
        }
        subtitle={`${result.row_count} 行 · ${result.columns.length} 列 · 生成于 ${formatTime(result.created_at)}`}
        actions={
          <>
            <button type="button" className="btn btn-ghost" onClick={onBack}>
              返回字段设置
            </button>
            <button type="button" className="btn" onClick={runRecheck} disabled={rechecking}>
              {rechecking ? <Spinner label="重新读取" /> : "重新读取并核对"}
            </button>
          </>
        }
      >
        <div className="result-summary">
          <Stat label="原始文件" value={result.original.original_name} hint={`sha256 ${result.original.sha256.slice(0, 16)}…`} />
          <Stat label="原始文件状态" value={result.original.unchanged ? "未改动" : "未知"} tone={result.original.unchanged ? "good" : "bad"} />
          <Stat label="转换条数" value={result.overrides.length} />
          <Stat label="受影响行" value={affectedRows.size} tone={affectedRows.size ? "warn" : undefined} />
        </div>

        {result.notes.length > 0 ? (
          <ul className="note-list dataset-notes">
            {result.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        ) : null}

        {result.overrides.length > 0 ? (
          <div className="override-list">
            <h4>本次试算的缺失码转换</h4>
            <ul>
              {result.overrides.map((override, index) => (
                <li key={`${override.field}-${override.rule_id}-${index}`}>
                  <code>{override.field}</code>
                  <Badge tone="warn">{ACTION_TITLES[override.action]}</Badge>
                  <span className="mono small">{override.rule_id}</span>
                  {override.action === "set" ? (
                    <span className="small">→ {showValue(override.value)}</span>
                  ) : null}
                  <span className="muted small">
                    {override.affected_count} 行（{override.affected_rows.map((row) => row + 1).join("、") || "无"}）
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </Panel>

      <Panel
        title="导出与回读核对"
        subtitle="每个文件生成后立即重新读取，逐格比对值、标签与缺失含义"
        actions={
          missingFormats.length > 0 ? (
            <span className="muted small">可补充导出：{missingFormats.join(" / ")}</span>
          ) : null
        }
      >
        {addError ? <Callout tone="bad">{addError}</Callout> : null}
        <div className="export-grid">
          {result.exports.map((item) => (
            <ExportCard key={item.id} item={item} resultId={result.result_id} />
          ))}
          {missingFormats.map((fmt) => (
            <button
              key={fmt}
              type="button"
              className="export-add"
              disabled={adding !== null}
              onClick={() => void addExport(fmt)}
            >
              <span className="export-add-icon">＋</span>
              <span>{adding === fmt ? "生成中…" : `再导出 ${fmt.toUpperCase()}`}</span>
              <span className="muted small">生成后会自动回读核对</span>
            </button>
          ))}
        </div>

        {recheck ? (
          <div className="recheck">
            <h4>重新读取导出文件（{formatTime(Date.now() / 1000)}）</h4>
            <div className="verify-grid">
              {recheck.reports.map((report) => (
                <VerificationCard key={report.format} report={report} />
              ))}
            </div>
          </div>
        ) : (
          <p className="muted small">
            点击“重新读取并核对”会再次打开已导出的文件，与当前结果逐列比对，而不只是比较行数。
          </p>
        )}
      </Panel>

      <Panel
        title="查询结果"
        subtitle="所有层按字段并列保存；可用关键词跨列搜索（如 拒答、.a、2023）"
        actions={
          <form
            className="search-form"
            onSubmit={(event) => {
              event.preventDefault();
              runSearch();
            }}
          >
            <input
              type="search"
              value={query}
              placeholder="搜索任意列…"
              onChange={(event) => setQuery(event.target.value)}
            />
            <button type="submit" className="btn btn-small">
              搜索
            </button>
          </form>
        }
      >
        {error ? <Callout tone="bad">{error}</Callout> : null}
        {loading && !rows ? (
          <Spinner label="读取结果" />
        ) : rows && rows.rows.length === 0 ? (
          <Empty>{search ? `没有包含“${search}”的行。` : "结果为空。"}</Empty>
        ) : rows ? (
          <>
            <div className="table-scroll tall">
              <table className="data-table result-table">
                <thead>
                  <tr>
                    <th className="num">#</th>
                    {schema.map((column) => (
                      <ColumnHead key={column.name} name={column.name} result={result} />
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.rows.map((row) => {
                    const rowId = Number(row.row_id);
                    return (
                      <tr key={rowId} className={affectedRows.has(rowId) ? "row-affected" : undefined}>
                        <td className="num muted">{rowId + 1}</td>
                        {schema.map((column) => (
                          <TableCell
                            key={column.name}
                            value={row[column.name]}
                            meta={column}
                          />
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="pager">
              <span className="muted small">
                第 {total === 0 ? 0 : offset + 1}–{Math.min(offset + limit, total)} 行，共 {total} 行
                {search ? `（搜索“${search}”）` : ""}
              </span>
              <div className="pager-actions">
                <button type="button" className="btn btn-small" disabled={offset === 0} onClick={() => goTo(offset - limit)}>
                  上一页
                </button>
                <button
                  type="button"
                  className="btn btn-small"
                  disabled={offset + limit >= total}
                  onClick={() => goTo(offset + limit)}
                >
                  下一页
                </button>
              </div>
            </div>
          </>
        ) : null}
      </Panel>

      <Panel title="列说明" subtitle="每列来自哪个字段、哪一层，以及该层的含义">
        <div className="schema-list">
          {schema.map((column) => (
            <div className="schema-row" key={column.name}>
              <div className="schema-name">
                <code>{column.name}</code>
                <Badge tone={column.layer === "state" ? "muted" : column.layer === "analysis" ? "accent" : "info"}>
                  {LAYER_TITLES[column.layer]}
                </Badge>
              </div>
              <div className="schema-desc">
                <span>{column.title}</span>
                <span className="muted small">{column.description}</span>
                {column.notes.map((note) => (
                  <span className="muted small" key={note}>
                    · {note}
                  </span>
                ))}
              </div>
              {column.value_labels.length > 0 ? (
                <div className="schema-labels">
                  {column.value_labels.map((item) => (
                    <span key={`${item.value}-${item.label}`}>
                      <code>{item.value}</code>={item.label}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </Panel>

      <p className="muted small">
        原始文件 sha256 {result.original.sha256}；原解释文件保持只读，试算结果写入独立目录。
        {result.row_count > 0 ? ` 每格数值统计见预览；结果共 ${formatNumber(result.columns.length)} 列。` : ""}
      </p>
    </div>
  );
}

function ExportCard({ item, resultId }: { item: ExportInfo; resultId: string }) {
  const ok = item.verification?.ok;
  return (
    <div className={`export-card ${ok ? "is-ok" : "is-bad"}`}>
      <div className="export-head">
        <strong>{item.id.toUpperCase()}</strong>
        <Badge tone={ok ? "good" : "bad"}>{ok ? "核对通过" : "核对不通过"}</Badge>
        <span className="muted small">{formatBytes(item.size_bytes)}</span>
      </div>
      <a className="btn btn-small" href={api.downloadUrl(resultId, item.id)}>
        下载 {item.filename}
      </a>
      {item.sidecar ? <span className="muted small">附带 {item.sidecar}</span> : null}
      <ul className="note-list small">
        {item.notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
        {item.limits.map((limit) => (
          <li key={limit} className="muted">
            {limit}
          </li>
        ))}
      </ul>
      {item.verification ? (
        <p className="muted small">
          {item.verification.checked_columns} 列 / {item.verification.checked_cells} 格重新比对
        </p>
      ) : null}
    </div>
  );
}
