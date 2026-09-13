import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  linkGuardianToStudent: vi.fn(),
}));

vi.mock("../parents/api", () => ({
  listParentsForPicker: vi.fn(),
  getParent: vi.fn(),
  listStudentsForParent: vi.fn(),
}));

import * as api from "./api";
import * as parentsApi from "../parents/api";
import { useToastStore } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { LinkGuardianForm } from "./LinkGuardianForm";

const STUDENT_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV";

const PARENT_OPTION: parentsApi.ParentOption = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
  fullName: "Fatima Ali",
  status: "active",
};

const PARENT_DETAIL: parentsApi.Parent = {
  id: PARENT_OPTION.id,
  organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  userId: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
  fullName: "Fatima Ali",
  phone: "+252612345678",
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  alternatePhone: null,
  address: null,
  emergencyContactName: null,
  emergencyContactPhone: null,
  notes: null,
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

/** Types into the `ParentSearchSelect` search field, waits for the result, and selects it —
 * exercising the same flow a real admin follows. */
async function selectParent(): Promise<void> {
  const input = screen.getByLabelText("Parent");
  await userEvent.click(input);
  await userEvent.type(input, "Fatima");
  const option = await screen.findByRole("option", { name: "Fatima Ali" });
  await userEvent.click(option);
  await screen.findByText(/\+252612345678/);
}

describe("LinkGuardianForm", () => {
  beforeEach(() => {
    vi.mocked(parentsApi.listParentsForPicker).mockReset().mockResolvedValue([PARENT_OPTION]);
    vi.mocked(parentsApi.getParent).mockReset().mockResolvedValue(PARENT_DETAIL);
    vi.mocked(parentsApi.listStudentsForParent).mockReset().mockResolvedValue([]);
    vi.mocked(api.linkGuardianToStudent).mockReset();
    useToastStore.setState({ toasts: [] });
  });

  it("searches by name and shows the existing children count once a parent is selected", async () => {
    vi.mocked(parentsApi.listStudentsForParent).mockResolvedValue([
      { studentId: "s1", fullName: "Mohamed Ahmed", status: "active", relationship: "Mother", isPrimary: true, dateOfBirth: null },
      { studentId: "s2", fullName: "Aisha Ahmed", status: "active", relationship: "Mother", isPrimary: false, dateOfBirth: null },
    ]);
    renderForm();

    await selectParent();

    expect(screen.getByText("Fatima Ali")).toBeInTheDocument();
    expect(screen.getByText(/2 existing children/)).toBeInTheDocument();
  });

  it("requires a parent to be selected before submitting", async () => {
    renderForm();

    expect(screen.getByRole("button", { name: "Link guardian" })).toBeDisabled();
    expect(api.linkGuardianToStudent).not.toHaveBeenCalled();
  });

  it("links the selected parent with relationship/primary defaults and reports success", async () => {
    vi.mocked(api.linkGuardianToStudent).mockResolvedValue(undefined);
    const { onClose } = renderForm();

    await selectParent();
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

    await selectParent();
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
    await selectParent();
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
    vi.mocked(api.linkGuardianToStudent).mockRejectedValue(
      new ApiError(500, {
        code: "DOMAIN_ERROR",
        message: `Cannot link Student ${STUDENT_ID} (organization 01ORGA) to Parent ${PARENT_OPTION.id} (organization 01ORGB): cross-organization parent-student links are not permitted.`,
        correlationId: null,
      }),
    );

    const { onClose } = renderForm();
    await selectParent();
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
