import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  addStopToRoute: vi.fn(),
}));

import * as api from "./api";
import { useToastStore } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { AddStopForm } from "./AddStopForm";

const STOP: api.Stop = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FST",
  name: "Main Street & 5th Ave",
  latitude: 2.0469,
  longitude: 45.3182,
  sequenceNo: 1,
  geofenceRadiusM: 100,
};

function renderForm(props: Partial<Parameters<typeof AddStopForm>[0]> = {}) {
  const onClose = vi.fn();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <AddStopForm
        open
        onClose={onClose}
        routeId="01ARZ3NDEKTSV4RRFFQ69G5FRT"
        routeName="Morning Route A"
        nextSequenceNo={1}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("AddStopForm", () => {
  beforeEach(() => {
    vi.mocked(api.addStopToRoute).mockReset();
    useToastStore.setState({ toasts: [] });
  });

  it("renders nothing when no route is selected", () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <AddStopForm open onClose={vi.fn()} routeId={null} nextSequenceNo={1} />
      </QueryClientProvider>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("pre-fills the sequence number field with the suggested next value", () => {
    renderForm({ nextSequenceNo: 3 });

    expect(screen.getByPlaceholderText("e.g. 1")).toHaveValue("3");
  });

  it("submits the exact AddStopToRouteRequest shape", async () => {
    vi.mocked(api.addStopToRoute).mockResolvedValue(STOP);
    const { onClose } = renderForm();

    await userEvent.type(screen.getByPlaceholderText("e.g. Main Street & 5th Ave"), "Main Street & 5th Ave");
    await userEvent.type(screen.getByPlaceholderText("e.g. 2.0469"), "2.0469");
    await userEvent.type(screen.getByPlaceholderText("e.g. 45.3182"), "45.3182");
    await userEvent.type(screen.getByPlaceholderText("e.g. 100"), "100");
    await userEvent.click(screen.getByRole("button", { name: "Add stop" }));

    await waitFor(() =>
      expect(api.addStopToRoute).toHaveBeenCalledWith("01ARZ3NDEKTSV4RRFFQ69G5FRT", {
        name: "Main Street & 5th Ave",
        latitude: 2.0469,
        longitude: 45.3182,
        sequenceNo: 1,
        geofenceRadiusM: 100,
      }),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(useToastStore.getState().toasts[0]).toMatchObject({ variant: "success", title: "Stop added" });
  });

  it("rejects an out-of-range latitude", async () => {
    renderForm();

    await userEvent.type(screen.getByPlaceholderText("e.g. Main Street & 5th Ave"), "Somewhere");
    await userEvent.type(screen.getByPlaceholderText("e.g. 2.0469"), "120");
    await userEvent.type(screen.getByPlaceholderText("e.g. 45.3182"), "45.3182");
    await userEvent.click(screen.getByRole("button", { name: "Add stop" }));

    expect(await screen.findByText("Latitude must be between -90 and 90")).toBeInTheDocument();
    expect(api.addStopToRoute).not.toHaveBeenCalled();
  });

  it("rejects a non-positive sequence number", async () => {
    renderForm();

    await userEvent.clear(screen.getByPlaceholderText("e.g. 1"));
    await userEvent.type(screen.getByPlaceholderText("e.g. 1"), "0");
    await userEvent.type(screen.getByPlaceholderText("e.g. Main Street & 5th Ave"), "Somewhere");
    await userEvent.type(screen.getByPlaceholderText("e.g. 2.0469"), "2.0469");
    await userEvent.type(screen.getByPlaceholderText("e.g. 45.3182"), "45.3182");
    await userEvent.click(screen.getByRole("button", { name: "Add stop" }));

    expect(await screen.findByText("Sequence number must be a positive whole number")).toBeInTheDocument();
    expect(api.addStopToRoute).not.toHaveBeenCalled();
  });

  it("surfaces a duplicate-sequence conflict via a toast and keeps the drawer open", async () => {
    vi.mocked(api.addStopToRoute).mockRejectedValue(
      new ApiError(409, {
        code: "CONFLICT",
        message: "A stop with sequence_no 1 already exists on this route.",
        correlationId: null,
      }),
    );
    const { onClose } = renderForm();

    await userEvent.type(screen.getByPlaceholderText("e.g. Main Street & 5th Ave"), "Somewhere");
    await userEvent.type(screen.getByPlaceholderText("e.g. 2.0469"), "2.0469");
    await userEvent.type(screen.getByPlaceholderText("e.g. 45.3182"), "45.3182");
    await userEvent.click(screen.getByRole("button", { name: "Add stop" }));

    await waitFor(() =>
      expect(useToastStore.getState().toasts[0]).toMatchObject({
        variant: "error",
        title: "Add stop failed",
        description: "A stop with sequence_no 1 already exists on this route.",
      }),
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
