import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Logo } from "./Logo";

describe("Logo", () => {
  it("renders the RAAD mark with default size", () => {
    render(<Logo size={32} />);
    const img = screen.getByAltText("RAAD");
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("width", "32");
    expect(img).toHaveAttribute("height", "32");
  });

  it("renders with wordmark and tagline", () => {
    render(<Logo size={34} withWordmark />);
    expect(screen.getByAltText("RAAD")).toBeInTheDocument();
    expect(screen.getByText("RAAD")).toBeInTheDocument();
    expect(screen.getByText("TRANSPORT OS")).toBeInTheDocument();
  });

  it("applies theme-adaptive colors by default", () => {
    render(<Logo withWordmark />);
    const name = screen.getByText("RAAD");
    expect(name).toHaveStyle({ color: "var(--color-text-primary)" });
  });
});
