/**
 * Render the four views to static HTML with data from a running backend.
 *
 *   node --experimental-strip-types ... (not used; built through vite)
 *
 * Run with:  npx vite build --ssr scripts/ssr-check.tsx --outDir /tmp/ssr && node /tmp/ssr/ssr-check.js
 */

import { renderToString } from "react-dom/server";
import { IntakeView } from "../src/components/IntakeView";
import { WorkspaceView } from "../src/components/WorkspaceView";
import { ConfigureView } from "../src/components/ConfigureView";
import { ResultsView } from "../src/components/ResultsView";
import { defaultFields } from "../src/lib/format";
import type { PreviewResult, ResultManifest, UploadSummary } from "../src/types";

const BASE = "http://127.0.0.1:8000/api";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`);
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return (await response.json()) as T;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`${path} -> ${response.status}: ${await response.text()}`);
  return (await response.json()) as T;
}

function check(name: string, html: string, needles: string[]) {
  const missing = needles.filter((needle) => !html.includes(needle));
  if (process.env.SSR_DUMP === name) console.log(html);
  if (missing.length > 0) {
    throw new Error(`${name}: rendered HTML is missing ${JSON.stringify(missing)}`);
  }
  console.log(`ok ${name} (${html.length} chars)`);
}

async function main() {
  const samples = await get<{ samples: unknown[] }>("/samples");
  const formats = await get<{ formats: { id: string; title: string; notes: string; limits: string[] }[] }>("/formats");
  const upload = await post<UploadSummary>("/uploads/sample/demo_intake.dta");

  check(
    "IntakeView",
    renderToString(
      <IntakeView
        samples={samples.samples as never}
        recent={[]}
        busy={null}
        error={null}
        onUploadFile={() => undefined}
        onLoadSample={() => undefined}
        onOpenUpload={() => undefined}
      />,
    ),
    ["SPSS · Stata → 统一数据", "demo_intake.dta", "拖入文件"],
  );

  check(
    "WorkspaceView",
    renderToString(
      <WorkspaceView upload={upload} onConfigure={() => undefined} onBack={() => undefined} />,
    ),
    ["变量定义", "收件台演示数据（Stata）", "不支持的格式", "week"],
  );

  const fields = defaultFields(upload.interpretation);
  const withOverride = fields.map((field) =>
    field.name === "group"
      ? { ...field, overrides: [{ rule_id: "extended:group:.a", action: "set" as const, value: 1 }] }
      : field,
  );
  const preview = await post<PreviewResult>(
    `/uploads/${upload.upload.upload_id}/preview`,
    { fields: withOverride },
  );
  check(
    "ConfigureView",
    renderToString(
      <ConfigureView
        interpretation={upload.interpretation}
        fields={withOverride}
        onChange={() => undefined}
        preview={preview}
        previewing={false}
        previewError={null}
        formats={formats.formats}
        onPreview={() => undefined}
        onConfirm={() => undefined}
        creating={false}
        createError={null}
        onBack={() => undefined}
      />,
    ),
    ["选择字段与转换方式", "预览与确认", "受影响单元格", "确认生成新结果", "扩展缺失码 .a", "extended:group:.a"],
  );

  const created = await post<ResultManifest>(`/uploads/${upload.upload.upload_id}/results`, {
    spec: { fields: withOverride },
    format: "dta",
    preview_token: preview.preview_token,
  });
  await post(`/results/${created.result_id}/exports/sav`);

  check(
    "ResultsView",
    renderToString(
      <ResultsView result={created} onBack={() => undefined} onRefresh={() => undefined} />,
    ),
    ["导出与回读核对", "核对通过", "查询结果", "重新读取并核对", "设为指定值"],
  );

  console.log("ssr check complete");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
