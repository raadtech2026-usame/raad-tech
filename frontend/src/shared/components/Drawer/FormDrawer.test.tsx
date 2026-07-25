import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FormDrawer } from "./FormDrawer";

/** Reproduces the real bug's shape: a parent passing a brand-new `onClose` function identity
 * every render (the extremely common `onClose={() => setOpen(false)}` inline-arrow pattern),
 * re-rendering itself in response to typing in a field inside the drawer — the same "keystroke
 * -> re-render -> new onClose reference" chain RegisterDeviceWizard's own `handleClose` +
 * unscoped `watch()` produced. */
function UnstableOnCloseHost() {
  const [text, setText] = useState("");
  return (
    <FormDrawer
      open
      onClose={() => {}}
      icon={<span />}
      iconTint="#fff"
      iconColor="#000"
      title="New Thing"
    >
      <input aria-label="Field" value={text} onChange={(e) => setText(e.target.value)} />
    </FormDrawer>
  );
}

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

  it("keeps focus on a child field across re-renders that pass a new onClose reference", async () => {
    const user = userEvent.setup();
    render(<UnstableOnCloseHost />);

    const field = screen.getByLabelText("Field");
    await user.click(field);
    expect(field).toHaveFocus();

    await user.type(field, "hello");

    expect(field).toHaveFocus();
    expect(field).toHaveValue("hello");
  });
});
