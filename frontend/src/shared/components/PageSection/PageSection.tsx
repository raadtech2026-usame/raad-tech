import type { ReactNode } from "react";
import clsx from "clsx";
import styles from "./PageSection.module.css";

export interface PageSectionProps {
  /** Section eyebrow. Short — this is a wayfinding label above a band of content, not a title
   * competing with the card headers beneath it. */
  title: ReactNode;
  description?: ReactNode;
  /** Right-aligned controls: a tab switcher, a filter, a link out to the full view. */
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

/**
 * A labelled band of dashboard content.
 *
 * Promoted out of `app/dashboard/dashboard.module.css`, where it existed as a local
 * `.section`/`.sectionLabel` pair, so the ERP finance surfaces and the dashboard cannot drift
 * apart on the one piece of structure they most obviously share. The `action` slot is what the
 * reference design puts a segmented control into, alongside the section title rather than
 * floating inside the first card.
 */
export function PageSection({ title, description, action, children, className }: PageSectionProps) {
  return (
    <section className={clsx(styles.section, className)}>
      <header className={styles.header}>
        <div className={styles.headingText}>
          <h2 className={styles.title}>{title}</h2>
          {description && <p className={styles.description}>{description}</p>}
        </div>
        {action && <div className={styles.action}>{action}</div>}
      </header>
      {children}
    </section>
  );
}
