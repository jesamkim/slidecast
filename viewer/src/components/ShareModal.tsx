import { useRef, useState } from "react";
import type { Deck } from "../types";
import type { createApi } from "../api";

type Api = ReturnType<typeof createApi>;

function publicUrl(token: string): string {
  return `${window.location.origin}/p/${token}`;
}

export function ShareModal({
  deck,
  api,
  onClose,
  onChanged,
}: {
  deck: Deck;
  api: Api;
  onClose: () => void;
  onChanged: () => void | Promise<void>;
}) {
  const [token, setToken] = useState<string | null>(deck.publicToken ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // Guard share/unshare/republish from double-submit (Enter, blur, rapid clicks).
  const submitting = useRef(false);

  const runGuarded = async (fn: () => Promise<void>) => {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  };

  const share = () =>
    runGuarded(async () => {
      const { token: t } = await api.share(deck.deckId);
      setToken(t);
      await onChanged();
    });

  const republish = () =>
    runGuarded(async () => {
      const { token: t } = await api.republish(deck.deckId);
      setToken(t);
      setCopied(false);
      await onChanged();
    });

  const unshare = () =>
    runGuarded(async () => {
      if (!confirm("공유를 해제하시겠습니까? 기존 링크는 즉시 무효화됩니다.")) return;
      await api.unshare(deck.deckId);
      setToken(null);
      setCopied(false);
      await onChanged();
    });

  const copy = async () => {
    if (!token) return;
    try {
      await navigator.clipboard.writeText(publicUrl(token));
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setError("복사 실패");
    }
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(3,3,8,0.72)",
        display: "grid",
        placeItems: "center",
        zIndex: 60,
        backdropFilter: "blur(6px)",
        WebkitBackdropFilter: "blur(6px)",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg-2)",
          padding: 28,
          borderRadius: 20,
          border: "1px solid var(--border)",
          boxShadow: "var(--shadow-lg)",
          minWidth: 480,
          maxWidth: 560,
        }}
      >
        <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-0.01em" }}>
          공유
        </div>
        <div style={{ color: "var(--text-dim)", fontSize: 13, marginTop: 6 }}>
          {deck.title}
        </div>

        {token ? (
          <div style={{ marginTop: 20, display: "grid", gap: 12 }}>
            <label
              style={{ color: "var(--text-dim)", fontSize: 12, letterSpacing: "0.02em" }}
            >
              공개 링크
            </label>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                readOnly
                value={publicUrl(token)}
                onFocus={(e) => e.currentTarget.select()}
                style={{
                  flex: 1,
                  padding: "10px 12px",
                  borderRadius: 10,
                  border: "1px solid var(--border)",
                  background: "var(--bg-2)",
                  color: "var(--text)",
                  fontSize: 13,
                  fontFamily: "var(--font-mono)",
                  outline: "none",
                }}
              />
              <button
                className="btn-ghost"
                onClick={copy}
                style={{ padding: "8px 14px", fontSize: 13 }}
              >
                {copied ? "복사됨" : "복사"}
              </button>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
              <button
                className="btn-ghost"
                onClick={republish}
                disabled={busy}
                style={{ padding: "9px 14px", fontSize: 13 }}
                title="새 토큰을 발급하고 기존 링크를 무효화합니다"
              >
                재발행
              </button>
              <button
                className="btn-ghost"
                onClick={unshare}
                disabled={busy}
                style={{
                  padding: "9px 14px",
                  fontSize: 13,
                  color: "#ff8a8a",
                }}
              >
                공유 해제
              </button>
              <div style={{ flex: 1 }} />
              <button
                className="btn-ghost"
                onClick={onClose}
                style={{ padding: "9px 14px", fontSize: 13 }}
              >
                닫기
              </button>
            </div>
          </div>
        ) : (
          <div style={{ marginTop: 20, display: "grid", gap: 12 }}>
            <p style={{ color: "var(--text-dim)", fontSize: 13, margin: 0 }}>
              공개 링크를 발급하면 로그인 없이도 이 덱을 볼 수 있습니다.
            </p>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={share}
                disabled={busy}
                style={{
                  padding: "10px 18px",
                  borderRadius: 10,
                  border: "1px solid rgba(255,255,255,0.14)",
                  background: "var(--grad)",
                  color: "#fff",
                  fontSize: 13,
                  fontWeight: 600,
                }}
              >
                공유하기
              </button>
              <div style={{ flex: 1 }} />
              <button
                className="btn-ghost"
                onClick={onClose}
                style={{ padding: "9px 14px", fontSize: 13 }}
              >
                닫기
              </button>
            </div>
          </div>
        )}

        {error && (
          <div style={{ color: "#ff8a8a", fontSize: 12, marginTop: 12 }}>{error}</div>
        )}
      </div>
    </div>
  );
}
