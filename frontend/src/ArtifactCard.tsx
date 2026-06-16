import { useState } from "react";

export type ArtifactRef = { id: string; kind: string; filename: string; size_bytes: number };

const API_BASE = import.meta.env.VITE_API_BASE_URL;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function ArtifactCard(
  { artifact, getToken }: { artifact: ArtifactRef; getToken: () => Promise<string> }
) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handleDownload() {
    setBusy(true); setErr(null);
    try {
      const tok = await getToken();
      const r = await fetch(`${API_BASE}/api/artifacts/${artifact.id}/download`, {
        headers: { Authorization: `Bearer ${tok}` }
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = artifact.filename;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  const icon = artifact.kind === "xlsx" ? "📊"
    : artifact.kind === "pdf" ? "📄"
    : artifact.kind === "pptx" ? "🎴" : "📎";

  return (
    <div className="artifact-card">
      <span className="artifact-icon">{icon}</span>
      <div className="artifact-meta">
        <div className="artifact-name">{artifact.filename}</div>
        <div className="artifact-sub">{formatSize(artifact.size_bytes)} · {artifact.kind.toUpperCase()}</div>
      </div>
      <button className="artifact-dl" onClick={handleDownload} disabled={busy}>
        {busy ? "Baixando…" : "Baixar"}
      </button>
      {err && <span className="artifact-err">⚠ {err}</span>}
    </div>
  );
}
