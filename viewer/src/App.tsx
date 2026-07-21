import { useEffect, useState } from "react";
import { makeAuth, type CognitoConfig } from "./auth";
import { createApi } from "./api";
import { Gallery } from "./components/Gallery";
import { Player } from "./components/Player";
import type { Deck } from "./types";

// Config injected at build time from CDK outputs (see scripts/deploy-viewer.sh).
const cfg: CognitoConfig = {
  region: import.meta.env.VITE_REGION ?? "us-east-1",
  userPoolId: import.meta.env.VITE_USER_POOL_ID ?? "",
  clientId: import.meta.env.VITE_CLIENT_ID ?? "",
  domain: import.meta.env.VITE_COGNITO_DOMAIN ?? "",
};
const apiBase = import.meta.env.VITE_API_BASE ?? "";
const auth = makeAuth(cfg);

// Detect a /s/{alias} deep link once at load; the alias is preserved through
// the auth roundtrip because Cognito returns to the original path.
const aliasMatch = window.location.pathname.match(/^\/s\/([^/]+)$/);
const initialAlias = aliasMatch ? aliasMatch[1] : null;

export function App() {
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [aliasDeck, setAliasDeck] = useState<Deck | null>(null);
  const [aliasError, setAliasError] = useState<string | null>(null);
  const [aliasLoading, setAliasLoading] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        await auth.init();
        await auth.handleCallback();
        setAuthed(auth.isAuthenticated());
      } catch (err) {
        console.error("auth bootstrap failed:", err);
        try {
          await auth.reset();
        } catch (resetErr) {
          console.error("auth reset failed:", resetErr);
        }
        window.history.replaceState({}, "", "/");
        setAuthed(false);
      } finally {
        setReady(true);
      }
    })();
  }, []);

  useEffect(() => {
    if (!ready || !authed || !initialAlias) return;
    const api = createApi(apiBase, () => auth.getToken());
    setAliasLoading(true);
    (async () => {
      try {
        const d = await api.resolve(initialAlias);
        setAliasDeck(d);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setAliasError(msg.includes("404") ? "not-found" : "error");
      } finally {
        setAliasLoading(false);
      }
    })();
  }, [ready, authed]);

  if (!ready) {
    return (
      <div style={{ display: "grid", placeItems: "center", height: "100%" }}>
        <div style={{ color: "var(--text-dim)", fontSize: 14 }}>로딩 중...</div>
      </div>
    );
  }

  if (!authed) {
    return (
      <div style={{ display: "grid", placeItems: "center", height: "100%", padding: 24 }}>
        <div style={{ textAlign: "center", maxWidth: 520 }}>
          <div className="h1 grad-text">Slidecast</div>
          <p style={{ color: "var(--text-dim)", marginTop: 16, fontSize: 18, letterSpacing: "-0.005em" }}>
            HTML 슬라이드 시네마
          </p>
          <button className="btn-primary" style={{ marginTop: 36 }} onClick={() => auth.login()}>
            로그인
          </button>
        </div>
      </div>
    );
  }

  const api = createApi(apiBase, () => auth.getToken());

  if (initialAlias) {
    if (aliasLoading) {
      return (
        <div style={{ display: "grid", placeItems: "center", height: "100%" }}>
          <div style={{ color: "var(--text-dim)", fontSize: 14 }}>불러오는 중...</div>
        </div>
      );
    }
    if (aliasError) {
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
              찾을 수 없음
            </div>
            <p style={{ color: "var(--text-dim)", marginTop: 16, fontSize: 16 }}>
              alias{" "}
              <code style={{ fontFamily: "var(--font-mono)", color: "var(--accent)" }}>
                /s/{initialAlias}
              </code>
              에 해당하는 덱이 없습니다.
            </p>
            <a
              href="/"
              style={{
                display: "inline-block",
                marginTop: 28,
                padding: "10px 22px",
                borderRadius: 12,
                border: "1px solid var(--border-strong)",
                background: "var(--surface)",
                color: "var(--text)",
                fontSize: 14,
                textDecoration: "none",
              }}
            >
              갤러리로
            </a>
          </div>
        </div>
      );
    }
    if (aliasDeck) {
      const src = `/slides/${aliasDeck.deckId}/v${aliasDeck.currentVersion}/index.html`;
      return (
        <Player
          src={src}
          onClose={() => {
            window.history.replaceState({}, "", "/");
            window.location.reload();
          }}
        />
      );
    }
  }

  return <Gallery api={api} onLogout={() => auth.logout()} />;
}
