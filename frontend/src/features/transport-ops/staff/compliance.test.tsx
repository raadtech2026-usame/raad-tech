import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../shared/api/client")>()),
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../../shared/api/client";
import { CompliancePanel, ComplianceSummary } from "./CompliancePanel";
import { StaffSetupPanel } from "./StaffSetupPanel";
import { getDocumentTypeImpact, listDocumentTypes, listStaffCompliance, toCompliance, updateDocumentType } from "./api";
import { complianceReasons, enforcementLabel, requirementLabel } from "./labels";

const TYPE_WIRE = {
  id: "t1",
  organization_id: "org",
  name: "Driving licence",
  alert_lead_days: [30, 7],
  is_archived: false,
  required_for: "none",
  enforcement: "warn",
};

const COMPLIANCE_WIRE = {
  status: "not_compliant",
  gaps: [
    { type_id: "t1", type_name: "Driving licence", reason: "expired", expired_on: "2026-10-03", blocks: true },
    { type_id: "t2", type_name: "Medical certificate", reason: "missing", expired_on: null, blocks: false },
  ],
  expiring: [{ type_id: "t3", type_name: "First-aid certificate", expires_on: "2026-10-20" }],
  is_blocked: true,
};

const ROW_WIRE = {
  staff_id: "s1",
  organization_id: "org",
  staff_name: "Hassan Driver",
  role_name: "Driver",
  is_driver: true,
  compliance: COMPLIANCE_WIRE,
};

function wrap(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("compliance api and labels", () => {
  beforeEach(() => vi.mocked(apiRequest).mockReset());

  it("maps a compliance result and words each reason", () => {
    const compliance = toCompliance(COMPLIANCE_WIRE)!;
    expect(compliance).toMatchObject({ status: "not_compliant", isBlocked: true });
    const reasons = complianceReasons(compliance);
    expect(reasons[0]).toMatch(/^Driving licence expired on /);
    expect(reasons[1]).toBe("Medical certificate missing");
    expect(reasons[2]).toMatch(/^First-aid certificate expires on /);
    expect(toCompliance(null)).toBeNull();
  });

  it("treats a type from before Phase 4 as not required", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce([{ ...TYPE_WIRE, required_for: undefined, enforcement: undefined }]);
    const [type] = await listDocumentTypes();
    expect([type.requiredFor, type.enforcement]).toEqual(["none", "warn"]);
    expect([requirementLabel("drivers"), enforcementLabel("block")]).toEqual(["Required for drivers", "Blocks new planning"]);
  });

  it("sends the requirement in snake_case and asks for the impact read-only", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(TYPE_WIRE).mockResolvedValueOnce({ applies_to: 4, not_compliant: 3 });
    await updateDocumentType("t1", { name: "Driving licence", alertLeadDays: [30, 7], requiredFor: "drivers", enforcement: "block" });
    expect(vi.mocked(apiRequest).mock.calls[0][1]).toMatchObject({
      method: "PATCH",
      body: { required_for: "drivers", enforcement: "block", is_archived: false },
    });
    expect(await getDocumentTypeImpact("t1", "drivers")).toEqual({ appliesTo: 4, notCompliant: 3 });
    expect(apiRequest).toHaveBeenLastCalledWith("/staff-document-types/t1/impact?required_for=drivers");
  });

  it("maps the compliance list", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce([ROW_WIRE]);
    const [row] = await listStaffCompliance();
    expect(row).toMatchObject({ staffId: "s1", staffName: "Hassan Driver", isDriver: true });
    expect(row.compliance.gaps).toHaveLength(2);
  });
});

describe("CompliancePanel", () => {
  beforeEach(() => vi.mocked(apiRequest).mockReset());

  it("lists who is not compliant with each reason, and opens their profile", async () => {
    vi.mocked(apiRequest).mockResolvedValue([ROW_WIRE]);
    const onOpen = vi.fn();
    wrap(<CompliancePanel onOpenStaff={onOpen} />);
    const panel = await screen.findByRole("region", { name: "Required documents" });
    expect(within(panel).getByText("1 not compliant · 0 expiring")).toBeInTheDocument();
    expect(within(panel).getByText("Medical certificate missing")).toBeInTheDocument();
    expect(within(panel).getByText("Blocks planning")).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Open profile" }));
    expect(onOpen).toHaveBeenCalledWith("s1");
  });

  it("stays out of the way when nothing is required", async () => {
    vi.mocked(apiRequest).mockResolvedValue([]);
    const { container } = wrap(<CompliancePanel onOpenStaff={vi.fn()} />);
    await waitFor(() => expect(apiRequest).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("shows nothing for a compliant person or one who has left", () => {
    const { container } = render(
      <>
        <ComplianceSummary compliance={null} />
        <ComplianceSummary compliance={{ status: "compliant", gaps: [], expiring: [], isBlocked: false }} />
      </>,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("document type requirement setup", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
    vi.mocked(apiRequest).mockImplementation(async (path: string, options?: { method?: string }) => {
      if (path.includes("/impact")) return { applies_to: 5, not_compliant: 5 } as never;
      if (options?.method === "PATCH") return { ...TYPE_WIRE, required_for: "drivers", enforcement: "block" } as never;
      if (path.startsWith("/staff-document-types")) return [TYPE_WIRE] as never;
      return [] as never;
    });
  });

  it("shows how many people a requirement affects before it is saved", async () => {
    wrap(<StaffSetupPanel canManage />);
    const types = await screen.findByRole("region", { name: "Document types" });
    await userEvent.click(await within(types).findByRole("button", { name: "Requirement" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Who needs Driving licence"), "drivers");
    expect(await screen.findByText("Applies to 5 staff; 5 of them will be not compliant today.")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("If Driving licence is missing or expired"), "block");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith(
        "/staff-document-types/t1",
        expect.objectContaining({ body: expect.objectContaining({ required_for: "drivers", enforcement: "block" }) }),
      ),
    );
  });

  it("offers no requirement control to read-only roles", async () => {
    wrap(<StaffSetupPanel canManage={false} />);
    const types = await screen.findByRole("region", { name: "Document types" });
    await within(types).findByText("Driving licence");
    expect(within(types).queryByRole("button", { name: "Requirement" })).not.toBeInTheDocument();
  });
});
