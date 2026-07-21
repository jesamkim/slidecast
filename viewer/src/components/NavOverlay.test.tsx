import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { NavOverlay } from "./NavOverlay";

describe("NavOverlay", () => {
  it("is hidden until a slidecast-state message arrives (unsupported deck fallback)", () => {
    const ref = { current: document.createElement("iframe") } as any;
    render(<NavOverlay iframeRef={ref} />);
    // 페이지 표시 요소가 없어야 함
    expect(screen.queryByTestId("nav-counter")).toBeNull();
  });

  it("shows counter and buttons after receiving slidecast-state", () => {
    const ref = { current: document.createElement("iframe") } as any;
    render(<NavOverlay iframeRef={ref} />);
    act(() => {
      window.dispatchEvent(new MessageEvent("message", {
        source: ref.current.contentWindow,
        data: { type: "slidecast-state", cur: 3, total: 15 },
      }));
    });
    expect(screen.getByTestId("nav-counter").textContent).toContain("3 / 15");
    expect(screen.getByRole("button", { name: "이전 슬라이드" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "다음 슬라이드" })).toBeTruthy();
  });

  it("clicking next posts a slidecast-nav next command to the iframe", () => {
    const iframe = document.createElement("iframe");
    const post = vi.fn();
    // happy-dom exposes contentWindow as a read-only getter, so override it.
    Object.defineProperty(iframe, "contentWindow", {
      configurable: true,
      value: { postMessage: post },
    });
    const ref = { current: iframe } as any;
    render(<NavOverlay iframeRef={ref} />);
    act(() => {
      window.dispatchEvent(new MessageEvent("message", {
        source: iframe.contentWindow,
        data: { type: "slidecast-state", cur: 1, total: 5 },
      }));
    });
    fireEvent.click(screen.getByRole("button", { name: "다음 슬라이드" }));
    expect(post).toHaveBeenCalledWith(
      { type: "slidecast-nav", action: "next" }, "*"
    );
  });

  it("ignores messages whose source is not the iframe", () => {
    const ref = { current: document.createElement("iframe") } as any;
    render(<NavOverlay iframeRef={ref} />);
    act(() => {
      window.dispatchEvent(new MessageEvent("message", {
        source: {} as Window,   // 다른 소스
        data: { type: "slidecast-state", cur: 9, total: 9 },
      }));
    });
    expect(screen.queryByTestId("nav-counter")).toBeNull();
  });
});
