import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { Gallery } from "./Gallery";

const makeApi = (decks: any[], overrides: Record<string, any> = {}) =>
  ({
    listDecks: vi.fn().mockResolvedValue(decks),
    listGroups: vi.fn().mockResolvedValue([]),
    restore: vi.fn().mockResolvedValue({}),
    softDelete: vi.fn().mockResolvedValue({}),
    hardDelete: vi.fn().mockResolvedValue({}),
    share: vi.fn().mockResolvedValue({ token: "TOK", url: "/p/TOK" }),
    unshare: vi.fn().mockResolvedValue({}),
    republish: vi.fn().mockResolvedValue({ token: "TOK2", url: "/p/TOK2" }),
    downloadUrl: vi.fn().mockResolvedValue({ downloadUrl: "https://cdn/f.html" }),
    getViews: vi
      .fn()
      .mockResolvedValue({ total: 5, byDay: [{ date: "2026-07-21", count: 5 }] }),
    downloadViews: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }) as any;

const alpha = {
  deckId: "a",
  title: "Alpha",
  tags: ["quarterly"],
  status: "active",
  currentVersion: 1,
  versions: [
    { n: 1, createdAt: "t", thumbnailKey: "thumbnails/a/v1.png", sizeBytes: 1, pdfKey: null },
  ],
  createdAt: "t",
  updatedAt: "t",
  group: null,
  alias: null,
  publicToken: null,
};

describe("Gallery", () => {
  it("renders deck cards from api", async () => {
    const api = makeApi([alpha]);
    render(<Gallery api={api} onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeTruthy());
    expect(api.listDecks).toHaveBeenCalledWith("active", undefined);
  });

  it("matches a query against tags, not just the title", async () => {
    const api = makeApi([alpha]);
    render(<Gallery api={api} onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeTruthy());

    // "quarterly" matches the tag, not the title "Alpha".
    fireEvent.change(screen.getByPlaceholderText("검색"), {
      target: { value: "quarterly" },
    });
    expect(screen.getByText("Alpha")).toBeTruthy();

    // A query matching neither title nor tags hides the card.
    fireEvent.change(screen.getByPlaceholderText("검색"), {
      target: { value: "zzz-nomatch" },
    });
    expect(screen.queryByText("Alpha")).toBeNull();
  });

  it("shows a restore action in the archived view that calls api.restore", async () => {
    const archived = { ...alpha, status: "archived" };
    const api = makeApi([archived]);
    render(<Gallery api={api} onLogout={() => {}} />);

    // Switch to the archived view.
    fireEvent.click(screen.getByRole("button", { name: "보관함" }));
    await waitFor(() =>
      expect(api.listDecks).toHaveBeenCalledWith("archived", undefined),
    );
    await waitFor(() => expect(screen.getByText("Alpha")).toBeTruthy());

    const restoreBtn = await screen.findByRole("button", { name: "복원" });
    fireEvent.click(restoreBtn);
    await waitFor(() => expect(api.restore).toHaveBeenCalledWith("a"));
  });

  it("renders a placeholder (not a /null image) when the current version has no thumbnail", async () => {
    const pending = {
      ...alpha,
      deckId: "b",
      title: "Pending",
      versions: [{ n: 1, createdAt: "t", thumbnailKey: null, sizeBytes: 1 }],
    };
    const { container } = render(
      <Gallery api={makeApi([pending])} onLogout={() => {}} />,
    );
    await waitFor(() => expect(screen.getByText("Pending")).toBeTruthy());

    // No img should point at "/null".
    const imgs = Array.from(container.querySelectorAll("img"));
    expect(imgs.some((i) => (i.getAttribute("src") ?? "").includes("null"))).toBe(false);
    // The placeholder copy is shown instead.
    expect(screen.getByText("생성 중...")).toBeTruthy();
  });

  it("opens share modal, calls api.share and shows the public link", async () => {
    const api = makeApi([alpha]);
    render(<Gallery api={api} onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "공유" }));
    // Modal shows "공유하기" primary button since no token yet.
    const shareBtn = await screen.findByRole("button", { name: "공유하기" });
    fireEvent.click(shareBtn);

    await waitFor(() => expect(api.share).toHaveBeenCalledWith("a"));
    // After share resolves, a readonly link input appears with /p/TOK.
    const link = await screen.findByDisplayValue(/\/p\/TOK$/);
    expect(link).toBeTruthy();
    expect((link as HTMLInputElement).readOnly).toBe(true);
  });

  it("shows a public badge for decks with a publicToken", async () => {
    const pub = { ...alpha, deckId: "p", title: "Public Deck", publicToken: "TOK" };
    const api = makeApi([pub]);
    render(<Gallery api={api} onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText("Public Deck")).toBeTruthy());
    expect(screen.getByText("공개")).toBeTruthy();
  });

  it("shows a view-count badge for public decks with viewCount", async () => {
    const pub = {
      ...alpha,
      deckId: "p",
      title: "Public Deck",
      publicToken: "TOK",
      viewCount: 5,
    };
    const api = makeApi([pub]);
    render(<Gallery api={api} onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText("Public Deck")).toBeTruthy());
    expect(screen.getByTestId("view-count-badge").textContent).toContain("5");
  });

  it("opening share modal for a shared deck fetches views and renders total", async () => {
    const pub = {
      ...alpha,
      deckId: "p",
      title: "Public Deck",
      publicToken: "TOK",
      viewCount: 5,
    };
    const api = makeApi([pub]);
    render(<Gallery api={api} onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText("Public Deck")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "공유" }));
    await waitFor(() => expect(api.getViews).toHaveBeenCalledWith("p"));
    await waitFor(() =>
      expect(screen.getByTestId("views-total").textContent).toContain("5"),
    );
    // Export CSV button calls downloadViews.
    fireEvent.click(screen.getByRole("button", { name: "CSV 내보내기" }));
    await waitFor(() => expect(api.downloadViews).toHaveBeenCalledWith("p", "csv"));
  });

  it("HTML download calls api.downloadUrl and opens the returned url", async () => {
    const api = makeApi([alpha]);
    // Spy on anchor click since JSDOM/happy-dom won't navigate.
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    render(<Gallery api={api} onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "HTML" }));
    await waitFor(() =>
      expect(api.downloadUrl).toHaveBeenCalledWith("a", "html", undefined),
    );
    expect(clickSpy).toHaveBeenCalled();
    clickSpy.mockRestore();
  });

  it("PDF button is disabled when the current version has no pdfKey", async () => {
    const api = makeApi([alpha]);
    render(<Gallery api={api} onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeTruthy());
    const pdfBtn = screen.getByRole("button", { name: "PDF" }) as HTMLButtonElement;
    expect(pdfBtn.disabled).toBe(true);
    expect(pdfBtn.title).toBe("PDF 생성 중");
  });

  it("upload passes the selected real group to createUpload", async () => {
    const api = makeApi([], {
      listGroups: vi.fn().mockResolvedValue([{ groupId: "mkt", name: "Marketing" }]),
      createUpload: vi.fn().mockResolvedValue({ uploadUrl: "https://u/1", deckId: "x", version: 1 }),
      uploadFile: vi.fn().mockResolvedValue(undefined),
    });
    render(<Gallery api={api} onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText("Marketing")).toBeTruthy());

    fireEvent.click(screen.getByText("Marketing"));
    await waitFor(() => expect(api.listDecks).toHaveBeenCalledWith("active", "mkt"));

    const file = new File(["<html/>"], "brief.html", { type: "text/html" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() =>
      expect(api.createUpload).toHaveBeenCalledWith("brief.html", "brief", [], "mkt"),
    );
  });

  it("upload does not send __unassigned__ sentinel as a group id", async () => {
    const api = makeApi([], {
      listGroups: vi.fn().mockResolvedValue([{ groupId: "mkt", name: "Marketing" }]),
      createUpload: vi.fn().mockResolvedValue({ uploadUrl: "https://u/1", deckId: "x", version: 1 }),
      uploadFile: vi.fn().mockResolvedValue(undefined),
    });
    render(<Gallery api={api} onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText("미분류")).toBeTruthy());

    fireEvent.click(screen.getByText("미분류"));
    await waitFor(() =>
      expect(api.listDecks).toHaveBeenCalledWith("active", "__unassigned__"),
    );

    const file = new File(["<html/>"], "brief.html", { type: "text/html" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() =>
      expect(api.createUpload).toHaveBeenCalledWith("brief.html", "brief", [], undefined),
    );
  });

  it("upload with no group selected calls createUpload with undefined group", async () => {
    const api = makeApi([], {
      createUpload: vi.fn().mockResolvedValue({ uploadUrl: "https://u/1", deckId: "x", version: 1 }),
      uploadFile: vi.fn().mockResolvedValue(undefined),
    });
    render(<Gallery api={api} onLogout={() => {}} />);
    // Wait for initial listDecks (no group).
    await waitFor(() => expect(api.listDecks).toHaveBeenCalledWith("active", undefined));

    const file = new File(["<html/>"], "brief.html", { type: "text/html" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() =>
      expect(api.createUpload).toHaveBeenCalledWith("brief.html", "brief", [], undefined),
    );
  });

  it("deleting an active deck asks for confirmation before archiving", async () => {
    const api = makeApi([alpha]);
    render(<Gallery api={api} onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeTruthy());

    // Declined confirm: softDelete must NOT run.
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(screen.getByRole("button", { name: "삭제" }));
    await Promise.resolve();
    expect(confirmSpy).toHaveBeenCalled();
    expect(api.softDelete).not.toHaveBeenCalled();

    // Accepted confirm: softDelete runs.
    confirmSpy.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "삭제" }));
    await waitFor(() => expect(api.softDelete).toHaveBeenCalledWith("a"));
    confirmSpy.mockRestore();
  });

  it("clicking the Slidecast header returns home (reloads at /)", async () => {
    const api = makeApi([alpha]);
    const replaceSpy = vi
      .spyOn(window.history, "replaceState")
      .mockImplementation(() => {});
    const reloadSpy = vi.fn();
    const orig = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...orig, reload: reloadSpy },
    });

    render(<Gallery api={api} onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeTruthy());

    fireEvent.click(screen.getByText("Slidecast"));
    expect(replaceSpy).toHaveBeenCalledWith({}, "", "/");
    expect(reloadSpy).toHaveBeenCalled();

    Object.defineProperty(window, "location", { configurable: true, value: orig });
    replaceSpy.mockRestore();
  });

  it("renders group sidebar and matches alias in search", async () => {
    const aliased = { ...alpha, deckId: "c", title: "Roadmap", alias: "road" };
    const api = makeApi([aliased], {
      listGroups: vi.fn().mockResolvedValue([
        { groupId: "mkt", name: "Marketing" },
      ]),
    });
    render(<Gallery api={api} onLogout={() => {}} />);

    await waitFor(() => expect(screen.getAllByText("Marketing").length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByText("Roadmap")).toBeTruthy());

    // Alias-only query keeps the deck visible.
    fireEvent.change(screen.getByPlaceholderText("검색"), {
      target: { value: "road" },
    });
    expect(screen.getByText("Roadmap")).toBeTruthy();
  });
});
