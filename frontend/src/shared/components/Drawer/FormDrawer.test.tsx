import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FormDrawer } from "./FormDrawer";

describe("FormDrawer", () => {
  it("renders nothing when closed", () => {
    render(
      <FormDrawer
        open={false}
        onClose={vi.fn()}
        icon={<span>icon</span>}
        iconTint="#fff"
        iconColor="#000"
        title="New Thing"
      >
        <div>form body</div>
      </FormDrawer>,
    );
    expect(screen.queryByText("form body")).not.toBeInTheDocument();
  });

  it("renders the title, children, and footer when open", () => {
    render(
      <FormDrawer
        open
        onClose={vi.fn()}
        icon={<span>icon</span>}
        iconTint="#fff"
        iconColor="#000"
        title="New Thing"
        subtitle="A subtitle"
        footer={<button type="button">Save</button>}
      >
        <div>form body</div>
      </FormDrawer>,
    );
    expect(screen.getByText("New Thing")).toBeInTheDocument();
    expect(screen.getByText("A subtitle")).toBeInTheDocument();
    expect(screen.getByText("form body")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(
      <FormDrawer open onClose={onClose} icon={<span />} iconTint="#fff" iconColor="#000" title="New Thing">
        <div>form body</div>
      </FormDrawer>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Close panel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose on Escape and clicking the scrim", () => {
    const onClose = vi.fn();
    const { container } = render(
      <FormDrawer open onClose={onClose} icon={<span />} iconTint="#fff" iconColor="#000" title="New Thing">
        <div>form body</div>
      </FormDrawer>,
    );

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    const scrim = container.querySelector("div");
    expect(scrim).not.toBeNull();
    fireEvent.click(scrim as Element);
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
