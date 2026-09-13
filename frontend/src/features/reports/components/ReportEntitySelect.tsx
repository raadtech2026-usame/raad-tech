import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { Input } from "../../../shared/components/Input/Input";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import type { ReportPickerOption } from "../api";
import styles from "./ReportEntitySelect.module.css";

export interface ReportEntitySelectProps {
  value: ReportPickerOption | null;
  onChange: (option: ReportPickerOption | null) => void;
  fetchOptions: (search: string) => Promise<ReportPickerOption[]>;
  queryKey: string;
  placeholder: string;
  emptyLabel: string;
  icon: ReactNode;
  disabled?: boolean;
}

const SEARCH_DEBOUNCE_MS = 250;

/**
 * A generic searchable id->label combobox — the Report Center's own Parent and Vehicle selectors
 * (directive Section 7/29: "NEVER ask the organization user to enter a raw Parent/Vehicle ID";
 * this is what replaces the pre-redesign card grid's raw text inputs for both). One component
 * parameterized by `fetchOptions` rather than two near-identical ones, since the interaction
 * (debounce, dropdown, clear) is identical for both — only what is searched differs.
 *
 * Deliberately lighter than `transport-ops/parents/ParentSearchSelect.tsx`: a report filter only
 * ever needs the picked id, so there is no second "resolve full detail" network step here.
 */
export function ReportEntitySelect({
  value,
  onChange,
  fetchOptions,
  queryKey,
  placeholder,
  emptyLabel,
  icon,
  disabled,
}: ReportEntitySelectProps) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(query), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [query]);

  const optionsQuery = useQuery({
    queryKey: [queryKey, "report-select", debouncedQuery],
    queryFn: () => fetchOptions(debouncedQuery),
    enabled: open && !value,
    staleTime: 15_000,
  });

  useEffect(() => {
    function handlePointerDown(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, []);

  function handleClear(): void {
    setQuery("");
    onChange(null);
  }

  if (value) {
    return (
      <div className={styles.selected}>
        <span className={styles.selectedIcon}>{icon}</span>
        <span className={styles.selectedLabel}>{value.label}</span>
        {!disabled && (
          <button type="button" className={styles.clearButton} onClick={handleClear} aria-label="Clear selection">
            <X size={14} />
          </button>
        )}
      </div>
    );
  }

  const options = optionsQuery.data ?? [];

  return (
    <div className={styles.container} ref={containerRef}>
      <Input
        icon={<Search size={14} />}
        placeholder={placeholder}
        value={query}
        disabled={disabled}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
      />
      {open && (
        <div className={styles.dropdown} role="listbox">
          {optionsQuery.isLoading && <Skeleton height={16} />}
          {!optionsQuery.isLoading && options.length === 0 && (
            <div className={styles.empty}>{query ? emptyLabel : "Type to search…"}</div>
          )}
          {options.map((option) => (
            <button
              key={option.id}
              type="button"
              role="option"
              aria-selected={false}
              className={styles.option}
              onClick={() => {
                setOpen(false);
                onChange(option);
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
