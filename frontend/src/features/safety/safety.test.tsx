import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../shared/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../shared/api/client")>()),
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../shared/api/client";
import { useAuthStore } from "../../shared/stores/authStore";
import { useToastStore } from "../../shared/components/Toast/toastStore";
import { linkedSearch } from "../video/RecordingsPage";
import { SafetyPage, recordingLink } from "./SafetyPage";
import { changeIncidentStatus, listAlerts, toIncident } from "./api";
import { NEXT_STATUSES, dayBounds } from "./labels";

const BUS = "01ARZ3NDEKTSV4RRFFQ69G5BUS";
const DEVICE = "01ARZ3NDEKTSV4RRFFQ69G5DEV";

const ALERT_WIRE = {
  id: "a1",
  organization_id: "org",
  vehicle_id: BUS,
  device_id: DEVICE,
  alarm_type: "sos",
  is_critical: true,
  status: "open",
  raised_at: "2026-10-01T06:00:00Z",
  last_raised_at: "2026-10-01T06:00:00Z",
  received_at: "2026-10-01T06:00:02Z",
  is_late: false,
  occurrences: 1,
  latitude: 2.04,
  longitude: 45.34,
  speed_kph: 32,
  trip_id: "t1",
  driver_id: null,
  incident_id: null,
  device_confirmation: null,
  acknowledged_at: null,
  closed_at: null,
};

const INCIDENT_WIRE = {
  id: "i1",
  organization_id: "org",
  category: "medical",
  severity: "high",
  status: "open",
  occurred_at: "2026-10-01T06:00:00Z",
  vehicle_id: BUS,
  trip_id: null,
  route_id: null,
  title: "Child unwell",
  description: "Felt faint",
  actions_taken: null,
  resolution: null,
  recorded_in_error: false,
  staff_ids: [],
  staff_names: [],
  student_ids: [],
  student_names: [],
  source_alert_id: null,
  closed_at: null,
  created_at: "2026-10-01T06:05:00Z",
  notes: [{ id: "n1", kind: "note", body: "Called the school nurse", author_id: "u1", created_at: "2026-10-01T06:10:00Z" }],
  private_fields_visible: true,
};

const HIDDEN_INCIDENT = {
  ...INCIDENT_WIRE,
  title: null,
  description: null,
  notes: [],
  private_fields_visible: false,
};

function route(path: string, incident: object = INCIDENT_WIRE): unknown {
  if (path.startsWith("/safety-alerts?")) return [ALERT_WIRE];
  if (path.startsWith("/safety-alerts/")) return { ...ALERT_WIRE, status: "acknowledged", device_confirmation: "requested" };
  if (path.startsWith("/incidents?")) return [incident];
  if (path.startsWith("/incidents/")) return incident;
  if (path.startsWith("/vehicles")) return { data: [{ id: BUS, plate_no: "KB-12", label: null }], page: { total: 1, page: 1, page_size: 100 } };
  return { data: [], page: { total: 0, page: 1, page_size: 100 } };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SafetyPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("safety api", () => {
  beforeEach(() => vi.mocked(apiRequest).mockReset());

  it("repeats the status filter and maps an alert", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce([ALERT_WIRE]);
    const [alert] = await listAlerts({ statuses: ["open", "acknowledged"], vehicleId: BUS });
    expect(apiRequest).toHaveBeenCalledWith(`/safety-alerts?status=open&status=acknowledged&vehicle_id=${BUS}`);
    expect(alert).toMatchObject({ alarmType: "sos", deviceId: DEVICE, speedKph: 32, isCritical: true });
  });

  it("sends recorded_in_error with a status change", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(INCIDENT_WIRE);
    await changeIncidentStatus("i1", { status: "closed", resolution: "Done", recordedInError: true });
    expect(apiRequest).toHaveBeenCalledWith("/incidents/i1/status", {
      method: "POST",
      body: { status: "closed", resolution: "Done", recorded_in_error: true },
    });
  });

  it("maps withheld fields as withheld", () => {
    expect(toIncident(HIDDEN_INCIDENT)).toMatchObject({ title: null, notes: [], privateFieldsVisible: false });
  });
});

describe("labels and links", () => {
  it("never offers a transition the server refuses", () => {
    expect(NEXT_STATUSES.closed).toEqual([]);
    expect(NEXT_STATUSES.investigating).not.toContain("open");
  });

  it("bounds a day in local time", () => {
    const { start, end } = dayBounds("2026-10-01");
    expect(new Date(end).getTime() - new Date(start).getTime()).toBe(24 * 3600 * 1000);
  });

  it("opens the recorder ten minutes either side of the alarm", () => {
    const link = recordingLink(DEVICE, "2026-10-01T06:00:00Z");
    const parsed = linkedSearch(link.slice(link.indexOf("?")));
    expect(parsed?.deviceId).toBe(DEVICE);
    expect(parsed?.start.toISOString()).toBe("2026-10-01T05:50:00.000Z");
    expect(parsed?.end.toISOString()).toBe("2026-10-01T06:10:00.000Z");
    expect(linkedSearch("?device=x&at=not-a-date")).toBeNull();
  });
});

describe("SafetyPage", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
    vi.mocked(apiRequest).mockImplementation(async (path: string) => route(path) as never);
    useAuthStore.setState({ principal: { userId: "u1", role: "org_admin", organizationId: "org", regionIds: [] } });
    useToastStore.setState({ toasts: [] });
  });

  it("lists an open SOS with its bus and the recording link, and acknowledges it on the terminal", async () => {
    renderPage();
    const alerts = await screen.findByRole("region", { name: "Safety alerts" });
    expect(await within(alerts).findByText(/KB-12/)).toBeInTheDocument();
    expect(within(alerts).getByText("SOS / panic button")).toBeInTheDocument();
    expect(within(alerts).getByRole("link", { name: "Open the recording at that time" })).toHaveAttribute(
      "href",
      recordingLink(DEVICE, ALERT_WIRE.raised_at),
    );
    await userEvent.click(within(alerts).getByRole("button", { name: "Acknowledge" }));
    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/safety-alerts/a1/acknowledge", { method: "POST", body: {} }));
    await waitFor(() =>
      expect(useToastStore.getState().toasts.at(-1)?.description).toBe("The bus terminal has been asked to clear its SOS."),
    );
  });

  it("turns an alert into an incident and opens it", async () => {
    renderPage();
    const alerts = await screen.findByRole("region", { name: "Safety alerts" });
    await userEvent.click(await within(alerts).findByRole("button", { name: "Record incident" }));
    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/incidents/from-alert/a1", { method: "POST", body: {} }));
    expect(await screen.findByText("Called the school nurse")).toBeInTheDocument();
  });

  it("will not close an incident without a resolution", async () => {
    renderPage();
    await userEvent.click(screen.getByRole("tab", { name: "Incident log" }));
    await userEvent.click(await screen.findByRole("button", { name: "Child unwell" }));
    await userEvent.click(await screen.findByRole("button", { name: "Change status" }));
    const dialog = await screen.findByRole("dialog", { name: "Move this incident on" });
    await userEvent.selectOptions(within(dialog).getByLabelText("New status"), "closed");
    const confirm = within(dialog).getByRole("button", { name: "Change status" });
    expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("Resolution"), "Collected by parents");
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith("/incidents/i1/status", {
        method: "POST",
        body: { status: "closed", resolution: "Collected by parents", recorded_in_error: false },
      }),
    );
  });

  it("cannot notify parents until students are linked", async () => {
    renderPage();
    await userEvent.click(screen.getByRole("tab", { name: "Incident log" }));
    await userEvent.click(await screen.findByRole("button", { name: "Child unwell" }));
    expect(await screen.findByRole("button", { name: "Notify parents" })).toBeDisabled();
  });

  it("gives read-only roles no actions and says what is withheld", async () => {
    useAuthStore.setState({ principal: { userId: "u2", role: "support_staff", organizationId: null, regionIds: [] } });
    vi.mocked(apiRequest).mockImplementation(async (path: string) => route(path, HIDDEN_INCIDENT) as never);
    renderPage();
    const alerts = await screen.findByRole("region", { name: "Safety alerts" });
    await within(alerts).findByText("SOS / panic button");
    expect(within(alerts).queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
    expect(within(alerts).queryByRole("link")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Incident log" }));
    expect(screen.queryByRole("button", { name: "Record an incident" })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Medical" }));
    expect(await screen.findByText(/visible to the school's Org Admins only/)).toBeInTheDocument();
  });
});
