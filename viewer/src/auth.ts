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
    userStore: new WebStorageStateStore({ store: window.localStorage }),
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
    logout: () => mgr.signoutRedirect(),
    getToken: () => user?.id_token ?? "",
    isAuthenticated: () => !!user && !user.expired,
  };
}
