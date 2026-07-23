import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  createRegion: vi.fn(),
}));

import * as api from "./api";
import { useToastStore } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { CreateRegionForm } from "./CreateRegionForm";

const REGION: api.Region = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  name: "East Africa",
  geographicScope: "Kenya, Somalia, Ethiopia",
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

function renderForm(onClose = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CreateRegionForm open onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("CreateRegionForm", () => {
  beforeEach(() => {
    useToastStore.setState({ toasts: [] });
    vi.mocked(api.createRegion).mockReset();
  });

  it("requires a region name before submitting", async () => {
    renderForm();

    await userEvent.click(screen.getByRole("button", { name: "Create region" }));

    expect(await screen.findByText("Region name is required")).toBeInTheDocument();
    expect(api.createRegion).not.toHaveBeenCalled();
  });

  it("submits the exact CreateRegionInput shape and closes on success", async () => {
    vi.mocked(api.createRegion).mockResolvedValue(REGION);
    const { onClose } = renderForm();

    await userEvent.type(screen.getByPlaceholderText("e.g. East Africa"), "East Africa");
    await userEvent.type(
      screen.getByPlaceholderText("e.g. Kenya, Somalia, Ethiopia"),
      "Kenya, Somalia, Ethiopia",
    );
    await userEvent.click(screen.getByRole("button", { name: "Create region" }));

    await waitFor(() =>
      expect(api.createRegion).toHaveBeenCalledWith({
        name: "East Africa",
        geographicScope: "Kenya, Somalia, Ethiopia",
      }),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("surfaces the backend's error message verbatim via a toast and keeps the drawer open", async () => {
    vi.mocked(api.createRegion).mockRejectedValue(
      new ApiError(409, { code: "CONFLICT", message: "A region named 'East Africa' already exists.", correlationId: null }),
    );
    const { onClose } = renderForm();

    await userEvent.type(screen.getByPlaceholderText("e.g. East Africa"), "East Africa");
    await userEvent.click(screen.getByRole("button", { name: "Create region" }));

    await waitFor(() =>
      expect(useToastStore.getState().toasts[0]).toMatchObject({
        variant: "error",
        title: "Create failed",
        description: "A region named 'East Africa' already exists.",
      }),
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
