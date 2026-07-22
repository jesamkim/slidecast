import { describe, it, expect, vi } from "vitest";
import { createApi, fetchPublic } from "./api";

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

  it("share PUTs /api/decks/{id}/share with bearer", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ token: "abc", url: "https://x/p/abc" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = createApi("", () => "TOKEN");
    const res = await api.share("d1");
    expect(res.token).toBe("abc");
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/decks/d1/share");
    expect(opts.method).toBe("PUT");
    expect(opts.headers.Authorization).toBe("Bearer TOKEN");
  });

  it("downloadUrl attaches bearer and version query", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ downloadUrl: "https://s3/x" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = createApi("", () => "TOKEN");
    await api.downloadUrl("d1", "pdf", 3);
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/decks/d1/download?format=pdf&version=3");
    expect(opts.headers.Authorization).toBe("Bearer TOKEN");
  });

  it("getViews GETs /api/decks/{id}/views with bearer and parses {total,byDay}", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ total: 5, byDay: [{ date: "2026-07-20", count: 3 }, { date: "2026-07-21", count: 2 }] }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = createApi("", () => "TOKEN");
    const stats = await api.getViews("d1");
    expect(stats.total).toBe(5);
    expect(stats.byDay).toHaveLength(2);
    expect(stats.byDay[0].date).toBe("2026-07-20");
    expect(stats.byDay[0].count).toBe(3);
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/decks/d1/views");
    expect(opts.headers.Authorization).toBe("Bearer TOKEN");
  });

  it("fetchPublic hits /api/public/{token} WITHOUT Authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ title: "T", htmlUrl: "https://s3/h" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const res = await fetchPublic("", "pubtok");
    expect(res.title).toBe("T");
    expect(res.htmlUrl).toBe("https://s3/h");
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/public/pubtok");
    // No init or no headers means no Authorization
    expect(opts === undefined || !opts.headers || !opts.headers.Authorization).toBe(true);
  });

  it("calls onUnauthorized and throws on a 401 (expired session)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401 }));
    const onUnauthorized = vi.fn();
    const api = createApi("", () => "TOKEN", onUnauthorized);
    await expect(api.deleteGroup("yonsei")).rejects.toThrow("api 401");
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("does NOT call onUnauthorized on a non-auth error (500)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    const onUnauthorized = vi.fn();
    const api = createApi("", () => "TOKEN", onUnauthorized);
    await expect(api.deleteGroup("yonsei")).rejects.toThrow("api 500");
    expect(onUnauthorized).not.toHaveBeenCalled();
  });
});
