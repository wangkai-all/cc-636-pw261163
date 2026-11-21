import { useRef, useState } from "react";
import type { DragEvent } from "react";
import type { SampleInfo, UploadListItem } from "../types";
import { Badge, Callout, Empty, Spinner } from "./ui";
import { formatBytes, formatTime } from "../lib/format";

interface Props {
  samples: SampleInfo[];
  recent: UploadListItem[];
  busy: string | null;
  error: string | null;
  onUploadFile: (file: File) => void;
  onLoadSample: (name: string) => void;
  onOpenUpload: (id: string) => void;
}

export function IntakeView({
  samples,
  recent,
  busy,
  error,
  onUploadFile,
  onLoadSample,
  onOpenUpload,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) onUploadFile(file);
  };

  return (
    <div className="intake">
      <section className="hero">
        <div className="hero-copy">
          <span className="eyebrow">SPSS · Stata → 统一数据</span>
          <h1>先把文件读清楚，再决定怎么用。</h1>
          <p>
            上传 <code>.sav</code> 或 <code>.dta</code>，逐字段检查存储类型、值标签、日期起点与缺失规则。
            原始值、显示标签、分析值分三层保存；缺失码改写只发生在新的试算结果里。
          </p>
          <ol className="hero-steps">
            <li>
              <span>1</span> 读取并检查定义
            </li>
            <li>
              <span>2</span> 选字段与转换
            </li>
            <li>
              <span>3</span> 预览影响并确认
            </li>
            <li>
              <span>4</span> 导出后重新核对
            </li>
          </ol>
        </div>
        <div
          className={`dropzone ${dragging ? "dropzone-active" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") inputRef.current?.click();
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".sav,.dta"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) onUploadFile(file);
              event.target.value = "";
            }}
          />
          <span className="dropzone-icon" aria-hidden="true">
            ⇪
          </span>
          <strong>{busy === "upload" ? "正在读取…" : "拖入文件，或点击选择"}</strong>
          <span className="dropzone-hint">SPSS SAV（$FL2/$FL3）· Stata DTA 117–119 · 上限 50 MB</span>
          {busy === "upload" ? <Spinner label="解析中" /> : null}
        </div>
      </section>

      {error ? (
        <Callout tone="bad" title="读取失败">
          {error}
        </Callout>
      ) : null}

      <div className="intake-grid">
        <section className="panel">
          <header className="panel-head">
            <div className="panel-heading">
              <h2>演示样例</h2>
              <p className="panel-subtitle">
                两个文件描述同一批问卷，但缺失的含义不同：SAV 用用户定义缺失，DTA 用扩展缺失码。
              </p>
            </div>
          </header>
          <div className="panel-body">
            {samples.length === 0 ? (
              <Empty>没有找到 samples/ 目录下的演示文件。</Empty>
            ) : (
              <ul className="sample-list">
                {samples.map((sample) => (
                  <li key={sample.filename}>
                    <div className="sample-main">
                      <Badge tone={sample.file_type === "sav" ? "accent" : "info"}>
                        {sample.file_type.toUpperCase()}
                      </Badge>
                      <div>
                        <strong>{sample.filename}</strong>
                        <span className="muted">
                          {formatBytes(sample.size_bytes)} · 含有效零值、多种缺失码、日期与中文长字符串
                        </span>
                      </div>
                    </div>
                    <button
                      type="button"
                      className="btn btn-small"
                      disabled={busy !== null}
                      onClick={() => onLoadSample(sample.filename)}
                    >
                      {busy === `sample:${sample.filename}` ? "读取中…" : "载入"}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <section className="panel">
          <header className="panel-head">
            <div className="panel-heading">
              <h2>最近读取</h2>
              <p className="panel-subtitle">原始文件与首次解释均已固化，可随时回到原样重新开始。</p>
            </div>
          </header>
          <div className="panel-body">
            {recent.length === 0 ? (
              <Empty>还没有上传记录。</Empty>
            ) : (
              <ul className="recent-list">
                {recent.map((item) => (
                  <li key={item.upload_id}>
                    <button type="button" className="link-row" onClick={() => onOpenUpload(item.upload_id)}>
                      <span>
                        <strong>{item.original_name}</strong>
                        <span className="muted">
                          {item.file_type.toUpperCase()} · {formatBytes(item.size_bytes)} ·{" "}
                          {formatTime(item.created_at)}
                        </span>
                      </span>
                      <span className="recent-meta">
                        <Badge tone={item.result_count ? "good" : "muted"}>
                          {item.result_count} 个结果
                        </Badge>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>

      <section className="principles">
        <article>
          <h3>缺失含义分开记</h3>
          <p>
            系统缺失、SPSS 用户定义缺失（离散码/区间/字符串）与 Stata 扩展缺失码 <code>.a</code>–
            <code>.z</code> 各自成列，导出后再读回来逐格核对。
          </p>
        </article>
        <article>
          <h3>代码不等于含义</h3>
          <p>
            同一个 9 在 <code>group</code> 里是“拒答”，在 <code>edu_years</code> 里是“九年级”。
            标签按字段保存，不做全局字典替换。
          </p>
        </article>
        <article>
          <h3>日期按源格式解释</h3>
          <p>
            SPSS 以 1582-10-14 为秒零点，Stata 以 1960-01-01 为起点。无法确定的格式标为不支持，
            不会当作普通数字。
          </p>
        </article>
      </section>
    </div>
  );
}
