import type { Deck } from "../types";

export function VersionMenu({
  deck,
  onRollback,
  onPlayVersion,
}: {
  deck: Deck;
  onRollback: (n: number) => void;
  onPlayVersion: (n: number) => void;
}) {
  return (
    <div style={{ display: "grid", gap: 10, minWidth: 480 }}>
      <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-0.01em", marginBottom: 6 }}>
        버전 히스토리
      </div>
      {deck.versions
        .slice()
        .reverse()
        .map((v) => {
          const isCurrent = v.n === deck.currentVersion;
          return (
            <div
              key={v.n}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 14,
                padding: 12,
                borderRadius: 12,
                border: `1px solid ${isCurrent ? "var(--border-strong)" : "var(--border)"}`,
                background: isCurrent ? "var(--surface-strong)" : "var(--surface)",
              }}
            >
              {v.thumbnailKey ? (
                <img
                  src={`/${v.thumbnailKey}`}
                  alt=""
                  width={112}
                  style={{
                    borderRadius: 8,
                    aspectRatio: "16 / 9",
                    objectFit: "cover",
                    background: "#000",
                  }}
                />
              ) : (
                // Thumbnail not generated yet; avoid a "/null" request.
                <div
                  style={{
                    width: 112,
                    borderRadius: 8,
                    aspectRatio: "16 / 9",
                    display: "grid",
                    placeItems: "center",
                    background:
                      "linear-gradient(135deg, var(--surface) 0%, var(--surface-strong, #14141c) 100%)",
                    color: "var(--text-dim)",
                    fontSize: 11,
                  }}
                >
                  생성 중...
                </div>
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 15 }}>
                  v{v.n}
                  {isCurrent && (
                    <span
                      style={{
                        marginLeft: 8,
                        fontSize: 11,
                        padding: "2px 8px",
                        borderRadius: 999,
                        background: "var(--grad-soft)",
                        color: "var(--text)",
                        letterSpacing: "0.02em",
                        textTransform: "uppercase",
                        fontWeight: 600,
                      }}
                    >
                      현재
                    </span>
                  )}
                </div>
                <div style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 4 }}>
                  {v.createdAt}
                </div>
              </div>
              <button
                className="btn-ghost"
                onClick={() => onPlayVersion(v.n)}
                style={{ padding: "8px 14px", fontSize: 13 }}
              >
                재생
              </button>
              {!isCurrent && (
                <button
                  onClick={() => onRollback(v.n)}
                  style={{
                    padding: "8px 14px",
                    borderRadius: 10,
                    border: "1px solid rgba(255,255,255,0.14)",
                    background: "var(--grad)",
                    color: "#fff",
                    fontSize: 13,
                    fontWeight: 600,
                  }}
                >
                  이 버전으로
                </button>
              )}
            </div>
          );
        })}
    </div>
  );
}
