import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DetailDrawer } from "./DetailDrawer";

/** DetailDrawer's own copy of FormDrawer's focus-management effect (its own docstring: "The
 * open/close focus-management effect is intentionally duplicated from DetailDrawer") shared the
 * identical bug: an unstable `onClose` reference in the effect's dependency array re-ran the
 * effect on every re-render and unconditionally re-focused the close button, stealing focus from
 * a field nested in `mapSlot`/`footer` (e.g. an inline edit form) the moment its own state
 * changed. See FormDrawer.test.tsx's equivalent case for the full reproduction shape. */
function UnstableOnCloseHost() {
  const [text, setText] = useState("");
  return (
    <DetailDrawer
      open
      onClose={() => {}}
      icon={<span />}
      iconTint="#fff"
      iconColor="#000"
      title="Vehicle ABC-1234"
      mapSlot={<input aria-label="Field" value={text} onChange={(e) => setText(e.target.value)} />}
    />
  );
}

describe("DetailDrawer", () => {
  it("renders nothing when closed", () => {
    render(
      <DetailDrawer open={false} onClose={() => {}} icon={<span />} iconTint="#fff" iconColor="#000" title="X" />,
    );
    expect(screen.queryByText("X")).not.toBeInTheDocument();
  });

  it("keeps focus on a nested field across re-renders that pass a new onClose reference", async () => {
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
