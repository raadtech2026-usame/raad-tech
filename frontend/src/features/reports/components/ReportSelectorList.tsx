import clsx from "clsx";
import { Search } from "lucide-react";
import { Input } from "../../../shared/components/Input/Input";
import { Tabs } from "../../../shared/components/Tabs/Tabs";
import { EmptyState } from "../../../shared/components/EmptyState/EmptyState";
import type { ReportCategory, ReportDefinition } from "../api";
import styles from "./ReportSelectorList.module.css";

/** The Organization Report Center's own two categories — the historical default so every
 * existing call site (which predates the `categories` prop) keeps its exact current behavior
 * unchanged. The Platform Report Center passes its own `categories` explicitly instead. */
const ORGANIZATION_CATEGORY_TABS: { id: ReportCategory; label: string }[] = [
  { id: "financial", label: "Financial" },
  { id: "transportation", label: "Transportation" },
];

export interface ReportSelectorListProps {
  definitions: ReportDefinition[];
  search: string;
  onSearchChange: (value: string) => void;
  activeCategory: ReportCategory;
  onCategoryChange: (category: ReportCategory) => void;
  selectedKey: string | null;
  onSelect: (definition: ReportDefinition) => void;
  /** Platform Report Center (Organization Management phase) — generalizes this component's
   * previously-hardcoded two-tab category bar so the same selector serves both scopes with
   * different category sets, without duplicating the tile-grid/search UI. Defaults to the
   * Organization Report Center's own two categories when omitted. */
  categories?: { id: ReportCategory; label: string }[];
}

/**
 * The Report Center's navigation/filter bar (search + category tabs) plus its "Available
 * reports" tile grid — a professional report-navigation toolbar sitting above a compact, wrapping
 * grid of report tiles, replacing the pre-redesign narrow vertical sidebar list (which forced a
 * tall scrolling column next to a large, mostly-empty detail panel).
 *
 * Search deliberately overrides the active tab rather than narrowing within it: typing "vehicle"
 * while on the Financial tab should still surface a Transportation report by name rather than
 * requiring the operator to first guess which tab it lives under.
 */
export function ReportSelectorList({
  definitions,
  search,
  onSearchChange,
  activeCategory,
  onCategoryChange,
  selectedKey,
  onSelect,
  categories = ORGANIZATION_CATEGORY_TABS,
}: ReportSelectorListProps) {
  const query = search.trim().toLowerCase();
  const visible = query
    ? definitions.filter(
        (d) => d.title.toLowerCase().includes(query) || d.description.toLowerCase().includes(query),
      )
    : definitions.filter((d) => d.category === activeCategory);

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <Input
          className={styles.search}
          icon={<Search size={14} />}
          placeholder="Search reports…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          aria-label="Search the report catalogue"
        />

        {!query && (
          <Tabs options={categories} activeId={activeCategory} onSelect={(id) => onCategoryChange(id as ReportCategory)} />
        )}
      </div>

      <div className={styles.sectionLabel}>Available reports</div>

      <div className={styles.grid} role="listbox" aria-label="Available reports">
        {visible.length === 0 ? (
          <EmptyState
            icon={<Search size={18} />}
            title={query ? "No reports match your search" : "No reports in this category"}
            description={query ? `Nothing matches "${search}". Try a different term.` : undefined}
          />
        ) : (
          visible.map((definition) => (
            <button
              key={definition.key}
              type="button"
              role="option"
              aria-selected={definition.key === selectedKey}
              className={clsx(styles.tile, definition.key === selectedKey && styles.tileActive)}
              onClick={() => onSelect(definition)}
            >
              <span className={styles.tileTitle}>{definition.title}</span>
              <span className={styles.tileDescription}>{definition.description}</span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
