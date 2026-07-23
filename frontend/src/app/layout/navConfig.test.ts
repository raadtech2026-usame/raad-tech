import { describe, expect, it } from "vitest";
import { getNavForRole, platformNav, organizationNav } from "./navConfig";

function linkPaths(nav: ReturnType<typeof getNavForRole>): string[] {
  return nav.filter((item) => item.type === "link").map((item) => item.path);
}

function headerLabels(nav: ReturnType<typeof getNavForRole>): string[] {
  return nav.filter((item) => item.type === "header").map((item) => item.label);
}

describe("getNavForRole — platform nav", () => {
  it("gives founder every platform nav item, unfiltered", () => {
    const nav = getNavForRole(platformNav, "founder");
    expect(linkPaths(nav)).toEqual(linkPaths(platformNav));
  });

  it("restricts finance_staff to dashboard/organizations/billing/reports only", () => {
    const nav = getNavForRole(platformNav, "finance_staff");
    expect(linkPaths(nav)).toEqual([
      "/platform",
      "/platform/organizations",
      "/platform/reports",
      "/platform/billing",
    ]);
  });

  it("never leaves a dangling section header with no links under it", () => {
    const nav = getNavForRole(platformNav, "finance_staff");
    // Every header in the filtered result must be followed by at least one link.
    for (let i = 0; i < nav.length; i++) {
      if (nav[i].type === "header") {
        expect(nav[i + 1]?.type).toBe("link");
      }
    }
  });

  it("never renders a trailing header as the last item", () => {
    const nav = getNavForRole(platformNav, "finance_staff");
    expect(nav[nav.length - 1]?.type).toBe("link");
  });

  it("excludes Live Video from every platform role (Org-Admin only per api.md #2)", () => {
    for (const role of ["founder", "regional_manager", "support_staff", "finance_staff"] as const) {
      const nav = getNavForRole(platformNav, role);
      expect(linkPaths(nav)).not.toContain("/platform/video");
    }
    expect(linkPaths(platformNav)).not.toContain("/platform/video");
  });

  it("has no 'Organizations' management link at all — platform-exclusive by design", () => {
    expect(linkPaths(organizationNav)).not.toContain("/platform/organizations");
    expect(linkPaths(organizationNav).some((p) => p.includes("organizations"))).toBe(false);
  });

  it("restricts Regions to founder only (Device Domain Overhaul architecture review)", () => {
    expect(linkPaths(getNavForRole(platformNav, "founder"))).toContain("/platform/regions");
    for (const role of ["regional_manager", "support_staff", "finance_staff"] as const) {
      expect(linkPaths(getNavForRole(platformNav, role))).not.toContain("/platform/regions");
    }
  });
});

describe("getNavForRole — organization nav", () => {
  it("gives org_admin the full organization nav, including Live Video", () => {
    const nav = getNavForRole(organizationNav, "org_admin");
    expect(linkPaths(nav)).toEqual(linkPaths(organizationNav));
    expect(linkPaths(nav)).toContain("/org/video");
  });

  it("keeps every section header present for org_admin (nothing restricted)", () => {
    const nav = getNavForRole(organizationNav, "org_admin");
    expect(headerLabels(nav)).toEqual(headerLabels(organizationNav));
  });

  it("has no 'Devices' link at all — RAAD owns and manages all hardware, schools never see it", () => {
    expect(linkPaths(organizationNav)).not.toContain("/org/devices");
  });
});
