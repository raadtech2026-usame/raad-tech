import { describe, expect, it } from "vitest";
import { getDashboardType, getDashboardHomePath } from "./dashboard";
import type { Role } from "../api/types";

describe("getDashboardType", () => {
  const platformRoles: Role[] = ["founder", "regional_manager", "support_staff", "finance_staff"];

  it.each(platformRoles)("maps %s to the platform dashboard", (role) => {
    expect(getDashboardType(role)).toBe("platform");
  });

  it("maps org_admin to the organization dashboard", () => {
    expect(getDashboardType("org_admin")).toBe("organization");
  });

  it.each(["driver", "parent"] as Role[])("maps %s to unsupported (mobile-only)", (role) => {
    expect(getDashboardType(role)).toBe("unsupported");
  });
});

describe("getDashboardHomePath", () => {
  it("sends platform roles to /platform", () => {
    expect(getDashboardHomePath("founder")).toBe("/platform");
    expect(getDashboardHomePath("regional_manager")).toBe("/platform");
  });

  it("sends org_admin to /org", () => {
    expect(getDashboardHomePath("org_admin")).toBe("/org");
  });

  it("sends driver/parent to /mobile-only", () => {
    expect(getDashboardHomePath("driver")).toBe("/mobile-only");
    expect(getDashboardHomePath("parent")).toBe("/mobile-only");
  });
});
