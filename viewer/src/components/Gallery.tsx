import { useEffect, useState } from "react";
import type { Deck } from "../types";
import type { createApi } from "../api";
import { DeckCard } from "./DeckCard";
import { Player } from "./Player";
import { VersionMenu } from "./VersionMenu";
import { UploadZone } from "./UploadZone";

type Api = ReturnType<typeof createApi>;

export interface GalleryProps {
  api: Api;
  onLogout: () => void;
}

export function Gallery({ api, onLogout }: GalleryProps) {
  const [decks, setDecks] = useState<Deck[]>([]);
  const [status, setStatus] = useState<"active" | "archived">("active");
  const [query, setQuery] = useState("");
  const [playing, setPlaying] = useState<string | null>(null);
  const [versionsOf, setVersionsOf] = useState<Deck | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = async (s: "active" | "archived" = status) => {
    setLoading(true);
    try {
      const ds = await api.listDecks(s);
      setDecks(ds);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void reload(status);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  const upload = async (file: File) => {
    const title = file.name.replace(/\.html?$/i, "");
    const { uploadUrl } = await api.createUpload(file.name, title);
    await api.uploadFile(uploadUrl, file);
    setTimeout(() => {
      void reload();
    }, 2500);
  };

  const play = (d: Deck) =>
    setPlaying(`/slides/${d.deckId}/v${d.currentVersion}/index.html`);

  const q = query.toLowerCase();
  const shown = decks.filter(
    (d) =>
      d.title.toLowerCase().includes(q) ||
      (d.tags ?? []).some((t) => t.toLowerCase().includes(q)),
  );

  const archived = status === "archived";

  return (
    <div style={{ padding: "32px 40px 80px", maxWidth: 1440, margin: "0 auto" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          marginBottom: 28,
          flexWrap: "wrap",
        }}
      >
        <div
          className="grad-text"
          style={{ fontSize: 34, fontWeight: 800, letterSpacing: "-0.03em" }}
        >
          Slidecast
        </div>
        <div
          style={{
            color: "var(--text-dim)",
            fontSize: 13,
            marginLeft: 4,
            marginTop: 4,
          }}
        >
          {archived ? "보관함" : "활성 덱"}
          {!loading && ` · ${shown.length}`}
        </div>
        <div style={{ flex: 1 }} />
        <input
          placeholder="검색"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{
            padding: "10px 16px",
            borderRadius: 12,
            border: "1px solid var(--border)",
            background: "var(--surface)",
            color: "var(--text)",
            fontSize: 14,
            minWidth: 240,
            outline: "none",
          }}
        />
        <button
          className="btn-ghost"
          onClick={() => setStatus(archived ? "active" : "archived")}
        >
          {archived ? "활성" : "보관함"}
        </button>
        <button className="btn-ghost" onClick={onLogout}>
          로그아웃
        </button>
      </header>

      {!archived && (
        <div style={{ marginBottom: 32 }}>
          <UploadZone onUpload={upload} />
        </div>
      )}

      {loading && decks.length === 0 ? (
        <div style={{ color: "var(--text-dim)", padding: 40, textAlign: "center" }}>
          불러오는 중...
        </div>
      ) : shown.length === 0 ? (
        <div
          style={{
            color: "var(--text-dim)",
            padding: 60,
            textAlign: "center",
            border: "1px dashed var(--border)",
            borderRadius: 16,
          }}
        >
          {archived
            ? "보관된 덱이 없습니다."
            : "아직 덱이 없습니다. HTML을 업로드해 시작하세요."}
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
            gap: 24,
          }}
        >
          {shown.map((d) => (
            <DeckCard
              key={d.deckId}
              deck={d}
              archived={archived}
              onPlay={() => play(d)}
              onVersions={() => setVersionsOf(d)}
              onDelete={async () => {
                if (archived) {
                  if (!confirm(`${d.title}을(를) 영구 삭제할까요?`)) return;
                  await api.hardDelete(d.deckId);
                } else {
                  await api.softDelete(d.deckId);
                }
                void reload();
              }}
            />
          ))}
        </div>
      )}

      {versionsOf && (
        <div
          onClick={() => setVersionsOf(null)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(3,3,8,0.72)",
            display: "grid",
            placeItems: "center",
            zIndex: 50,
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
              maxHeight: "84vh",
              overflow: "auto",
            }}
          >
            <VersionMenu
              deck={versionsOf}
              onRollback={async (n) => {
                await api.setCurrent(versionsOf.deckId, n);
                setVersionsOf(null);
                void reload();
              }}
              onPlayVersion={(n) => {
                setPlaying(`/slides/${versionsOf.deckId}/v${n}/index.html`);
                setVersionsOf(null);
              }}
            />
          </div>
        </div>
      )}

      {playing && <Player src={playing} onClose={() => setPlaying(null)} />}
    </div>
  );
}
