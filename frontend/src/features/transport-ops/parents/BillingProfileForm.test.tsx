import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  getFamilyFees: vi.fn(),
  saveParentBillingProfile: vi.fn(),
  setStudentBillingFee: vi.fn(),
  formatParentAmount: (amount: string, currency: string) => `${currency} ${amount}`,
}));

import * as api from "./api";
import { BillingProfileForm } from "./BillingProfileForm";

const PARENT_ID = "01ARZ3NDEKTSV4RRFFQ69G5FCX";

const PROFILE: api.ParentBillingProfile = {
  id: "bp-1",
  organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  parentId: PARENT_ID,
  currency: "USD",
  billingStartPeriod: "2026-09",
  dueDay: 10,
  status: "active",
  createdAt: "2026-09-01T00:00:00Z",
  updatedAt: "2026-09-01T00:00:00Z",
};

function renderForm(existing: api.ParentBillingProfile | null = PROFILE) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <BillingProfileForm open onClose={onClose} parentId={PARENT_ID} parentName="Fatima Ali" existing={existing} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("BillingProfileForm (ADR-0048 per-student fees)", () => {
  beforeEach(() => {
    vi.mocked(api.getFamilyFees).mockReset().mockResolvedValue({
      parentId: PARENT_ID,
      monthlyTotal: "30.00",
      currency: "USD",
      unpricedActiveStudents: 1,
      students: [
        { studentId: "s1", fullName: "Amina", status: "active", monthlyFee: "10.00", currency: "USD" },
        { studentId: "s2", fullName: "Yusuf", status: "active", monthlyFee: "20.00", currency: "USD" },
        { studentId: "s3", fullName: "Hawa", status: "active", monthlyFee: null, currency: null },
      ],
    });
    vi.mocked(api.saveParentBillingProfile).mockReset().mockResolvedValue(PROFILE);
    vi.mocked(api.setStudentBillingFee).mockReset().mockResolvedValue(undefined);
  });

  it("shows each child's own fee and the family total the next invoice bills", async () => {
    renderForm();
    expect(await screen.findByLabelText("Monthly fee for Amina")).toHaveValue("10.00");
    expect(screen.getByLabelText("Monthly fee for Yusuf")).toHaveValue("20.00");
    expect(screen.getByLabelText("Monthly fee for Hawa")).toHaveValue("");
    expect(screen.getByText(/Monthly total:/)).toHaveTextContent("USD 30.00 — 1 active child has no fee yet");

    await userEvent.type(screen.getByLabelText("Monthly fee for Hawa"), "30.00");
    expect(screen.getByText(/Monthly total:/)).toHaveTextContent("USD 60.00");
  });

  it("saves the account, then only the fees that changed", async () => {
    const { onClose } = renderForm();
    await userEvent.type(await screen.findByLabelText("Monthly fee for Hawa"), "30.00");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(api.saveParentBillingProfile).toHaveBeenCalledWith(PARENT_ID, {
      currency: "USD",
      billingStartPeriod: "2026-09",
      dueDay: 10,
    });
    expect(api.setStudentBillingFee).toHaveBeenCalledTimes(1);
    expect(api.setStudentBillingFee).toHaveBeenCalledWith("s3", { monthlyFee: "30.00", currency: "USD" });
  });

  it("refuses to blank a fee that is set — 0.00 is how a child stops being billed", async () => {
    renderForm();
    await userEvent.clear(await screen.findByLabelText("Monthly fee for Amina"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Enter 0.00 to stop billing this child")).toBeInTheDocument();
    expect(api.saveParentBillingProfile).not.toHaveBeenCalled();
  });
});
