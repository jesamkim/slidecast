import { describe, it, expect } from "vitest";
import { buildAuthConfig } from "./auth";

describe("auth config", () => {
  it("builds cognito authority and redirect", () => {
    const c = buildAuthConfig({
      region: "us-east-1",
      userPoolId: "us-east-1_ABC",
      clientId: "cid",
      domain: "d.example.com",
    });
    expect(c.authority).toContain("cognito-idp.us-east-1.amazonaws.com/us-east-1_ABC");
    expect(c.client_id).toBe("cid");
    expect(c.redirect_uri).toContain(window.location.origin);
  });

  it("stores oidc state in sessionStorage, not localStorage", () => {
    const c = buildAuthConfig({
      region: "us-east-1",
      userPoolId: "us-east-1_ABC",
      clientId: "cid",
      domain: "d.example.com",
    });
    // The WebStorageStateStore keeps its backing store on `_store`. We assert
    // it points at sessionStorage so id_tokens don't survive the tab session.
    const store = (c.userStore as unknown as { _store: Storage })._store;
    expect(store).toBe(window.sessionStorage);
    expect(store).not.toBe(window.localStorage);
  });
});
