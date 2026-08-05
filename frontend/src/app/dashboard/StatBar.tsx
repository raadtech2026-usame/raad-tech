import clsx from "clsx";
import type { BadgeVariant } from "../../shared/components/Badge/Badge";
import styles from "./StatBar.module.css";

export interface StatBarItem {
  key: string;
  label: string;
  value: number;
  tone: BadgeVariant;
}

interface StatBarProps {
  items: StatBarItem[];
  /** Shown instead of an all-zero bar/legend — every widget using this component reaches zero
   * segments the moment its source has no rows yet (a fresh deployment, an empty organization),
   * which is a real, expected state here, not an error. */
  emptyLabel: string;
}

/**
 * A horizontal proportional breakdown bar + legend — this dashboard's only "chart" primitive,
 * hand-rolled rather than a charting dependency (no new package is approved for this session,
 * `.claude/rules/workflow.md` #1/#2, and a handful of 2-5 category breakdowns don't need one).
 * Every consumer passes real, already-fetched counts (vehicle status, device connectivity,
 * subscription status, ...) — this component never invents a value, and reduces to `emptyLabel`
 * the moment every count is genuinely zero.
 */
export function StatBar({ items, emptyLabel }: StatBarProps) {
  const total = items.reduce((sum, item) => sum + item.value, 0);
  const visible = items.filter((item) => item.value > 0);

  if (total === 0) {
    return <p className={styles.empty}>{emptyLabel}</p>;
  }

  return (
    <div className={styles.wrap}>
      <div
        className={styles.track}
        role="img"
        aria-label={items.map((item) => `${item.label}: ${item.value}`).join(", ")}
      >
        {visible.map((item) => (
          <span
            key={item.key}
            className={clsx(styles.segment, styles[item.tone])}
            style={{ flexGrow: item.value }}
            title={`${item.label}: ${item.value}`}
          />
        ))}
      </div>
      <ul className={styles.legend}>
        {items.map((item) => (
          <li key={item.key} className={styles.legendItem}>
            <span className={clsx(styles.swatch, styles[item.tone])} aria-hidden="true" />
            <span className={styles.legendLabel}>{item.label}</span>
            <span className={styles.legendValue}>{item.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
