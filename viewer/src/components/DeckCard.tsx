import { useState } from "react";
import type { Deck } from "../types";

export function DeckCard({
  deck,
  onPlay,
  onVersions,
  onDelete,
  archived,
}: {
  deck: Deck;
  onPlay: () => void;
  onVersions: () => void;
  onDelete: () => void;
  archived?: boolean;
}) {
  const [hover, setHover] = useState(false);
  const cur = deck.versions.find((v) => v.n === deck.currentVersion);
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        borderRadius: 18,
        overflow: "hidden",
        background: "var(--surface)",
        border: `1px solid ${hover ? "var(--border-strong)" : "var(--border)"}`,
        boxShadow: hover ? "var(--shadow-lg)" : "var(--shadow-md)",
        transform: hover ? "translateY(-3px)" : "translateY(0)",
        transition: "transform 260ms var(--ease, ease), box-shadow 260ms var(--ease, ease), border-color 260ms var(--ease, ease)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
      }}
    >
      <div
        onClick={onPlay}
        style={{
          cursor: "pointer",
          aspectRatio: "16 / 9",
          background: "#000",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {cur && (
          <img
            src={`/${cur.thumbnailKey}`}
            alt={deck.title}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              transform: hover ? "scale(1.03)" : "scale(1)",
              transition: "transform 420ms var(--ease, ease)",
            }}
          />
        )}
        <div
          style={{
            position: "absolute",
            inset: 0,
            background:
              "linear-gradient(180deg, rgba(0,0,0,0) 55%, rgba(0,0,0,0.55) 100%)",
            opacity: hover ? 1 : 0.75,
            transition: "opacity 260ms var(--ease, ease)",
            pointerEvents: "none",
          }}
        />
        {hover && (
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "grid",
              placeItems: "center",
              pointerEvents: "none",
            }}
          >
            <div
              style={{
                width: 64,
                height: 64,
                borderRadius: "50%",
                background: "rgba(255,255,255,0.14)",
                border: "1px solid rgba(255,255,255,0.28)",
                display: "grid",
                placeItems: "center",
                backdropFilter: "blur(14px)",
                WebkitBackdropFilter: "blur(14px)",
              }}
            >
              <div
                style={{
                  width: 0,
                  height: 0,
                  borderLeft: "14px solid #fff",
                  borderTop: "9px solid transparent",
                  borderBottom: "9px solid transparent",
                  marginLeft: 4,
                }}
              />
            </div>
          </div>
        )}
      </div>
      <div style={{ padding: "18px 18px 16px" }}>
        <div
          style={{
            fontSize: 18,
            fontWeight: 700,
            letterSpacing: "-0.01em",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {deck.title}
        </div>
        <div style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 6 }}>
          v{deck.currentVersion} · {deck.updatedAt}
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <button
            onClick={onPlay}
            style={{
              flex: 1,
              padding: "9px 14px",
              borderRadius: 10,
              border: "1px solid rgba(255,255,255,0.14)",
              background: "var(--grad)",
              color: "#fff",
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            재생
          </button>
          <button className="btn-ghost" onClick={onVersions} style={{ padding: "9px 14px", fontSize: 13 }}>
            버전
          </button>
          <button
            className="btn-ghost"
            onClick={onDelete}
            style={{ padding: "9px 14px", fontSize: 13, color: "var(--text-dim)" }}
            title={archived ? "영구 삭제" : "보관함으로"}
          >
            {archived ? "영구삭제" : "삭제"}
          </button>
        </div>
      </div>
    </div>
  );
}
