import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatCard } from "./StatCard";

/**
 * `StatCard` is the product's only KPI primitive, used by the platform dashboard and the ERP
 * finance surfaces. Its contract is deliberately narrow, and these tests pin the parts of it
 * that matter beyond layout: it renders exactly the value it is handed, and it never invents a
 * figure to fill a slot while loading.
 */
describe("StatCard", () => {
  it("renders the value exactly as given, without reformatting it", () => {
    render(<StatCard label="Revenue" value="$4,500" />);

    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText("$4,500")).toBeInTheDocument();
  });

  it("shows a skeleton instead of a value while loading, and no meta or footnote text", () => {
    render(
      <StatCard
        label="Devices"
        value="128"
        meta="96 online"
        footnote="32 currently offline"
        isLoading
      />,
    );

    // The real figures must not leak through the loading state — a card that paints last
    // render's number under a skeleton is worse than one that paints nothing.
    expect(screen.queryByText("128")).not.toBeInTheDocument();
    expect(screen.queryByText("96 online")).not.toBeInTheDocument();
    expect(screen.queryByText("32 currently offline")).not.toBeInTheDocument();
    expect(screen.getByText("Devices")).toBeInTheDocument();
  });

  it("renders meta and footnote only when supplied", () => {
    const { rerender } = render(<StatCard label="Vehicles" value="8" />);
    expect(screen.queryByText(/online/)).not.toBeInTheDocument();

    rerender(<StatCard label="Vehicles" value="8" meta="6 active" footnote="2 in maintenance" />);
    expect(screen.getByText("6 active")).toBeInTheDocument();
    expect(screen.getByText("2 in maintenance")).toBeInTheDocument();
  });

  it("passes an em dash through as a value, so an unavailable figure never renders as zero", () => {
    render(<StatCard label="Total parents" value="—" />);

    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });
});
