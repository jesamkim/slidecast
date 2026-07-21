import { useEffect, useState } from "react";
import { makeAuth, type CognitoConfig } from "./auth";
import { createApi } from "./api";
import { Gallery } from "./components/Gallery";

// Config injected at build time from CDK outputs (see scripts/deploy-viewer.sh).
const cfg: CognitoConfig = {
  region: import.meta.env.VITE_REGION ?? "us-east-1",
  userPoolId: import.meta.env.VITE_USER_POOL_ID ?? "",
  clientId: import.meta.env.VITE_CLIENT_ID ?? "",
  domain: import.meta.env.VITE_COGNITO_DOMAIN ?? "",
};
const apiBase = import.meta.env.VITE_API_BASE ?? "";
const auth = makeAuth(cfg);

export function App() {
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        await auth.init();
        await auth.handleCallback();
        setAuthed(auth.isAuthenticated());
      } catch (err) {
        // Auth callback / init failed (bad state, network, etc). Clear stale
        // oidc state and the URL, then drop back to the login screen instead of
        // hanging on "로딩 중..." (and avoid failing on every reload).
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
  return <Gallery api={api} onLogout={() => auth.logout()} />;
}
