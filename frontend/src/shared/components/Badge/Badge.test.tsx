import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Badge } from "./Badge";

describe("Badge", () => {
  it("renders its children", () => {
    render(<Badge variant="success">Active</Badge>);
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("renders a dot when dot is set", () => {
    const { container } = render(
      <Badge variant="danger" dot>
        Offline
      </Badge>,
    );
    expect(container.querySelectorAll("span").length).toBeGreaterThanOrEqual(2);
  });

  it("defaults to the neutral variant", () => {
    render(<Badge>Idle</Badge>);
    expect(screen.getByText("Idle")).toBeInTheDocument();
  });
});
