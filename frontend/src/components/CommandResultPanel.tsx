import { CheckCircle2, Terminal, XCircle } from "lucide-react";
import type { CommandRunResult } from "../api/types";
import { JsonPreview } from "./JsonPreview";
import { StatusBadge } from "./StatusBadge";

type CommandResultPanelProps = {
  title: string;
  result: CommandRunResult | null;
};

export function CommandResultPanel({ title, result }: CommandResultPanelProps) {
  if (!result) return null;
  const Icon = result.ok ? CheckCircle2 : XCircle;
  return (
    <section className="panel command-result">
      <div className="panel__header">
        <div>
          <h2>{title}</h2>
          <p>{result.dry_run ? "本次为 dry-run，没有执行真实飞书写入。" : "命令已执行，请核对飞书群和报告。"} </p>
        </div>
        <StatusBadge status={result.ok ? "success" : "failed"} tone={result.ok ? "ok" : "danger"} />
      </div>
      <div className="summary-grid">
        <div>
          <span>Returncode</span>
          <code>{result.returncode}</code>
        </div>
        <div>
          <span>Report</span>
          <code>{result.report_path || "-"}</code>
        </div>
        <div>
          <span>Mode</span>
          <code>{result.dry_run ? "dry-run" : "allow-write"}</code>
        </div>
      </div>
      <div className={result.ok ? "callout callout--ok" : "callout callout--warn"}>
        <Icon size={16} />
        <span>{result.ok ? "命令返回成功。" : "命令返回失败，请查看 stdout 中的飞书错误码、request_id 或本地配置提示。"}</span>
      </div>
      <details className="command-details">
        <summary>
          <Terminal size={16} />
          命令
        </summary>
        <JsonPreview value={result.command.join(" ")} maxHeight={120} />
      </details>
      {Object.keys(result.parsed ?? {}).length ? <JsonPreview value={result.parsed} maxHeight={220} /> : null}
      <JsonPreview value={result.stdout} maxHeight={360} />
    </section>
  );
}
