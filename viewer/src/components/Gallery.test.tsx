import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { Gallery } from "./Gallery";

const makeApi = (decks: any[], overrides: Record<string, any> = {}) =>
  ({
    listDecks: vi.fn().mockResolvedValue(decks),
    restore: vi.fn().mockResolvedValue({}),
    ...overrides,
  }) as any;

const alpha = {
  deckId: "a",
  title: "Alpha",
  tags: ["quarterly"],
  status: "active",
  currentVersion: 1,
  versions: [
    { n: 1, createdAt: "t", thumbnailKey: "thumbnails/a/v1.png", sizeBytes: 1 },
  ],
  createdAt: "t",
  updatedAt: "t",
};

describe("Gallery", () => {
  it("renders deck cards from api", async () => {
    const api = makeApi([alpha]);
    render(<Gallery api={api} onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeTruthy());
    expect(api.listDecks).toHaveBeenCalledWith("active");
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
    await waitFor(() => expect(api.listDecks).toHaveBeenCalledWith("archived"));
    await waitFor(() => expect(screen.getByText("Alpha")).toBeTruthy());

    const restoreBtn = await screen.findByRole("button", { name: "복원" });
    fireEvent.click(restoreBtn);
    await waitFor(() => expect(api.restore).toHaveBeenCalledWith("a"));
  });
});
