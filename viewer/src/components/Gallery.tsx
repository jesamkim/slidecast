import { useEffect, useState } from "react";
import type { Deck, Group } from "../types";
import type { createApi } from "../api";
import { DeckCard } from "./DeckCard";
import { Player } from "./Player";
import { VersionMenu } from "./VersionMenu";
import { UploadZone } from "./UploadZone";
import { GroupSidebar } from "./GroupSidebar";
import { ShareModal } from "./ShareModal";

type Api = ReturnType<typeof createApi>;

export interface GalleryProps {
  api: Api;
  onLogout: () => void;
}

export function Gallery({ api, onLogout }: GalleryProps) {
  const [decks, setDecks] = useState<Deck[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [status, setStatus] = useState<"active" | "archived">("active");
  const [query, setQuery] = useState("");
  const [playing, setPlaying] = useState<string | null>(null);
  const [versionsOf, setVersionsOf] = useState<Deck | null>(null);
  const [sharingOf, setSharingOf] = useState<Deck | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);

  const reload = async (
    s: "active" | "archived" = status,
    g: string | null = selectedGroup,
  ) => {
    setLoading(true);
    try {
      const groupParam = g === null ? undefined : g;
      const ds = await api.listDecks(s, groupParam);
      setDecks(ds);
    } finally {
      setLoading(false);
    }
  };

  const reloadGroups = async () => {
    try {
      const gs = await api.listGroups();
      setGroups(gs);
    } catch (err) {
      console.error("listGroups failed:", err);
    }
  };

  useEffect(() => {
    void reloadGroups();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void reload(status, selectedGroup);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, selectedGroup]);

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
      (d.tags ?? []).some((t) => t.toLowerCase().includes(q)) ||
      (d.alias ?? "").toLowerCase().includes(q),
  );

  const archived = status === "archived";

  const createGroup = async (name: string) => {
    try {
      await api.createGroup(name);
      await reloadGroups();
    } catch (err) {
      console.error("createGroup failed:", err);
      alert("그룹 생성 실패");
    }
  };

  const deleteGroup = async (groupId: string) => {
    try {
      await api.deleteGroup(groupId);
      if (selectedGroup === groupId) setSelectedGroup(null);
      await reloadGroups();
      void reload();
    } catch (err) {
      console.error("deleteGroup failed:", err);
      alert("그룹 삭제 실패");
    }
  };

  const moveGroup = async (deckId: string, groupId: string | null) => {
    await api.setGroup(deckId, groupId);
    void reload();
  };

  const download = async (deckId: string, format: "html" | "pdf", version?: number) => {
    try {
      const { downloadUrl } = await api.downloadUrl(deckId, format, version);
      const a = document.createElement("a");
      a.href = downloadUrl;
      a.rel = "noopener";
      a.click();
    } catch (err) {
      console.error("download failed:", err);
      alert("다운로드 실패");
    }
  };

  const setAlias = async (deckId: string, alias: string | null) => {
    // Let errors propagate so DeckCard can render inline (409/400) feedback.
    await api.setAlias(deckId, alias);
    void reload();
  };

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

      <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
        <GroupSidebar
          groups={groups}
          selected={selectedGroup}
          onSelect={setSelectedGroup}
          onCreate={createGroup}
          onDelete={deleteGroup}
        />

        <div style={{ flex: 1, minWidth: 0 }}>
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
                  groups={groups}
                  onPlay={() => play(d)}
                  onVersions={() => setVersionsOf(d)}
                  onMoveGroup={
                    archived ? undefined : (gid) => moveGroup(d.deckId, gid)
                  }
                  onSetAlias={
                    archived ? undefined : (a) => setAlias(d.deckId, a)
                  }
                  onShare={archived ? undefined : () => setSharingOf(d)}
                  onDownload={
                    archived ? undefined : (fmt) => download(d.deckId, fmt)
                  }
                  onRestore={
                    archived
                      ? async () => {
                          await api.restore(d.deckId);
                          void reload();
                        }
                      : undefined
                  }
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
        </div>
      </div>

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
              onDownload={(n, fmt) => download(versionsOf.deckId, fmt, n)}
            />
          </div>
        </div>
      )}

      {sharingOf && (
        <ShareModal
          deck={sharingOf}
          api={api}
          onClose={() => setSharingOf(null)}
          onChanged={async () => {
            await reload();
            // Refresh the modal's underlying deck reference so republish etc.
            // reflect the newest publicToken.
            const fresh = (await api.listDecks(status, selectedGroup === null ? undefined : selectedGroup))
              .find((d) => d.deckId === sharingOf.deckId);
            if (fresh) setSharingOf(fresh);
          }}
        />
      )}

      {playing && <Player src={playing} onClose={() => setPlaying(null)} />}
    </div>
  );
}
