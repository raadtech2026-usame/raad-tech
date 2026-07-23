import type { Role } from "../api/types";

/** Presentation-only metadata per role — label text, a two-letter avatar abbreviation, and an
 * accent color. Not an authorization source: the backend's `role_permissions` matrix is the
 * only real authority (`.claude/rules/frontend.md` #2). */
export interface RoleDisplay {
  label: string;
  abbreviation: string;
  color: string;
}

const ROLE_DISPLAY: Record<Role, RoleDisplay> = {
  founder: { label: "Founder", abbreviation: "FO", color: "#1E63FF" },
  regional_manager: { label: "Regional Manager", abbreviation: "RM", color: "#6366F1" },
  support_staff: { label: "Support Staff", abbreviation: "SS", color: "#7C3AED" },
  finance_staff: { label: "Finance Staff", abbreviation: "FS", color: "#0D9488" },
  org_admin: { label: "Org Admin", abbreviation: "OA", color: "#0891B2" },
  driver: { label: "Driver", abbreviation: "DR", color: "#2FBF4F" },
  parent: { label: "Parent", abbreviation: "PA", color: "#F5A524" },
};

export function getRoleDisplay(role: Role): RoleDisplay {
  return ROLE_DISPLAY[role];
}
