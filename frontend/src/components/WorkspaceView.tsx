import { useState } from "react";
import type { UploadSummary, Variable } from "../types";
import { countSummary, formatBytes, shortHash } from "../lib/format";
import { Badge, Callout, Empty, KeyValue, Panel } from "./ui";
import { VariableDetail } from "./VariableDetail";

export function WorkspaceView({
  upload,
  onConfigure,
  onBack,
}: {
  upload: UploadSummary;
  onConfigure: () => void;
  onBack: () => void;
}) {
  const { interpretation } = upload;
  const [active, setActive] = useState<string>(interpretation.variables[0]?.name ?? "");
  const activeVariable: Variable | undefined = interpretation.variables.find(
    (variable) => variable.name === active,
  );

  const unsupported = interpretation.variables.filter(
    (variable) => variable.classification === "unsupported",
  );

  return (
    <div className="workspace">
      <Panel
        title={
          <span className="title-with-badge">
            {upload.upload.original_name}
            <Badge tone={interpretation.file_type === "sav" ? "accent" : "info"}>
              {interpretation.file_type.toUpperCase()}
            </Badge>
          </span>
        }
        subtitle={`${interpretation.file_format} · ${interpretation.row_count} 行 × ${interpretation.column_count} 列 · ${formatBytes(upload.upload.size_bytes)}`}
        actions={
          <>
            <button type="button" className="btn btn-ghost" onClick={onBack}>
              换一个文件
            </button>
            <button type="button" className="btn btn-primary" onClick={onConfigure}>
              选择字段与转换
            </button>
          </>
        }
      >
        <KeyValue
          items={[
            { label: "文件类型", value: interpretation.file_type.toUpperCase() },
            { label: "字符编码", value: interpretation.encoding ?? "未声明" },
            { label: "数据集标签", value: interpretation.file_label ?? "无" },
            {
              label: "SHA-256",
              value: <code className="mono">{shortHash(upload.upload.sha256)}</code>,
            },
            {
              label: "原始文件",
              value: <span className="ok-text">已固化 · 不可修改</span>,
            },
            { label: "已有结果", value: `${upload.results.length} 个` },
          ]}
        />

        {interpretation.notes.length > 0 ? (
          <ul className="note-list dataset-notes">
            {interpretation.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        ) : null}

        {interpretation.label_conflicts.length > 0 ? (
          <Callout tone="warn" title="同一数值在不同字段含义不同">
            <ul className="conflict-list">
              {interpretation.label_conflicts.map((conflict) => (
                <li key={conflict.value}>
                  <code>{conflict.value}</code>
                  {conflict.meanings.map((meaning) => (
                    <span key={meaning.label}>
                      {meaning.label}
                      <span className="muted">（{meaning.variables.join("、")}）</span>
                    </span>
                  ))}
                </li>
              ))}
            </ul>
            <p className="small">
              因此本工具不使用全局字典替换：每个字段的标签与缺失规则只对该字段生效。
            </p>
          </Callout>
        ) : null}

        {unsupported.length > 0 ? (
          <Callout tone="bad" title="存在不支持的格式">
            {unsupported.map((variable) => variable.name).join("、")} 的格式无法确定时间含义，
            分析值将为空并标记为 unsupported，原始数值保留。
          </Callout>
        ) : null}
      </Panel>

      <div className="workspace-body">
        <aside className="variable-rail" aria-label="变量列表">
          <div className="rail-head">
            <h2>变量定义</h2>
            <span className="muted small">{interpretation.variables.length} 个字段</span>
          </div>
          <ul>
            {interpretation.variables.map((variable) => (
              <li key={variable.name}>
                <button
                  type="button"
                  className={`variable-item ${variable.name === active ? "is-active" : ""}`}
                  onClick={() => setActive(variable.name)}
                >
                  <span className="variable-name">
                    <code>{variable.name}</code>
                    {variable.classification === "unsupported" ? (
                      <Badge tone="bad">不支持</Badge>
                    ) : null}
                  </span>
                  <span className="variable-label">{variable.label ?? "无变量标签"}</span>
                  <span className="variable-meta">
                    <span className="mono">
                      {variable.storage_type}
                      {variable.storage_width ? `/${variable.storage_width}` : ""}
                    </span>
                    <span>{variable.source_format ?? "无格式"}</span>
                  </span>
                  <span className="variable-counts">{countSummary(variable.counts)}</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <div className="variable-main">
          {activeVariable ? (
            <Panel
              title={
                <span className="title-with-badge">
                  <code>{activeVariable.name}</code>
                  {activeVariable.label ? (
                    <span className="variable-title-text">{activeVariable.label}</span>
                  ) : null}
                </span>
              }
              subtitle={`第 ${activeVariable.index + 1} 列 · ${countSummary(activeVariable.counts)}`}
            >
              <VariableDetail variable={activeVariable} uploadId={upload.upload.upload_id} />
            </Panel>
          ) : (
            <Empty>这个文件没有可显示的字段。</Empty>
          )}
        </div>
      </div>
    </div>
  );
}
