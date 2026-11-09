import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../platform-analytics/api", () => ({
  listAuditEntries: vi.fn(),
}));

import * as analyticsApi from "../../platform-analytics/api";
import { AuditLogPage } from "./AuditLogPage";

const MOCK_ENTRY: analyticsApi.AuditEntry = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FA1",
  organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  actorUserId: "01ARZ3NDEKTSV4RRFFQ69G5FB1",
  action: "organization.registered",
  entityType: "organization",
  entityId: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  metadata: { name: "Green Valley School", plan: "starter" },
  createdAt: "2026-01-01T12:00:00Z",
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuditLogPage />
    </QueryClientProvider>,
  );
}

describe("AuditLogPage", () => {
  beforeEach(() => {
    vi.mocked(analyticsApi.listAuditEntries).mockReset();
    vi.mocked(analyticsApi.listAuditEntries).mockResolvedValue({
      data: [MOCK_ENTRY],
      page: { total: 1, page: 1, pageSize: 25 },
    });
  });

  it("renders audit log title and table with entry data", async () => {
    renderPage();

    expect(await screen.findByText("System Audit Log")).toBeInTheDocument();
    expect(await screen.findByText("organization.registered")).toBeInTheDocument();
    expect(await screen.findByText("organization")).toBeInTheDocument();
  });

  it("opens detail drawer when clicking a row", async () => {
    const user = userEvent.setup();
    renderPage();

    const row = await screen.findByText("organization.registered");
    await user.click(row);

    expect(await screen.findByText("Audit Entry Details")).toBeInTheDocument();
    expect(await screen.findByText("Actor User ID")).toBeInTheDocument();
  });
});
