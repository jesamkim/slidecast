import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { GroupSidebar } from "./GroupSidebar";

describe("GroupSidebar", () => {
  it("calls onCreate exactly once when Enter is followed by blur (unmount)", async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    render(
      <GroupSidebar
        groups={[]}
        selected={null}
        onSelect={() => {}}
        onCreate={onCreate}
        onDelete={() => {}}
      />,
    );

    fireEvent.click(screen.getByTitle("그룹 추가"));
    const input = screen.getByPlaceholderText("그룹 이름") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "New Group" } });
    fireEvent.keyDown(input, { key: "Enter" });
    // Simulate the blur that fires as the input unmounts after successful create.
    fireEvent.blur(input);

    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));
    expect(onCreate).toHaveBeenCalledWith("New Group");
  });

  it("calls onCreate once on blur (click-away path) when Enter was not pressed", async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    render(
      <GroupSidebar
        groups={[]}
        selected={null}
        onSelect={() => {}}
        onCreate={onCreate}
        onDelete={() => {}}
      />,
    );

    fireEvent.click(screen.getByTitle("그룹 추가"));
    const input = screen.getByPlaceholderText("그룹 이름") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Click Away" } });
    fireEvent.blur(input);

    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));
    expect(onCreate).toHaveBeenCalledWith("Click Away");
  });
});
