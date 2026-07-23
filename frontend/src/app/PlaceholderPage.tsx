import { Construction } from "lucide-react";
import { usePageHeader } from "./layout/PageHeaderContext";
import styles from "./PlaceholderPage.module.css";

export interface PlaceholderPageProps {
  title: string;
  subtitle?: string;
}

/** Every nav item routes somewhere real today — either a built feature or this honest
 * "not built yet" state — rather than a dead link or a 404. Replaced module-by-module as each
 * roadmap phase (`docs/architecture/frontend-flutter-master-roadmap.md`) lands. */
export function PlaceholderPage({ title, subtitle }: PlaceholderPageProps) {
  usePageHeader(title, subtitle);

  return (
    <div className={styles.wrap}>
      <span className={styles.icon}>
        <Construction size={24} />
      </span>
      <div className={styles.title}>{title}</div>
      <p className={styles.description}>
        This module is being built next, following the approved implementation roadmap. Check
        back soon.
      </p>
    </div>
  );
}
