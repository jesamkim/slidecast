import { useRef, useState } from "react";
import type { Deck, Group } from "../types";
import { formatDate } from "../format";

export function DeckCard({
  deck,
  onPlay,
  onVersions,
  onDelete,
  onRestore,
  archived,
  groups,
  onMoveGroup,
  onSetAlias,
}: {
  deck: Deck;
  onPlay: () => void;
  onVersions: () => void;
  onDelete: () => void;
  onRestore?: () => void;
  archived?: boolean;
  groups?: Group[];
  onMoveGroup?: (groupId: string | null) => void | Promise<void>;
  onSetAlias?: (alias: string | null) => void | Promise<void>;
}) {
  const [hover, setHover] = useState(false);
  const [editingAlias, setEditingAlias] = useState(false);
  const [aliasDraft, setAliasDraft] = useState(deck.alias ?? "");
  const [aliasError, setAliasError] = useState<string | null>(null);
  const [aliasBusy, setAliasBusy] = useState(false);
  // Enter (onKeyDown) and click-away (onBlur) can both trigger a submit; this
  // ref guards against the Enter-then-blur double fire (unmount fires blur).
  const submittingAlias = useRef(false);
  const cur = deck.versions.find((v) => v.n === deck.currentVersion);
  const alias = deck.alias ?? null;
  const group = deck.group ?? null;

  const submitAlias = async () => {
    if (!onSetAlias) return;
    // Enter already kicked off (or completed) a submit; skip the blur echo.
    if (submittingAlias.current) return;
    const raw = aliasDraft.trim();
    const next = raw === "" ? null : raw;
    if (next === alias) {
      setEditingAlias(false);
      setAliasError(null);
      return;
    }
    submittingAlias.current = true;
    setAliasBusy(true);
    setAliasError(null);
    try {
      await onSetAlias(next);
      setEditingAlias(false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("409")) setAliasError("이미 사용 중인 alias 입니다");
      else if (msg.includes("400")) setAliasError("잘못된 alias 형식");
      else setAliasError("alias 설정 실패");
    } finally {
      submittingAlias.current = false;
      setAliasBusy(false);
    }
  };

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
        {cur?.thumbnailKey ? (
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
        ) : (
          <div
            style={{
              width: "100%",
              height: "100%",
              display: "grid",
              placeItems: "center",
              background:
                "linear-gradient(135deg, var(--surface) 0%, var(--surface-strong, #14141c) 100%)",
              color: "var(--text-dim)",
              fontSize: 13,
              letterSpacing: "0.02em",
            }}
          >
            생성 중...
          </div>
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
        {alias && (
          <div
            style={{
              position: "absolute",
              top: 10,
              left: 10,
              padding: "3px 9px",
              borderRadius: 999,
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: "0.02em",
              color: "#fff",
              background: "rgba(10,10,18,0.6)",
              border: "1px solid rgba(255,255,255,0.18)",
              backdropFilter: "blur(10px)",
              WebkitBackdropFilter: "blur(10px)",
            }}
            title={`/s/${alias}`}
          >
            /s/{alias}
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
          v{deck.currentVersion} · {formatDate(deck.updatedAt)}
        </div>

        {!archived && (onMoveGroup || onSetAlias) && (
          <div
            style={{
              display: "grid",
              gap: 8,
              marginTop: 12,
              padding: "10px 12px",
              borderRadius: 12,
              background: "rgba(255,255,255,0.02)",
              border: "1px solid var(--border)",
            }}
          >
            {onMoveGroup && groups && (
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 12,
                  color: "var(--text-dim)",
                }}
              >
                <span style={{ minWidth: 40 }}>그룹</span>
                <select
                  value={group ?? ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    void onMoveGroup(v === "" ? null : v);
                  }}
                  style={{
                    flex: 1,
                    padding: "6px 8px",
                    borderRadius: 8,
                    border: "1px solid var(--border)",
                    background: "var(--bg-2)",
                    color: "var(--text)",
                    fontSize: 12,
                    outline: "none",
                  }}
                >
                  <option value="">미분류</option>
                  {groups.map((g) => (
                    <option key={g.groupId} value={g.groupId}>
                      {g.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {onSetAlias && (
              <div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 12,
                    color: "var(--text-dim)",
                  }}
                >
                  <span style={{ minWidth: 40 }}>alias</span>
                  {editingAlias ? (
                    <input
                      autoFocus
                      value={aliasDraft}
                      onChange={(e) => setAliasDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void submitAlias();
                        else if (e.key === "Escape") {
                          setAliasDraft(alias ?? "");
                          setEditingAlias(false);
                          setAliasError(null);
                        }
                      }}
                      onBlur={() => void submitAlias()}
                      placeholder="예: roadmap"
                      disabled={aliasBusy}
                      style={{
                        flex: 1,
                        padding: "6px 8px",
                        borderRadius: 8,
                        border: `1px solid ${aliasError ? "#ff6a6a" : "var(--border)"}`,
                        background: "var(--bg-2)",
                        color: "var(--text)",
                        fontSize: 12,
                        fontFamily: "var(--font-mono)",
                        outline: "none",
                      }}
                    />
                  ) : (
                    <>
                      <span
                        style={{
                          flex: 1,
                          fontFamily: "var(--font-mono)",
                          color: alias ? "var(--accent)" : "var(--text-muted)",
                        }}
                      >
                        {alias ?? "없음"}
                      </span>
                      <button
                        className="btn-ghost"
                        onClick={() => {
                          setAliasDraft(alias ?? "");
                          setEditingAlias(true);
                        }}
                        style={{ padding: "4px 10px", fontSize: 11 }}
                      >
                        편집
                      </button>
                    </>
                  )}
                </div>
                {aliasError && (
                  <div
                    style={{
                      color: "#ff8a8a",
                      fontSize: 11,
                      marginTop: 6,
                      paddingLeft: 48,
                    }}
                  >
                    {aliasError}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

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
          {archived && onRestore && (
            <button
              className="btn-ghost"
              onClick={onRestore}
              style={{ padding: "9px 14px", fontSize: 13 }}
              title="활성으로 복원"
            >
              복원
            </button>
          )}
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
