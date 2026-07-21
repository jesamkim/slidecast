import { UserManager, WebStorageStateStore, type User } from "oidc-client-ts";

export interface CognitoConfig {
  region: string;
  userPoolId: string;
  clientId: string;
  /**
   * Cognito Hosted UI domain prefix (e.g. "slidecast-abc123").
   * The full Hosted UI URL is derived as
   *   https://{prefix}.auth.{region}.amazoncognito.com
   * The domain field also accepts a full custom domain (e.g. "auth.example.com").
   * It is not used for OIDC discovery (that uses the cognito-idp issuer authority),
   * but is retained here for callers that need to construct logout / Hosted UI URLs.
   */
  domain: string;
}

/**
 * Key under which we stash the alias of a /s/{alias} deep link before kicking
 * off the Cognito login redirect. Cognito's redirect_uri is fixed to the app
 * origin ("/"), so the path segment is lost across the roundtrip. We stash
 * the alias in sessionStorage (which survives the same-tab OAuth redirect) so
 * the app can resume the deep link once auth completes.
 */
export const PENDING_ALIAS_KEY = "slidecast:pendingAlias";

const ALIAS_PATH_RE = /^\/s\/([^/]+)$/;

/**
 * Given the current URL pathname and a Storage backend, return the alias the
 * app should resolve and play, or null for the gallery.
 *
 * - If pathname is /s/{alias}, that alias wins (fresh deep-link visit).
 * - Otherwise, if a pending alias was stashed pre-login, consume it (read +
 *   remove) and return it. This is the post-login roundtrip case, where
 *   Cognito has bounced the user back to "/".
 * - Otherwise, return null.
 *
 * Pure w.r.t. inputs (aside from consuming storage), so it's directly
 * unit-testable without mounting the app.
 */
export function resolvePendingAlias(pathname: string, storage: Storage): string | null {
  const m = pathname.match(ALIAS_PATH_RE);
  if (m) return m[1];
  const stashed = storage.getItem(PENDING_ALIAS_KEY);
  if (stashed) {
    storage.removeItem(PENDING_ALIAS_KEY);
    return stashed;
  }
  return null;
}

export function cognitoHostedUiUrl(c: CognitoConfig): string {
  if (c.domain.includes(".")) return `https://${c.domain}`;
  return `https://${c.domain}.auth.${c.region}.amazoncognito.com`;
}

export function buildAuthConfig(c: CognitoConfig) {
  return {
    authority: `https://cognito-idp.${c.region}.amazonaws.com/${c.userPoolId}`,
    client_id: c.clientId,
    redirect_uri: `${window.location.origin}/`,
    post_logout_redirect_uri: `${window.location.origin}/`,
    response_type: "code",
    scope: "openid email",
    // Store tokens in sessionStorage (per-tab, cleared on tab close) rather than
    // localStorage. This limits the id_token's exposure window and reduces the
    // blast radius if any script running on this origin reads storage.
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  };
}

export function makeAuth(c: CognitoConfig) {
  const mgr = new UserManager(buildAuthConfig(c));
  let user: User | null = null;
  return {
    async init() {
      user = await mgr.getUser();
    },
    async handleCallback() {
      if (window.location.search.includes("code=")) {
        user = await mgr.signinRedirectCallback();
        window.history.replaceState({}, "", "/");
      }
    },
    login: () => mgr.signinRedirect(),
    logout: async () => {
      // Cognito's OIDC discovery doesn't publish end_session_endpoint, so
      // mgr.signoutRedirect() fails. Clear the local user, then redirect to
      // the Hosted UI /logout which clears the Cognito session and bounces
      // back to the origin.
      try {
        await mgr.removeUser();
      } catch {
        // ignore — we're leaving the page anyway
      }
      const base = cognitoHostedUiUrl(c);
      const url = `${base}/logout?client_id=${encodeURIComponent(c.clientId)}&logout_uri=${encodeURIComponent(window.location.origin + "/")}`;
      window.location.assign(url);
    },
    async reset() {
      // Drop any corrupted / stale oidc state so a broken bootstrap doesn't
      // fail on every subsequent reload.
      await mgr.clearStaleState();
      await mgr.removeUser();
      user = null;
    },
    getToken: () => user?.id_token ?? "",
    isAuthenticated: () => !!user && !user.expired,
  };
}
