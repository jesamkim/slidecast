import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { Gallery } from "./Gallery";

const makeApi = (decks: any[], overrides: Record<string, any> = {}) =>
  ({
    listDecks: vi.fn().mockResolvedValue(decks),
    listGroups: vi.fn().mockResolvedValue([]),
    restore: vi.fn().mockResolvedValue({}),
    share: vi.fn().mockResolvedValue({ token: "TOK", url: "/p/TOK" }),
    unshare: vi.fn().mockResolvedValue({}),
    republish: vi.fn().mockResolvedValue({ token: "TOK2", url: "/p/TOK2" }),
    downloadUrl: vi.fn().mockResolvedValue({ downloadUrl: "https://cdn/f.html" }),
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
