import {
  LayoutDashboard,
  Building2,
  Globe,
  Truck,
  Cpu,
  UserRound,
  Users,
  Contact,
  Navigation,
  CalendarClock,
  Radio,
  Video,
  Bell,
  FileText,
  CreditCard,
  Settings,
  UsersRound,
  ScrollText,
  type LucideIcon,
} from "lucide-react";
import type { Role } from "../../shared/api/types";

export interface NavLinkItem {
  type: "link";
  label: string;
  icon: LucideIcon;
  path: string;
  /** Omit to allow every role this nav tree is already scoped to (per `getDashboardType`).
   * Present only for the few items a subset of platform roles shouldn't see — e.g. Finance
   * Staff's documented "billing scope only" (`.claude/rules/security.md` #3) excludes the
   * operational fleet/people/ops items a Founder or Support Staff member would use. This is
   * still only presentation — the backend's own RBAC matrix is the real gate
   * (`.claude/rules/frontend.md` #2). */
  roles?: Role[];
}

export interface NavHeaderItem {
  type: "header";
  label: string;
}

export type NavItem = NavLinkItem | NavHeaderItem;

const FINANCE_ALLOWED_PATHS = new Set(["/platform", "/platform/organizations", "/platform/billing", "/platform/reports"]);

function link(label: string, icon: LucideIcon, path: string, roles?: Role[]): NavLinkItem {
  return { type: "link", label, icon, path, roles };
}

function header(label: string): NavHeaderItem {
  return { type: "header", label };
}

/**
 * Founder / Regional Manager / Support Staff / Finance Staff. Manages the whole platform across
 * every organization — scoped server-side by RBAC + `ScopeResolver`, not by this list.
 *
 * Live Video is deliberately absent here: `.claude/rules/api.md` #2 documents `/video` as
 * "Org-Admin only" — not "Org-Admin plus RAAD staff" — so no platform role gets a Live Video nav
 * entry at all, only the organization nav below does.
 *
 * **No "Students"/"Parents" entries either** (platform verification, 2026-07-29) — CLAUDE.md's
 * own Business Model section already says RAAD does not manage students or parents directly;
 * the original `5437a5d1651b` seed granting founder/regional_manager/support_staff platform-wide
 * `transport_ops.students.*`/`.parents.*` access was a real deviation from that, corrected by
 * migration `c4d9a2e6f813`. `organizationNav` below keeps both — each Organization manages its
 * own students/parents, unaffected.
 */
export const platformNav: NavItem[] = [
  header("Overview"),
  link("Dashboard", LayoutDashboard, "/platform"),
  header("Platform"),
  link("Organizations", Building2, "/platform/organizations"),
  link("Regions", Globe, "/platform/regions", ["founder"]),
  header("Fleet"),
  link("Vehicles", Truck, "/platform/vehicles"),
  link("Devices", Cpu, "/platform/devices"),
  link("Drivers", UserRound, "/platform/drivers"),
  header("Operations"),
  link("Routes", Navigation, "/platform/routes"),
  link("Trips", CalendarClock, "/platform/trips"),
  link("Live Tracking", Radio, "/platform/tracking"),
  link("Notifications", Bell, "/platform/notifications"),
  header("Business"),
  link("Reports", FileText, "/platform/reports"),
  link("Billing", CreditCard, "/platform/billing"),
  header("Admin"),
  link("Users & Roles", UsersRound, "/platform/users"),
  link("Audit Log", ScrollText, "/platform/audit"),
  link("System Settings", Settings, "/platform/settings"),
];

/** Org Admin only. Organizations are *created from* the platform dashboard above; this dashboard
 * shows only the signed-in Org Admin's own organization (`organization_id` scoping is enforced
 * server-side — this nav tree simply has no "Organizations" entry, since creating tenants isn't
 * this role's job at all).
 *
 * **No "Devices" entry either** (Device Domain Overhaul architecture review) — RAAD owns and
 * manages all GPS/MDVR hardware; schools never register, configure, or view raw device records,
 * not even read-only. Device-connectivity visibility is folded into `router.tsx`'s
 * `VehiclesPage` instead (a "Tracking" drawer section carrying no device identifier). */
export const organizationNav: NavItem[] = [
  header("Overview"),
  link("Dashboard", LayoutDashboard, "/org"),
  header("Fleet"),
  link("Vehicles", Truck, "/org/vehicles"),
  link("Drivers", UserRound, "/org/drivers"),
  header("People"),
  link("Students", Users, "/org/students"),
  link("Parents", Contact, "/org/parents"),
  header("Operations"),
  link("Routes", Navigation, "/org/routes"),
  link("Trips", CalendarClock, "/org/trips"),
  link("Live Tracking", Radio, "/org/tracking"),
  link("Live Video", Video, "/org/video"),
  link("Notifications", Bell, "/org/notifications"),
  header("Business"),
  link("Reports", FileText, "/org/reports"),
  link("Billing", CreditCard, "/org/billing"),
  header("Settings"),
  link("Users & Roles", UsersRound, "/org/users"),
  link("Organization Settings", Settings, "/org/settings"),
];

/** Filters a nav tree for the given role, then drops any header left with no links beneath it
 * (e.g. Finance Staff loses every item under "Fleet"/"People"/"Operations"/"Admin", so those
 * section headers must disappear too, not render as empty labels). */
export function getNavForRole(nav: NavItem[], role: Role): NavItem[] {
  const visible = nav.filter((item) => {
    if (item.type === "header") {
      return true;
    }
    if (role === "finance_staff") {
      return FINANCE_ALLOWED_PATHS.has(item.path);
    }
    return !item.roles || item.roles.includes(role);
  });

  const result: NavItem[] = [];
  for (let i = 0; i < visible.length; i++) {
    const item = visible[i];
    if (item.type === "header") {
      const next = visible[i + 1];
      if (!next || next.type === "header") {
        continue;
      }
    }
    result.push(item);
  }
  return result;
}
