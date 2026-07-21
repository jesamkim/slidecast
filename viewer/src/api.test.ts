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
