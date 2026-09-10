import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { useAuthStore } from "../../shared/stores/authStore";
import { Sidebar } from "./Sidebar";
import { getNavForRole, platformNav, organizationNav } from "./navConfig";

/**
 * The 2026-09-05 sidebar redesign turned the flat `navConfig` list into collapsible groups. The
 * grouping is derived at render time rather than by restructuring `navConfig` (see `Sidebar.tsx`),
 * so these tests cover the derivation itself — what `navConfig.test.ts` cannot see.
 */

function renderSidebar(
  nav = getNavForRole(platformNav, "founder"),
  props: Partial<React.ComponentProps<typeof Sidebar>> = {},
) {
  return render(
    <MemoryRouter initialEntries={["/platform"]}>
      <Sidebar nav={nav} {...props} />
    </MemoryRouter>,
  );
}

describe("Sidebar — collapsible groups", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
  });

  it("renders a section header as an expanded disclosure control over its own links", () => {
    renderSidebar();

    const platformGroup = screen.getByRole("button", { name: /platform/i });
    expect(platformGroup).toHaveAttribute("aria-expanded", "true");

    // The example from the brief: Platform -> Organizations, Regions.
    expect(screen.getByRole("link", { name: "Organizations" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Regions" })).toBeInTheDocument();
  });

  it("collapses and re-expands a group when its header is clicked", async () => {
    const user = userEvent.setup();
    renderSidebar();

    const fleetGroup = screen.getByRole("button", { name: /fleet/i });
    expect(fleetGroup).toHaveAttribute("aria-expanded", "true");

    await user.click(fleetGroup);
    expect(fleetGroup).toHaveAttribute("aria-expanded", "false");

    await user.click(fleetGroup);
    expect(fleetGroup).toHaveAttribute("aria-expanded", "true");
  });

  it("remembers which groups were collapsed across a remount", async () => {
    const user = userEvent.setup();
    const first = renderSidebar();

    await user.click(screen.getByRole("button", { name: /operations/i }));
    first.unmount();

    renderSidebar();
    expect(screen.getByRole("button", { name: /operations/i })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  /** A disclosure control that reveals exactly one row is friction, so a single-item group is
   * promoted to a plain top-level link. "Overview" holds only Dashboard, and this happens for
   * real when role filtering narrows a group too — see the Finance Staff case below. */
  it("promotes a single-item group to a top-level link with no disclosure control", () => {
    renderSidebar();

    expect(screen.queryByRole("button", { name: /^overview$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("promotes a group that role filtering has narrowed to one item", () => {
    // Finance Staff sees only Organizations under "Platform", so that group stops being a group.
    renderSidebar(getNavForRole(platformNav, "finance_staff"));

    expect(screen.queryByRole("button", { name: /^platform$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Organizations" })).toBeInTheDocument();
    // "Business" still holds three links for this role, so it remains a real group.
    expect(screen.getByRole("button", { name: /^business$/i })).toBeInTheDocument();
  });

  it("keeps every nav link reachable — grouping never drops one", () => {
    const nav = getNavForRole(organizationNav, "org_admin");
    renderSidebar(nav);

    const expectedLabels = nav.filter((item) => item.type === "link").map((item) => item.label);
    for (const label of expectedLabels) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("exposes a collapse toggle only when the shell supplies a handler", () => {
    const { unmount } = renderSidebar(undefined, {});
    expect(screen.queryByRole("button", { name: /collapse sidebar/i })).not.toBeInTheDocument();
    unmount();

    renderSidebar(undefined, { onToggleCollapsed: () => {} });
    expect(screen.getByRole("button", { name: /collapse sidebar/i })).toBeInTheDocument();
  });

  it("hides group headers in rail mode but keeps every link present", () => {
    const nav = getNavForRole(platformNav, "founder");
    renderSidebar(nav, { collapsed: true, onToggleCollapsed: () => {} });

    // No disclosure controls at all — a rail has no room for a group label.
    expect(screen.queryByRole("button", { name: /^fleet$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /expand sidebar/i })).toBeInTheDocument();

    for (const item of nav) {
      if (item.type === "link") {
        expect(screen.getByRole("link", { name: item.label })).toBeInTheDocument();
      }
    }
  });

  it("shows the signed-in role in the sidebar account block", () => {
    renderSidebar();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    // Rendered outside the nav landmark, so scope the assertion away from the nav links.
    expect(within(nav).queryByText("Founder")).not.toBeInTheDocument();
    expect(screen.getByText("Founder")).toBeInTheDocument();
    expect(screen.getByText("RAAD Platform")).toBeInTheDocument();
  });
});
