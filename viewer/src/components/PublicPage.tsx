import { useEffect, useState } from "react";
import { fetchPublic } from "../api";
import type { PublicDeck } from "../types";

type State =
  | { kind: "loading" }
  | { kind: "ok"; deck: PublicDeck }
  | { kind: "not-found" }
  | { kind: "error" };

export function PublicPage({ token, baseUrl }: { token: string; baseUrl: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const deck = await fetchPublic(baseUrl, token);
        if (!cancelled) setState({ kind: "ok", deck });
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        if (msg.includes("404")) setState({ kind: "not-found" });
        else setState({ kind: "error" });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [baseUrl, token]);

  if (state.kind === "loading") {
    return (
      <div style={{ display: "grid", placeItems: "center", height: "100%" }}>
        <div style={{ color: "var(--text-dim)", fontSize: 14 }}>불러오는 중...</div>
      </div>
    );
  }

  if (state.kind === "not-found") {
    return (
      <div
        style={{
          display: "grid",
          placeItems: "center",
          height: "100%",
          padding: 24,
        }}
      >
        <div style={{ textAlign: "center", maxWidth: 520 }}>
          <div
            className="grad-text"
            style={{ fontSize: 44, fontWeight: 800, letterSpacing: "-0.03em" }}
          >
            링크 만료
          </div>
          <p style={{ color: "var(--text-dim)", marginTop: 16, fontSize: 16 }}>
            만료되었거나 존재하지 않는 링크입니다.
          </p>
        </div>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div
        style={{
          display: "grid",
          placeItems: "center",
          height: "100%",
          padding: 24,
        }}
      >
        <div style={{ textAlign: "center", maxWidth: 520 }}>
          <div
            className="grad-text"
            style={{ fontSize: 44, fontWeight: 800, letterSpacing: "-0.03em" }}
          >
            불러오기 실패
          </div>
          <p style={{ color: "var(--text-dim)", marginTop: 16, fontSize: 16 }}>
            슬라이드를 불러오지 못했습니다. 링크가 만료되었거나 잘못되었을 수 있습니다.
          </p>
        </div>
      </div>
    );
  }

  const { deck } = state;
  return (
    <div style={{ position: "fixed", inset: 0, background: "#000" }}>
      <div
        style={{
          position: "absolute",
          top: 16,
          left: 20,
          zIndex: 10,
          padding: "6px 12px",
          borderRadius: 999,
          background: "rgba(10,10,18,0.6)",
          border: "1px solid rgba(255,255,255,0.14)",
          color: "#fff",
          fontSize: 12,
          letterSpacing: "-0.005em",
          backdropFilter: "blur(14px)",
          WebkitBackdropFilter: "blur(14px)",
          maxWidth: "60vw",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
        title={deck.title}
      >
        {deck.title}
      </div>
      {/*
        Public viewer: same sandbox posture as the authenticated Player.
        We grant `allow-scripts` so decks can run inline nav/animation, but
        deliberately omit `allow-same-origin` so decks can't reach parent
        storage or DOM. Public pages carry no auth secrets, but the invariant
        stays uniform with Player.
      */}
      <iframe
        title="deck"
        src={deck.htmlUrl}
        sandbox="allow-scripts"
        style={{ width: "100%", height: "100%", border: "none", background: "#000" }}
      />
    </div>
  );
}
