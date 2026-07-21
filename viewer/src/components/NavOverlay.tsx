import { useEffect, useRef, useState } from "react";

type Props = { iframeRef: React.RefObject<HTMLIFrameElement> };

export function NavOverlay({ iframeRef }: Props) {
  const [state, setState] = useState<{ cur: number; total: number } | null>(null);
  const [visible, setVisible] = useState(true);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Receive slidecast-state from the iframe (validated by source).
  useEffect(() => {
    const onMsg = (e: MessageEvent) => {
      const d = e.data;
      if (!d || d.type !== "slidecast-state") return;
      if (e.source !== iframeRef.current?.contentWindow) return;
      if (typeof d.cur !== "number" || typeof d.total !== "number") return;
      setState({ cur: d.cur, total: d.total });
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [iframeRef]);

  // Handshake: ping a few times after mount; if no state arrives, overlay
  // stays hidden (unsupported deck).
  useEffect(() => {
    let n = 0;
    const id = setInterval(() => {
      n += 1;
      iframeRef.current?.contentWindow?.postMessage(
        { type: "slidecast-nav", action: "ping" }, "*"
      );
      if (n >= 5) clearInterval(id);
    }, 200);
    return () => clearInterval(id);
  }, [iframeRef]);

  // Auto-hide: show on pointer/touch activity, hide after 2.5s idle.
  useEffect(() => {
    const wake = () => {
      setVisible(true);
      if (hideTimer.current) clearTimeout(hideTimer.current);
      hideTimer.current = setTimeout(() => setVisible(false), 2500);
    };
    wake();
    window.addEventListener("mousemove", wake);
    window.addEventListener("touchstart", wake);
    window.addEventListener("keydown", wake);
    return () => {
      window.removeEventListener("mousemove", wake);
      window.removeEventListener("touchstart", wake);
      window.removeEventListener("keydown", wake);
      if (hideTimer.current) clearTimeout(hideTimer.current);
    };
  }, []);

  if (!state) return null; // unsupported deck → no overlay

  const send = (action: "next" | "prev") =>
    iframeRef.current?.contentWindow?.postMessage(
      { type: "slidecast-nav", action }, "*"
    );

  const atFirst = state.cur <= 1;
  const atLast = state.cur >= state.total;

  return (
    <div
      style={{
        position: "absolute", left: "50%", bottom: 24,
        transform: "translateX(-50%)", zIndex: 105,
        display: "flex", alignItems: "center", gap: 20,
        padding: "10px 18px", borderRadius: 999,
        background: "rgba(10,10,18,0.62)",
        border: "1px solid rgba(255,255,255,0.14)",
        backdropFilter: "blur(16px)", WebkitBackdropFilter: "blur(16px)",
        opacity: visible ? 1 : 0,
        transition: "opacity 200ms ease",
        pointerEvents: visible ? "auto" : "none",
      }}
    >
      <button aria-label="이전 슬라이드" onClick={() => send("prev")}
        disabled={atFirst}
        style={navBtn(atFirst)}>‹</button>
      <span data-testid="nav-counter"
        style={{ color: "#fff", fontSize: 15, fontVariantNumeric: "tabular-nums", minWidth: 72, textAlign: "center" }}>
        {state.cur} / {state.total}
      </span>
      <button aria-label="다음 슬라이드" onClick={() => send("next")}
        disabled={atLast}
        style={navBtn(atLast)}>›</button>
    </div>
  );
}

function navBtn(disabled: boolean): React.CSSProperties {
  return {
    width: 44, height: 44, borderRadius: "50%",
    border: "1px solid rgba(255,255,255,0.16)",
    background: "rgba(255,255,255,0.06)",
    color: "#fff", fontSize: 24, lineHeight: 1,
    cursor: disabled ? "default" : "pointer",
    opacity: disabled ? 0.3 : 1,
  };
}
