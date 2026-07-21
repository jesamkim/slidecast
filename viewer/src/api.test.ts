import { describe, it, expect, vi } from "vitest";
import { createApi } from "./api";

describe("api client", () => {
  it("attaches bearer token and parses decks", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ decks: [{ deckId: "a" }] }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = createApi("", () => "TOKEN");
    const decks = await api.listDecks();
    expect(decks[0].deckId).toBe("a");
    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.headers.Authorization).toBe("Bearer TOKEN");
  });

  it("listGroups attaches bearer and parses {groups:[]}", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ groups: [{ groupId: "g1", name: "Marketing" }] }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = createApi("", () => "TOKEN");
    const groups = await api.listGroups();
    expect(groups[0].groupId).toBe("g1");
    expect(groups[0].name).toBe("Marketing");
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/groups");
    expect(opts.headers.Authorization).toBe("Bearer TOKEN");
  });

  it("listDecks with group appends ?status=&group=", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ decks: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = createApi("", () => "T");
    await api.listDecks("active", "mkt");
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/decks?status=active&group=mkt");
  });

  it("uploadFile PUTs with text/html content-type", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    const api = createApi("", () => "T");
    await api.uploadFile("https://s3/put", new Blob(["<html>"], { type: "text/html" }));
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("https://s3/put");
    expect(opts.method).toBe("PUT");
    expect(opts.headers["Content-Type"]).toBe("text/html");
  });
});
