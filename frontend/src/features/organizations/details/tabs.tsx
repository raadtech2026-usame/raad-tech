import type { ReactNode } from "react";
import {
  Banknote,
  Building2,
  Bus,
  CreditCard,
  FileText,
  GaugeCircle,
  HardDrive,
  Landmark,
  Map,
  ReceiptText,
  ScrollText,
  Settings,
  UserCog,
  Users,
  Wallet,
} from "lucide-react";

/**
 * The Organization Details tab set.
 *
 * Ordered the way a Founder actually works a tenant: who they are, what they pay, who uses it,
 * what they operate, what they owe, and finally the history and the knobs. Grouping is by
 * question, not by which backend module happens to own the data.
 */

export type OrganizationDetailTabId =
  | "overview"
  | "subscription"
  | "users"
  | "vehicles"
  | "devices"
  | "students"
  | "parents"
  | "routes"
  | "drivers"
  | "invoices"
  | "payments"
  | "finance"
  | "usage"
  | "audit"
  | "settings";

export interface OrganizationDetailTab {
  id: OrganizationDetailTabId;
  label: string;
  description: string;
  icon: ReactNode;
}

export const ORGANIZATION_DETAIL_TABS: OrganizationDetailTab[] = [
  {
    id: "overview",
    label: "Overview",
    description: "Identity, region, hierarchy and lifecycle",
    icon: <Building2 size={18} />,
  },
  {
    id: "subscription",
    label: "Subscription",
    description: "The RAAD plan this organization pays for",
    icon: <CreditCard size={18} />,
  },
  {
    id: "users",
    label: "Users",
    description: "Accounts that can sign in to this organization",
    icon: <UserCog size={18} />,
  },
  {
    id: "vehicles",
    label: "Vehicles",
    description: "Buses operated by this organization",
    icon: <Bus size={18} />,
  },
  {
    id: "devices",
    label: "Devices",
    description: "GPS/MDVR hardware RAAD has allocated",
    icon: <HardDrive size={18} />,
  },
  {
    id: "students",
    label: "Students",
    description: "Count only — RAAD does not manage student records",
    icon: <Users size={18} />,
  },
  {
    id: "parents",
    label: "Parents",
    description: "Count only — RAAD does not manage family records",
    icon: <Users size={18} />,
  },
  {
    id: "routes",
    label: "Routes",
    description: "Defined bus routes and their stops",
    icon: <Map size={18} />,
  },
  {
    id: "drivers",
    label: "Drivers",
    description: "Drivers registered by this organization",
    icon: <UserCog size={18} />,
  },
  {
    id: "invoices",
    label: "Invoices",
    description: "RAAD invoices issued to this organization",
    icon: <ReceiptText size={18} />,
  },
  {
    id: "payments",
    label: "Payments",
    description: "Payment attempts against those invoices",
    icon: <Wallet size={18} />,
  },
  {
    id: "finance",
    label: "Finance",
    description: "The school's own student billing — a separate money flow",
    icon: <Landmark size={18} />,
  },
  {
    id: "usage",
    label: "Usage",
    description: "What this organization consumes against its plan",
    icon: <GaugeCircle size={18} />,
  },
  {
    id: "audit",
    label: "Audit",
    description: "Everything that has happened to this organization",
    icon: <ScrollText size={18} />,
  },
  {
    id: "settings",
    label: "Settings",
    description: "Lifecycle actions and configuration",
    icon: <Settings size={18} />,
  },
];

/** Icons reused by the Finance tab's own sub-sections. */
export const FINANCE_ICONS = { invoices: <FileText size={16} />, money: <Banknote size={16} /> };
