import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { PublicPage } from "./PublicPage";
import * as apiMod from "../api";

describe("PublicPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a sandboxed iframe with the htmlUrl on success", async () => {
    vi.spyOn(apiMod, "fetchPublic").mockResolvedValue({
      title: "Public Deck",
      htmlUrl: "https://cdn.example.com/slides/a/v1/index.html",
    });

    const { container } = render(<PublicPage token="TOK" baseUrl="" />);
    await waitFor(() => expect(screen.getByText("Public Deck")).toBeTruthy());

    const iframe = container.querySelector("iframe");
    expect(iframe).toBeTruthy();
    expect(iframe?.getAttribute("src")).toBe(
      "https://cdn.example.com/slides/a/v1/index.html",
    );
    expect(iframe?.getAttribute("sandbox")).toBe("allow-scripts allow-popups allow-popups-to-escape-sandbox");
  });

  it("renders a not-found message when fetchPublic 404s", async () => {
    vi.spyOn(apiMod, "fetchPublic").mockRejectedValue(new Error("public 404"));

    render(<PublicPage token="MISSING" baseUrl="" />);
    await waitFor(() =>
      expect(
        screen.getByText(/만료되었거나 존재하지 않는 링크/),
      ).toBeTruthy(),
    );
  });
});
