import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../../shared/api/client";
import {
  countParents,
  findParentByExactPhone,
  generateParentInvoices,
  getParent,
  getParentBillingProfile,
  getParentFinancialSummary,
  getParentInvoiceDetail,
  linkStudentToParent,
  listOrganizationsForPicker,
  listParentInvoices,
  listParents,
  listParentsForPicker,
  listStudentsForParent,
  registerParent,
  saveParentBillingProfile,
  setParentInvoicePaymentStatus,
  unlinkStudentFromParent,
  updateParent,
  updateParentStatus,
} from "./api";

const PARENT_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
  organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  user_id: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
  full_name: "Fatima Ali",
  phone: "+252612345678",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
  alternate_phone: "+252611111111",
  address: "Hodan District, Mogadishu",
  emergency_contact_name: "Ahmed Hassan",
  emergency_contact_phone: "+252622222222",
  notes: "Prefers SMS.",
};

const PARENT_SUMMARY_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
  full_name: "Fatima Ali",
  status: "active",
};

const ORG_WIRE = {
  data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }],
  page: { total: 1, page: 1, page_size: 100 },
};

describe("parents api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listParents builds the offset query string and maps the summary envelope to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [PARENT_SUMMARY_WIRE],
      page: { total: 1, page: 1, page_size: 25 },
    });

    const result = await listParents({
      page: 1,
      pageSize: 25,
      sort: { field: "full_name", direction: "asc" },
      filters: { status: "active" },
      search: "fatima",
    });

    expect(apiRequest).toHaveBeenCalledWith(
      "/parents?page=1&page_size=25&sort=full_name&filter%5Bstatus%5D=active&q=fatima",
    );
    expect(result).toEqual({
      data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FCX", fullName: "Fatima Ali", status: "active" }],
      page: { total: 1, page: 1, pageSize: 25 },
    });
  });

  it("countParents calls the count-only route and returns just the total", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ total: 7 });

    const result = await countParents();

    expect(apiRequest).toHaveBeenCalledWith("/parents/count");
    expect(result).toBe(7);
  });

  it("getParent maps the full response to camelCase, including the additive profile fields", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(PARENT_WIRE);

    const result = await getParent("01ARZ3NDEKTSV4RRFFQ69G5FCX");

    expect(apiRequest).toHaveBeenCalledWith("/parents/01ARZ3NDEKTSV4RRFFQ69G5FCX");
    expect(result).toEqual({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      userId: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
      fullName: "Fatima Ali",
      phone: "+252612345678",
      status: "active",
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-02T00:00:00Z",
      alternatePhone: "+252611111111",
      address: "Hodan District, Mogadishu",
      emergencyContactName: "Ahmed Hassan",
      emergencyContactPhone: "+252622222222",
      notes: "Prefers SMS.",
    });
  });

  it("registerParent posts the current RegisterParentRequest shape (no user_id) and unwraps ParentCreatedResponse", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      parent: PARENT_WIRE,
      temporary_password: "Tmp-Pass-123",
    });

    const result = await registerParent({
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      fullName: "Fatima Ali",
      email: "fatima@example.com",
      phone: "+252612345678",
    });

    expect(apiRequest).toHaveBeenCalledWith("/parents", {
      method: "POST",
      body: {
        organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        full_name: "Fatima Ali",
        email: "fatima@example.com",
        phone: "+252612345678",
        alternate_phone: null,
        address: null,
        emergency_contact_name: null,
        emergency_contact_phone: null,
        notes: null,
        children: undefined,
        route_id: null,
        pickup_stop_id: null,
        dropoff_stop_id: null,
        vehicle_id: null,
      },
    });
    expect(result.parent.fullName).toBe("Fatima Ali");
    expect(result.temporaryPassword).toBe("Tmp-Pass-123");
  });

  it("updateParentStatus PATCHes only the status field", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...PARENT_WIRE, status: "inactive" });

    const result = await updateParentStatus("01ARZ3NDEKTSV4RRFFQ69G5FCX", "inactive");

    expect(apiRequest).toHaveBeenCalledWith("/parents/01ARZ3NDEKTSV4RRFFQ69G5FCX", {
      method: "PATCH",
      body: { status: "inactive" },
    });
    expect(result.status).toBe("inactive");
  });

  it("updateParent PATCHes the full editable profile, never status", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(PARENT_WIRE);

    await updateParent("01ARZ3NDEKTSV4RRFFQ69G5FCX", {
      fullName: "Fatima Ali",
      phone: "+252612345678",
      alternatePhone: "+252611111111",
      address: "Hodan District, Mogadishu",
      emergencyContactName: "Ahmed Hassan",
      emergencyContactPhone: "+252622222222",
      notes: "Prefers SMS.",
    });

    expect(apiRequest).toHaveBeenCalledWith("/parents/01ARZ3NDEKTSV4RRFFQ69G5FCX", {
      method: "PATCH",
      body: {
        full_name: "Fatima Ali",
        phone: "+252612345678",
        alternate_phone: "+252611111111",
        address: "Hodan District, Mogadishu",
        emergency_contact_name: "Ahmed Hassan",
        emergency_contact_phone: "+252622222222",
        notes: "Prefers SMS.",
      },
    });
  });

  it("listStudentsForParent maps the raw array response to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce([
      {
        student_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        full_name: "Amina Hassan",
        status: "active",
        relationship: "Mother",
        is_primary: true,
      },
    ]);

    const result = await listStudentsForParent("01ARZ3NDEKTSV4RRFFQ69G5FCX");

    expect(apiRequest).toHaveBeenCalledWith("/parents/01ARZ3NDEKTSV4RRFFQ69G5FCX/students");
    expect(result).toEqual([
      {
        studentId: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        fullName: "Amina Hassan",
        status: "active",
        relationship: "Mother",
        isPrimary: true,
      },
    ]);
  });

  it("unlinkStudentFromParent issues a DELETE against the nested link route, student id last", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(undefined);

    await unlinkStudentFromParent("01ARZ3NDEKTSV4RRFFQ69G5FCX", "01ARZ3NDEKTSV4RRFFQ69G5FAV");

    expect(apiRequest).toHaveBeenCalledWith(
      "/students/01ARZ3NDEKTSV4RRFFQ69G5FAV/parents/01ARZ3NDEKTSV4RRFFQ69G5FCX",
      { method: "DELETE" },
    );
  });

  it("listOrganizationsForPicker maps the page envelope to a minimal option list", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(ORG_WIRE);

    const result = await listOrganizationsForPicker("green");

    expect(apiRequest).toHaveBeenCalledWith(
      "/organizations?page=1&page_size=100&sort=name&filter%5Bstatus%5D=active&q=green",
    );
    expect(result).toEqual([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }]);
  });

  it("listParentsForPicker searches by name or phone and maps to a minimal option list", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [PARENT_SUMMARY_WIRE],
      page: { total: 1, page: 1, page_size: 100 },
    });

    const result = await listParentsForPicker("+2526");

    expect(apiRequest).toHaveBeenCalledWith(
      "/parents?page=1&page_size=100&sort=full_name&filter%5Bstatus%5D=active&q=%2B2526",
    );
    expect(result).toEqual([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FCX", fullName: "Fatima Ali", status: "active" }]);
  });

  it("findParentByExactPhone filters by an exact phone match and returns the first match or null", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [PARENT_SUMMARY_WIRE],
      page: { total: 1, page: 1, page_size: 1 },
    });

    const result = await findParentByExactPhone("+252612345678");

    expect(apiRequest).toHaveBeenCalledWith(
      "/parents?page=1&page_size=1&sort=full_name&filter%5Bphone%5D=%2B252612345678",
    );
    expect(result).toEqual({ id: "01ARZ3NDEKTSV4RRFFQ69G5FCX", fullName: "Fatima Ali", status: "active" });
  });

  it("findParentByExactPhone returns null when nothing matches", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ data: [], page: { total: 0, page: 1, page_size: 1 } });

    const result = await findParentByExactPhone("+252699999999");

    expect(result).toBeNull();
  });

  it("getParentFinancialSummary maps the family-level summary to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      parent_id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
      currency: "USD",
      total_due: "60.00",
      total_paid: "30.00",
      outstanding: "30.00",
      status: "partially_paid",
      children: [
        {
          student_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
          full_name: "Mohamed Ahmed",
          status: "active",
          total_due: "30.00",
          total_paid: "30.00",
          outstanding: "0.00",
          invoice_count: 1,
        },
      ],
    });

    const result = await getParentFinancialSummary("01ARZ3NDEKTSV4RRFFQ69G5FCX");

    expect(apiRequest).toHaveBeenCalledWith("/school-finance/parents/01ARZ3NDEKTSV4RRFFQ69G5FCX/summary");
    expect(result.totalDue).toBe("60.00");
    expect(result.status).toBe("partially_paid");
    expect(result.children[0]).toEqual({
      studentId: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
      fullName: "Mohamed Ahmed",
      status: "active",
      totalDue: "30.00",
      totalPaid: "30.00",
      outstanding: "0.00",
      invoiceCount: 1,
    });
  });

  it("getParentBillingProfile returns null when the backend returns null", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(null);

    const result = await getParentBillingProfile("01ARZ3NDEKTSV4RRFFQ69G5FCX");

    expect(apiRequest).toHaveBeenCalledWith("/school-finance/parents/01ARZ3NDEKTSV4RRFFQ69G5FCX/billing-profile");
    expect(result).toBeNull();
  });

  it("saveParentBillingProfile PUTs the billing fields", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FBP0",
      organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      parent_id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
      monthly_fee: "80.00",
      currency: "USD",
      billing_start_period: "2026-09",
      due_day: 10,
      status: "active",
      created_at: "2026-09-10T08:00:00Z",
      updated_at: "2026-09-10T08:00:00Z",
    });

    const result = await saveParentBillingProfile("01ARZ3NDEKTSV4RRFFQ69G5FCX", {
      monthlyFee: "80.00",
      currency: "USD",
      billingStartPeriod: "2026-09",
      dueDay: 10,
    });

    expect(apiRequest).toHaveBeenCalledWith("/school-finance/parents/01ARZ3NDEKTSV4RRFFQ69G5FCX/billing-profile", {
      method: "PUT",
      body: { monthly_fee: "80.00", currency: "USD", billing_start_period: "2026-09", due_day: 10 },
    });
    expect(result.monthlyFee).toBe("80.00");
  });

  it("setParentInvoicePaymentStatus PATCHes status and amount", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FIV0",
      parent_id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
      parent_name: "Fatima Ali",
      period: "2026-09",
      invoice_number: "2026-09-G5FIV0",
      children_count: 1,
      amount: "80.00",
      amount_paid: "30.00",
      balance_due: "50.00",
      status: "partial",
      invoice_date: "2026-09-01",
      due_date: "2026-09-30",
      currency: "USD",
    });

    const result = await setParentInvoicePaymentStatus("01ARZ3NDEKTSV4RRFFQ69G5FIV0", {
      status: "partial",
      amountPaid: "30.00",
    });

    expect(apiRequest).toHaveBeenCalledWith(
      "/school-finance/parent-invoices/01ARZ3NDEKTSV4RRFFQ69G5FIV0/payment-status",
      { method: "PATCH", body: { status: "partial", amount_paid: "30.00" } },
    );
    expect(result.status).toBe("partial");
    expect(result.balanceDue).toBe("50.00");
  });

  it("generateParentInvoices posts the period and maps the created invoices", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce([]);

    const result = await generateParentInvoices("2026-09");

    expect(apiRequest).toHaveBeenCalledWith("/school-finance/parent-invoices/generate", {
      method: "POST",
      body: { period: "2026-09" },
    });
    expect(result).toEqual([]);
  });

  it("linkStudentToParent posts parent_id/relationship/is_primary", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(undefined);

    await linkStudentToParent("01ARZ3NDEKTSV4RRFFQ69G5FSTU", "01ARZ3NDEKTSV4RRFFQ69G5FCX", {
      relationship: "Father",
      isPrimary: false,
    });

    expect(apiRequest).toHaveBeenCalledWith("/students/01ARZ3NDEKTSV4RRFFQ69G5FSTU/parents", {
      method: "POST",
      body: { parent_id: "01ARZ3NDEKTSV4RRFFQ69G5FCX", relationship: "Father", is_primary: false },
    });
  });

  it("listParentInvoices builds the query string and maps real invoice rows", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [
        {
          id: "01ARZ3NDEKTSV4RRFFQ69G5FIV0",
          parent_id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
          parent_name: "Fatima Ali",
          period: "2026-09",
          invoice_number: "2026-09-G5FIV0",
          children_count: 2,
          amount: "60.00",
          amount_paid: "30.00",
          balance_due: "30.00",
          status: "partial",
          invoice_date: "2026-09-01",
          due_date: "2026-09-30",
          currency: "USD",
        },
      ],
      page: { total: 1, page: 1, page_size: 25 },
    });

    const result = await listParentInvoices({ page: 1, pageSize: 25, period: "2026-09", status: "partial" });

    expect(apiRequest).toHaveBeenCalledWith(
      "/school-finance/parent-invoices?page=1&page_size=25&period=2026-09&status=partial",
    );
    expect(result.data[0]).toMatchObject({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FIV0",
      parentId: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
      childrenCount: 2,
      status: "partial",
    });
    expect(result.page.total).toBe(1);
  });

  it("listParentInvoices includes vehicleId/dateFrom/dateTo in the query string when given", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ data: [], page: { total: 0, page: 1, page_size: 25 } });

    await listParentInvoices({
      page: 1,
      pageSize: 25,
      vehicleId: "01ARZ3NDEKTSV4RRFFQ69G5FBUS",
      dateFrom: "2026-09-01",
      dateTo: "2026-09-30",
    });

    expect(apiRequest).toHaveBeenCalledWith(
      "/school-finance/parent-invoices?page=1&page_size=25&vehicle_id=01ARZ3NDEKTSV4RRFFQ69G5FBUS&date_from=2026-09-01&date_to=2026-09-30",
    );
  });

  it("getParentInvoiceDetail maps the child line items", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FIV0",
      parent_id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
      parent_name: "Fatima Ali",
      period: "2026-09",
      invoice_number: "2026-09-G5FIV0",
      amount: "30.00",
      amount_paid: "30.00",
      balance_due: "0.00",
      status: "paid",
      currency: "USD",
      invoice_date: "2026-09-01",
      due_date: "2026-09-30",
      notes: null,
      lines: [
        {
          student_id: "01ARZ3NDEKTSV4RRFFQ69G5FSTU",
          full_name: "Mohamed Ahmed",
          amount: "30.00",
          vehicle_id: null,
          route_id: null,
        },
      ],
    });

    const detail = await getParentInvoiceDetail("01ARZ3NDEKTSV4RRFFQ69G5FIV0");

    expect(apiRequest).toHaveBeenCalledWith("/school-finance/parent-invoices/01ARZ3NDEKTSV4RRFFQ69G5FIV0");
    expect(detail.lines[0]).toMatchObject({ studentId: "01ARZ3NDEKTSV4RRFFQ69G5FSTU", amount: "30.00" });
  });
});
