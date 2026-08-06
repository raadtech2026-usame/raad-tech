import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("renders nothing when closed", () => {
    render(
      <ConfirmDialog
        open={false}
        title="Pay invoice"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.queryByText("Pay invoice")).not.toBeInTheDocument();
  });

  it("renders title/description and calls onConfirm/onCancel", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        open
        title="Pay invoice INV-1"
        description="Charge $49.00 to the card on file."
        confirmLabel="Pay now"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Charge $49.00 to the card on file.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Pay now" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<ConfirmDialog open title="Pay invoice" onConfirm={() => {}} onCancel={onCancel} />);

    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("disables the confirm button while loading and shows children content", () => {
    render(
      <ConfirmDialog
        open
        title="Pay invoice"
        loading
        onConfirm={() => {}}
        onCancel={() => {}}
      >
        <div>Card form</div>
      </ConfirmDialog>,
    );

    expect(screen.getByText("Card form")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });

  it("disables the confirm button when confirmDisabled is set, without a spinner", () => {
    render(
      <ConfirmDialog
        open
        title="Pay invoice"
        confirmDisabled
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );

    const confirmButton = screen.getByRole("button", { name: "Confirm" });
    expect(confirmButton).toBeDisabled();
    expect(confirmButton).not.toHaveAttribute("aria-busy");
  });
});
