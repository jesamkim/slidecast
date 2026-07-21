import { describe, it, expect, beforeEach } from "vitest";
import { buildAuthConfig, resolvePendingAlias, PENDING_ALIAS_KEY } from "./auth";

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

describe("resolvePendingAlias", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("returns alias from a /s/{alias} pathname", () => {
    expect(resolvePendingAlias("/s/road", window.sessionStorage)).toBe("road");
  });

  it("returns the stored pendingAlias when path is /", () => {
    window.sessionStorage.setItem(PENDING_ALIAS_KEY, "road");
    expect(resolvePendingAlias("/", window.sessionStorage)).toBe("road");
  });

  it("returns null when there is no path alias and nothing stored", () => {
    expect(resolvePendingAlias("/", window.sessionStorage)).toBeNull();
    expect(resolvePendingAlias("/other", window.sessionStorage)).toBeNull();
  });

  it("consumes (removes) the stored pendingAlias when it is used", () => {
    window.sessionStorage.setItem(PENDING_ALIAS_KEY, "road");
    resolvePendingAlias("/", window.sessionStorage);
    expect(window.sessionStorage.getItem(PENDING_ALIAS_KEY)).toBeNull();
  });

  it("does not consume storage when a path alias wins", () => {
    window.sessionStorage.setItem(PENDING_ALIAS_KEY, "stashed");
    expect(resolvePendingAlias("/s/fresh", window.sessionStorage)).toBe("fresh");
    // The stash is left alone so a subsequent /-load can still consume it.
    expect(window.sessionStorage.getItem(PENDING_ALIAS_KEY)).toBe("stashed");
  });
});
