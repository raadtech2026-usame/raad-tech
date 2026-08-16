import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CameraPicker } from "./CameraPicker";

const CAMERAS = [
  { id: "cam-1", channelNo: 1, position: "road_facing" as const, label: "Front" },
  { id: "cam-2", channelNo: 2, position: "in_cabin" as const, label: null },
];

describe("CameraPicker", () => {
  it("lists each camera by label, falling back to its channel number", () => {
    render(<CameraPicker cameras={CAMERAS} value="" onChange={vi.fn()} />);
    const select = screen.getByLabelText("Camera");
    expect(select).toHaveTextContent("Front");
    expect(select).toHaveTextContent("Channel 2");
  });

  it("calls onChange with the selected camera id", async () => {
    const onChange = vi.fn();
    render(<CameraPicker cameras={CAMERAS} value="" onChange={onChange} />);
    await userEvent.selectOptions(screen.getByLabelText("Camera"), "cam-1");
    expect(onChange).toHaveBeenCalledWith("cam-1");
  });

  it("defaults to disabled when there are no cameras to pick from", () => {
    render(<CameraPicker cameras={[]} value="" onChange={vi.fn()} />);
    expect(screen.getByLabelText("Camera")).toBeDisabled();
  });

  it("respects an explicit disabled override even when cameras are present", () => {
    render(<CameraPicker cameras={CAMERAS} value="" onChange={vi.fn()} disabled />);
    expect(screen.getByLabelText("Camera")).toBeDisabled();
  });
});
