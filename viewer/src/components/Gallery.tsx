// Placeholder Gallery component. Task 10 replaces this with the real gallery UI.
// Kept minimal so App.tsx typechecks and builds before Task 10 lands.
import type { createApi } from "../api";

export interface GalleryProps {
  api: ReturnType<typeof createApi>;
  onLogout: () => void;
}

export function Gallery({ onLogout }: GalleryProps) {
  return (
    <div style={{ padding: 48 }}>
      <div className="h1" style={{ backgroundImage: "var(--grad)", WebkitBackgroundClip: "text", color: "transparent" }}>
        Slidecast
      </div>
      <p style={{ color: "var(--text-dim)" }}>갤러리는 Task 10에서 구현됩니다.</p>
      <button
        onClick={onLogout}
        style={{
          marginTop: 16,
          padding: "10px 20px",
          borderRadius: 10,
          border: "1px solid var(--border)",
          background: "var(--surface)",
          color: "var(--text)",
        }}
      >
        로그아웃
      </button>
    </div>
  );
}
