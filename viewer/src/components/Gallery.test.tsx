import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Gallery } from "./Gallery";

const fakeApi = {
  listDecks: vi.fn().mockResolvedValue([
    {
      deckId: "a",
      title: "Alpha",
      tags: [],
      status: "active",
      currentVersion: 1,
      versions: [
        { n: 1, createdAt: "t", thumbnailKey: "thumbnails/a/v1.png", sizeBytes: 1 },
      ],
      createdAt: "t",
      updatedAt: "t",
    },
  ]),
} as any;

describe("Gallery", () => {
  it("renders deck cards from api", async () => {
    render(<Gallery api={fakeApi} onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeTruthy());
    expect(fakeApi.listDecks).toHaveBeenCalledWith("active");
  });
});
