import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { Gallery } from "./Gallery";

const makeApi = (decks: any[]) =>
  ({
    listDecks: vi.fn().mockResolvedValue(decks),
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
});
