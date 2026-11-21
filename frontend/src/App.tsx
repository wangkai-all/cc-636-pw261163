import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "./api";
import type {
  FieldSpec,
  FormatInfo,
  PreviewResult,
  ResultManifest,
  SampleInfo,
  UploadListItem,
  UploadSummary,
} from "./types";
import { IntakeView } from "./components/IntakeView";
import { WorkspaceView } from "./components/WorkspaceView";
import { ConfigureView } from "./components/ConfigureView";
import { ResultsView } from "./components/ResultsView";
import { Badge, Callout, Spinner } from "./components/ui";
import { defaultFields } from "./lib/format";

type Step = "intake" | "workspace" | "configure" | "results";

export default function App() {
  const [step, setStep] = useState<Step>("intake");
  const [samples, setSamples] = useState<SampleInfo[]>([]);
  const [formats, setFormats] = useState<FormatInfo[]>([]);
  const [recent, setRecent] = useState<UploadListItem[]>([]);
  const [upload, setUpload] = useState<UploadSummary | null>(null);
  const [fields, setFields] = useState<FieldSpec[]>([]);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [result, setResult] = useState<ResultManifest | null>(null);

  const [busy, setBusy] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [creating, setCreating] = useState(false);

  const [intakeError, setIntakeError] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);

  const refreshRecent = async () => {
    try {
      const data = await api.listUploads();
      setRecent(data.uploads);
    } catch {
      /* recent list is a nicety; ignore failures */
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [sampleData, formatData] = await Promise.all([api.samples(), api.formats()]);
        if (cancelled) return;
        setSamples(sampleData.samples);
        setFormats(formatData.formats);
        await refreshRecent();
      } catch (exc) {
        if (!cancelled) {
          setBootError(exc instanceof Error ? exc.message : String(exc));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const openUpload = (data: UploadSummary) => {
    setUpload(data);
    setFields(defaultFields(data.interpretation));
    setPreview(null);
    setPreviewError(null);
    setCreateError(null);
    setResult(null);
    setStep("workspace");
  };

  const handleUploadFile = async (file: File) => {
    setBusy("upload");
    setIntakeError(null);
    try {
      const data = await api.uploadFile(file);
      openUpload(data);
      await refreshRecent();
    } catch (exc) {
      setIntakeError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const handleSample = async (name: string) => {
    setBusy(`sample:${name}`);
    setIntakeError(null);
    try {
      const data = await api.uploadSample(name);
      openUpload(data);
      await refreshRecent();
    } catch (exc) {
      setIntakeError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const handleOpenUpload = async (id: string) => {
    setBusy(`open:${id}`);
    setIntakeError(null);
    try {
      const data = await api.getUpload(id);
      openUpload(data);
    } catch (exc) {
      setIntakeError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const handlePreview = async () => {
    if (!upload) return;
    setPreviewing(true);
    setPreviewError(null);
    setCreateError(null);
    try {
      const data = await api.preview(upload.upload.upload_id, { fields });
      setPreview(data);
    } catch (exc) {
      setPreview(null);
      setPreviewError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setPreviewing(false);
    }
  };

  const handleConfirm = async (format: string) => {
    if (!upload || !preview) return;
    setCreating(true);
    setCreateError(null);
    try {
      const manifest = await api.createResult(
        upload.upload.upload_id,
        { fields },
        format,
        preview.preview_token,
      );
      setResult(manifest);
      setStep("results");
      await refreshRecent();
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      setCreateError(
        exc instanceof ApiError && exc.status === 409
          ? `${message}（字段或转换在预览后发生了变化）`
          : message,
      );
    } finally {
      setCreating(false);
    }
  };

  const completion = useMemo(() => {
    if (step === "intake") return 0;
    if (step === "workspace") return 1;
    if (step === "configure") return 2;
    return 3;
  }, [step]);

  const steps: { id: Step; label: string; enabled: boolean }[] = [
    { id: "intake", label: "1 读取", enabled: true },
    { id: "workspace", label: "2 检查定义", enabled: upload !== null },
    { id: "configure", label: "3 字段与试算", enabled: upload !== null },
    { id: "results", label: "4 结果与核对", enabled: result !== null },
  ];

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            收
          </span>
          <div>
            <strong>数据收件台</strong>
            <span className="muted small">SPSS SAV / Stata DTA → 可核对的结构化数据</span>
          </div>
        </div>
        <nav className="steps" aria-label="流程">
          {steps.map((item, index) => (
            <button
              key={item.id}
              type="button"
              className={`step ${step === item.id ? "is-active" : ""} ${
                index < completion ? "is-done" : ""
              }`}
              disabled={!item.enabled}
              onClick={() => {
                if (item.enabled) setStep(item.id);
              }}
            >
              {item.label}
            </button>
          ))}
        </nav>
        {upload ? (
          <div className="topbar-file">
            <Badge tone={upload.interpretation.file_type === "sav" ? "accent" : "info"}>
              {upload.interpretation.file_type.toUpperCase()}
            </Badge>
            <span className="small">
              {upload.upload.original_name} · {upload.interpretation.row_count} 行
            </span>
          </div>
        ) : null}
      </header>

      {bootError ? (
        <Callout tone="bad" title="后端服务不可用">
          {bootError}。请确认 FastAPI 已在 <code>127.0.0.1:8000</code> 启动。
        </Callout>
      ) : null}

      <main className="app-main">
        {step === "intake" ? (
          <IntakeView
            samples={samples}
            recent={recent}
            busy={busy}
            error={intakeError}
            onUploadFile={handleUploadFile}
            onLoadSample={handleSample}
            onOpenUpload={handleOpenUpload}
          />
        ) : null}

        {step === "workspace" && upload ? (
          <WorkspaceView
            upload={upload}
            onConfigure={() => setStep("configure")}
            onBack={() => {
              setUpload(null);
              setStep("intake");
              void refreshRecent();
            }}
          />
        ) : null}

        {step === "configure" && upload ? (
          <ConfigureView
            interpretation={upload.interpretation}
            fields={fields}
            onChange={(next) => {
              setFields(next);
              setPreview(null);
              setPreviewError(null);
            }}
            preview={preview}
            previewing={previewing}
            previewError={previewError}
            formats={formats}
            onPreview={handlePreview}
            onConfirm={handleConfirm}
            creating={creating}
            createError={createError}
            onBack={() => setStep("workspace")}
          />
        ) : null}

        {step === "results" && result ? (
          <ResultsView
            result={result}
            onBack={() => setStep("configure")}
            onRefresh={(manifest) => {
              setResult(manifest);
              void refreshRecent();
            }}
          />
        ) : null}

        {busy && step === "intake" ? (
          <div className="floating-busy">
            <Spinner label="读取文件…" />
          </div>
        ) : null}
      </main>

      <footer className="app-foot">
        <span>
          原始文件与首次解释写一次即固化；每次试算生成独立结果目录，导出后自动回读核对。
        </span>
        <span className="muted small">
          缺失语义：系统缺失 · 用户定义缺失 · Stata 扩展缺失（.a–.z）分别保存
        </span>
      </footer>
    </div>
  );
}
