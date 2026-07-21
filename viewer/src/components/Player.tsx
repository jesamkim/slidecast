import { useEffect, useRef } from "react";

export function Player({ src, onClose }: { src: string; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div
      ref={ref}
      tabIndex={-1}
      style={{
        position: "fixed",
        inset: 0,
        background: "#000",
        zIndex: 100,
        animation: "sc-fade 200ms var(--ease, ease)",
      }}
    >
      <button
        onClick={onClose}
        style={{
          position: "absolute",
          top: 20,
          right: 20,
          zIndex: 101,
          padding: "10px 18px",
          borderRadius: 12,
          border: "1px solid rgba(255,255,255,0.14)",
          background: "rgba(20,20,28,0.7)",
          color: "var(--text)",
          fontSize: 13,
          fontWeight: 500,
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
        }}
      >
        닫기 (ESC)
      </button>
      <iframe
        title="deck"
        src={src}
        style={{ width: "100%", height: "100%", border: "none", background: "#000" }}
      />
    </div>
  );
}
