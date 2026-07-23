import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Toggle } from "./Toggle";

describe("Toggle", () => {
  it("exposes a real switch role, keyboard-operable", async () => {
    const onChange = vi.fn();
    render(<Toggle label="Harsh-event detection" onChange={onChange} />);
    const toggle = screen.getByRole("switch", { name: "Harsh-event detection" });
    expect(toggle).not.toBeChecked();

    await userEvent.click(toggle);
    expect(onChange).toHaveBeenCalledOnce();
  });

  it("reflects the checked state via aria for screen readers", () => {
    render(<Toggle label="Dark theme" checked readOnly />);
    expect(screen.getByRole("switch", { name: "Dark theme" })).toBeChecked();
  });
});
