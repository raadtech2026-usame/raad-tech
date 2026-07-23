import clsx from "clsx";
import styles from "./FilterChips.module.css";

export type FilterTone = "neutral" | "success" | "warning" | "danger" | "info" | "purple";

export interface FilterChipOption {
  id: string;
  label: string;
  tone?: FilterTone;
}

export interface FilterChipsProps {
  options: FilterChipOption[];
  activeId: string;
  onSelect: (id: string) => void;
}

/** The row of quick-status filter pills above every table in the approved design ("All 24",
 * "On route 18", "Delayed 3"…) — colors come from the same semantic tone system `Badge` uses
 * instead of each feature hand-picking its own hex pairs. */
export function FilterChips({ options, activeId, onSelect }: FilterChipsProps) {
  return (
    <div className={styles.row} role="tablist">
      {options.map((option) => {
        const tone = option.tone ?? "neutral";
        const isActive = option.id === activeId;
        return (
          <button
            key={option.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={clsx(styles.chip, styles[tone], isActive && styles.active)}
            onClick={() => onSelect(option.id)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
