import { Link } from "react-router-dom";
import { Bus, CreditCard, FileText, ReceiptText, Users } from "lucide-react";
import styles from "../DashboardHomePage.module.css";

/**
 * Organization Dashboard quick actions — the handful of destinations an Org Admin's own working
 * day actually starts from. Plain routed links to pages that already exist and are already
 * reachable from the sidebar (`organizationNav`); this is a shortcut, not a second navigation
 * system, so it names nothing the nav itself does not already offer.
 */
const ORG_QUICK_ACTIONS = [
  { to: "/org/students", label: "Students", icon: Users },
  { to: "/org/vehicles", label: "Vehicles", icon: Bus },
  { to: "/org/finance", label: "School Finance", icon: ReceiptText },
  { to: "/org/billing", label: "Billing", icon: CreditCard },
  { to: "/org/reports", label: "Reports", icon: FileText },
];

export function QuickActionsSection() {
  return (
    <div className={styles.quickActions}>
      {ORG_QUICK_ACTIONS.map(({ to, label, icon: Icon }) => (
        <Link key={to} to={to} className={styles.quickAction}>
          <Icon size={15} />
          {label}
        </Link>
      ))}
    </div>
  );
}
