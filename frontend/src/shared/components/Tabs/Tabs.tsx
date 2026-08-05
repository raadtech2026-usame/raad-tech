import clsx from "clsx";
import styles from "./Tabs.module.css";

export interface TabOption {
  id: string;
  label: string;
}

export interface TabsProps {
  options: TabOption[];
  activeId: string;
  onSelect: (id: string) => void;
}

/** Switches between entire content panels (e.g. Billing's Plans/Subscriptions/Invoices) —
 * distinct from `FilterChips`, which narrows *one* list's own rows. Underline style rather than
 * `FilterChips`' pill style so the two read as different affordances at a glance. */
export function Tabs({ options, activeId, onSelect }: TabsProps) {
  return (
    <div className={styles.row} role="tablist">
      {options.map((option) => {
        const isActive = option.id === activeId;
        return (
          <button
            key={option.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={clsx(styles.tab, isActive && styles.active)}
            onClick={() => onSelect(option.id)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
