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
});
