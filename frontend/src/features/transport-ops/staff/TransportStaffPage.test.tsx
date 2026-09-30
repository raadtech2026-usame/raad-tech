import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  listStaff: vi.fn(),
  getStaff: vi.fn(),
  changeStaffStatus: vi.fn(),
  listCrew: vi.fn().mockResolvedValue([]),
  listStaffDocuments: vi.fn().mockResolvedValue([]),
  listVehiclesForPicker: vi.fn().mockResolvedValue([]),
  listExpiringDocuments: vi.fn().mockResolvedValue([]),
  listStaffRoles: vi.fn().mockResolvedValue([]),
  listDocumentTypes: vi.fn().mockResolvedValue([]),
  listRoutesForPicker: vi.fn().mockResolvedValue([]),
}));

// The profile's Unavailability section (ADR-0053) reads through the operations client.
vi.mock("../operations/api", () => ({
  listUnavailability: vi.fn().mockResolvedValue([]),
  listStaffOptions: vi.fn().mockResolvedValue([]),
  listVehicleOptions: vi.fn().mockResolvedValue([]),
}));

import * as api from "./api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { TransportStaffPage } from "./TransportStaffPage";

const SUMMARY: api.StaffSummary = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FST",
  organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  fullName: "Amina Warsame",
  phone: "+252611234567",
  roleId: "r1",
  roleName: "Attendant",
  employeeRef: "E-7",
  status: "active",
  isDriver: false,
};

const DETAIL: api.Staff = {
  id: SUMMARY.id,
  organizationId: SUMMARY.organizationId,
  fullName: SUMMARY.fullName,
  phone: SUMMARY.phone,
  alternatePhone: null,
  roleId: "r1",
  roleName: "Attendant",
  employeeRef: "E-7",
  startDate: "2026-01-05",
  status: "active",
  emergencyContactName: "Hodan",
  emergencyContactPhone: "+252617654321",
  notes: null,
  leftOn: null,
  driver: null,
  privateFieldsVisible: true,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-02T00:00:00Z",
};

function renderPage(path = "/org/staff") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <TransportStaffPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("TransportStaffPage", () => {
  beforeEach(() => {
    vi.mocked(api.listStaff).mockResolvedValue({ data: [SUMMARY], page: { total: 1, page: 1, pageSize: 25 } });
    vi.mocked(api.getStaff).mockResolvedValue(DETAIL);
    useAuthStore.setState({
      principal: { userId: "u1", role: "org_admin", organizationId: SUMMARY.organizationId, regionIds: [] },
    });
  });

  it("lists staff with their title and opens the profile with its sections", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Amina Warsame")).toBeInTheDocument());
    expect(screen.getByText("Attendant")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Amina Warsame"));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByText("Hodan")).toBeInTheDocument());
    expect(within(dialog).getByRole("region", { name: "Buses" })).toBeInTheDocument();
    expect(within(dialog).getByRole("region", { name: "Documents" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Give driver access" })).toBeInTheDocument();
  });

  it("opens a profile from ?staff= so other pages can link to it", async () => {
    renderPage(`/org/staff?staff=${SUMMARY.id}`);
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(api.getStaff).toHaveBeenCalledWith(SUMMARY.id));
    expect(within(dialog).getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("confirms before marking someone as left, and says what it does", async () => {
    vi.mocked(api.changeStaffStatus).mockResolvedValue({ ...DETAIL, status: "left", leftOn: "2026-09-30" });
    renderPage(`/org/staff?staff=${SUMMARY.id}`);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Mark as left" }));

    expect(await screen.findByText(/bus assignments end today and their driver login is disabled/)).toBeInTheDocument();
    expect(api.changeStaffStatus).not.toHaveBeenCalled();
    const confirmButtons = screen.getAllByRole("button", { name: "Mark as left" });
    await userEvent.click(confirmButtons[confirmButtons.length - 1]);
    await waitFor(() => expect(api.changeStaffStatus).toHaveBeenCalledWith(SUMMARY.id, "left"));
  });

  it("shows RAAD staff a read-only profile without the Org-Admin-only fields", async () => {
    useAuthStore.setState({
      principal: { userId: "u2", role: "support_staff", organizationId: null, regionIds: [] },
    });
    vi.mocked(api.getStaff).mockResolvedValue({
      ...DETAIL,
      emergencyContactName: null,
      emergencyContactPhone: null,
      privateFieldsVisible: false,
    });
    renderPage(`/platform/staff?staff=${SUMMARY.id}`);

    expect(screen.queryByRole("button", { name: /New staff member/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Setup" })).not.toBeInTheDocument();
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getAllByText("Visible to Org Admins only")).toHaveLength(2));
    expect(within(dialog).queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Give driver access" })).not.toBeInTheDocument();
  });

  it("flags a Driver title without driver access", async () => {
    vi.mocked(api.getStaff).mockResolvedValue({ ...DETAIL, roleName: "Driver" });
    renderPage(`/org/staff?staff=${SUMMARY.id}`);
    expect(await screen.findByText("Titled Driver, but has no driver access yet.")).toBeInTheDocument();
  });
});
