import { useState } from "react";

export function UploadZone({ onUpload }: { onUpload: (file: File) => void | Promise<void> }) {
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);

  const handle = async (f: File | undefined) => {
    if (!f) return;
    setBusy(true);
    try {
      await onUpload(f);
    } finally {
      setBusy(false);
    }
  };

  return (
    <label
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        void handle(e.dataTransfer.files[0]);
      }}
      style={{
        display: "grid",
        placeItems: "center",
        padding: "40px 32px",
        borderRadius: 18,
        border: `1.5px dashed ${over ? "var(--accent)" : "var(--border-strong)"}`,
        background: over ? "var(--surface-hover)" : "var(--surface)",
        cursor: busy ? "wait" : "pointer",
        transition: "all 200ms var(--ease, ease)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
      }}
    >
      <input
        type="file"
        accept=".html,text/html"
        hidden
        disabled={busy}
        onChange={(e) => void handle(e.target.files?.[0] ?? undefined)}
      />
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 16, fontWeight: 600, letterSpacing: "-0.01em" }}>
          {busy ? "업로드 중..." : "HTML 덱을 드래그하거나 클릭해 업로드"}
        </div>
        <div style={{ color: "var(--text-dim)", fontSize: 13, marginTop: 6 }}>
          단일 파일 .html · 썸네일은 자동 생성됩니다
        </div>
      </div>
    </label>
  );
}
