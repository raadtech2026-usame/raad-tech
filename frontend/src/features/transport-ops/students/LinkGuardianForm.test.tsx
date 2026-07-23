import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  linkGuardianToStudent: vi.fn(),
  listParentsForPicker: vi.fn(),
}));

import * as api from "./api";
import { useToastStore } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { LinkGuardianForm } from "./LinkGuardianForm";

const STUDENT_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV";

const PARENT_OPTION: api.ParentOption = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
  fullName: "Fatima Ali",
  status: "active",
};

function renderForm(overrides: Partial<Parameters<typeof LinkGuardianForm>[0]> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <LinkGuardianForm open onClose={onClose} studentId={STUDENT_ID} studentName="Amina Hassan" {...overrides} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("LinkGuardianForm", () => {
  beforeEach(() => {
    vi.mocked(api.listParentsForPicker).mockReset().mockResolvedValue([PARENT_OPTION]);
    vi.mocked(api.linkGuardianToStudent).mockReset();
    useToastStore.setState({ toasts: [] });
  });

  it("fetches the parent picker on open", async () => {
    renderForm();

    await waitFor(() => expect(api.listParentsForPicker).toHaveBeenCalledWith(""));
    expect(await screen.findByText("Fatima Ali")).toBeInTheDocument();
  });

  it("requires a parent to be selected before submitting", async () => {
    renderForm();
    await screen.findByText("Fatima Ali");

    await userEvent.click(screen.getByRole("button", { name: "Link guardian" }));

    expect(await screen.findByText("Parent is required")).toBeInTheDocument();
    expect(api.linkGuardianToStudent).not.toHaveBeenCalled();
  });

  it("links the selected parent with relationship/primary defaults and reports success", async () => {
    vi.mocked(api.linkGuardianToStudent).mockResolvedValue(undefined);
    const { onClose } = renderForm();
    await screen.findByText("Fatima Ali");

    await userEvent.selectOptions(screen.getByLabelText("Parent"), PARENT_OPTION.id);
    await userEvent.click(screen.getByRole("button", { name: "Link guardian" }));

    await waitFor(() =>
      expect(api.linkGuardianToStudent).toHaveBeenCalledWith(STUDENT_ID, {
        parentId: PARENT_OPTION.id,
        relationship: null,
        isPrimary: false,
      }),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(useToastStore.getState().toasts[0]).toMatchObject({ variant: "success", title: "Guardian linked" });
  });

  it("submits the relationship text and primary toggle when set", async () => {
    vi.mocked(api.linkGuardianToStudent).mockResolvedValue(undefined);
    renderForm();
    await screen.findByText("Fatima Ali");

    await userEvent.selectOptions(screen.getByLabelText("Parent"), PARENT_OPTION.id);
    await userEvent.type(screen.getByPlaceholderText("e.g. Mother"), "Mother");
    await userEvent.click(screen.getByRole("switch"));
    await userEvent.click(screen.getByRole("button", { name: "Link guardian" }));

    await waitFor(() =>
      expect(api.linkGuardianToStudent).toHaveBeenCalledWith(STUDENT_ID, {
        parentId: PARENT_OPTION.id,
        relationship: "Mother",
        isPrimary: true,
      }),
    );
  });

  it("surfaces the backend's duplicate-link conflict via a toast and keeps the drawer open", async () => {
    vi.mocked(api.linkGuardianToStudent).mockRejectedValue(
      new ApiError(409, {
        code: "CONFLICT",
        message: `Parent ${PARENT_OPTION.id} is already linked to student ${STUDENT_ID}.`,
        correlationId: null,
      }),
    );

    const { onClose } = renderForm();
    await screen.findByText("Fatima Ali");

    await userEvent.selectOptions(screen.getByLabelText("Parent"), PARENT_OPTION.id);
    await userEvent.click(screen.getByRole("button", { name: "Link guardian" }));

    await waitFor(() =>
      expect(useToastStore.getState().toasts[0]).toMatchObject({
        variant: "error",
        title: "Link failed",
        description: `Parent ${PARENT_OPTION.id} is already linked to student ${STUDENT_ID}.`,
      }),
    );
    expect(onClose).not.toHaveBeenCalled();
  });

  it("surfaces the backend's cross-organization rejection (a raw DomainError, mapped to HTTP 500) via a toast", async () => {
    // `StudentParent.link`'s cross-organization guard raises a plain `DomainError`, which
    // `core/errors/handlers.py`'s `_STATUS_TABLE` does not special-case (only its `ConflictError`/
    // `RuleViolationError` subclasses are listed) — it falls through to the generic
    // `status_code >= 500` branch. The frontend still shows the real domain message via
    // `error.message`, exactly like every other `ApiError` consumer in this codebase.
    vi.mocked(api.linkGuardianToStudent).mockRejectedValue(
      new ApiError(500, {
        code: "DOMAIN_ERROR",
        message: `Cannot link Student ${STUDENT_ID} (organization 01ORGA) to Parent ${PARENT_OPTION.id} (organization 01ORGB): cross-organization parent-student links are not permitted.`,
        correlationId: null,
      }),
    );

    const { onClose } = renderForm();
    await screen.findByText("Fatima Ali");

    await userEvent.selectOptions(screen.getByLabelText("Parent"), PARENT_OPTION.id);
    await userEvent.click(screen.getByRole("button", { name: "Link guardian" }));

    await waitFor(() =>
      expect(useToastStore.getState().toasts[0]).toMatchObject({
        variant: "error",
        title: "Link failed",
        description: `Cannot link Student ${STUDENT_ID} (organization 01ORGA) to Parent ${PARENT_OPTION.id} (organization 01ORGB): cross-organization parent-student links are not permitted.`,
      }),
    );
    expect(onClose).not.toHaveBeenCalled();
  });

  it("renders nothing when no student is selected", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <LinkGuardianForm open onClose={vi.fn()} studentId={null} />
      </QueryClientProvider>,
    );

    expect(container.querySelector('[role="dialog"]')).not.toBeInTheDocument();
  });
});
