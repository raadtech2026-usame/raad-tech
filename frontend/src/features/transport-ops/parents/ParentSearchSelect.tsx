import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, UserRound, X } from "lucide-react";
import { Input } from "../../../shared/components/Input/Input";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { getParent, listParentsForPicker, listStudentsForParent, type ParentOption } from "./api";
import styles from "./ParentSearchSelect.module.css";

export interface SelectedParent {
  id: string;
  fullName: string;
  phone: string | null;
  childrenCount: number;
}

export interface ParentSearchSelectProps {
  value: SelectedParent | null;
  onChange: (parent: SelectedParent | null) => void;
  disabled?: boolean;
  "aria-label"?: string;
}

const SEARCH_DEBOUNCE_MS = 250;

/**
 * "Search parent by name or phone" — the picker the task's own UX description names verbatim:
 * type, see matching parents, select one, and see their existing children count before
 * continuing. Used by `CreateStudentForm.tsx` (inline, during enrollment) and
 * `LinkGuardianForm.tsx` (the post-enrollment "Add guardian" action), replacing both forms'
 * previous plain `<Select>` of up to 100 loaded parents with a real search.
 *
 * **Two network steps, deliberately.** The list step (`listParentsForPicker`, debounced,
 * `GET /parents?q=...`) only ever returns `id`/`fullName`/`status` — `ParentSummaryResponse`
 * carries no `phone` and no children count (`api.ts`'s own docstring). Fetching those for every
 * row in a live-typing dropdown would multiply a single keystroke into `2 × N` requests; fetching
 * them once, only for the row the admin actually picks (`getParent` + `listStudentsForParent`,
 * in parallel), keeps the common case (typing, scanning names, picking one) cheap and the
 * "Existing children: N" line accurate the moment it appears.
 *
 * **No inline "register a new parent" escape hatch.** A search with zero matches says so and
 * points at the Parents page — `CreateParentForm`'s own duplicate-phone check and one-time
 * temporary-password hand-off are involved enough to not duplicate inside this picker.
 */
export function ParentSearchSelect({ value, onChange, disabled, ...rest }: ParentSearchSelectProps) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [resolving, setResolving] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(query), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [query]);

  const optionsQuery = useQuery({
    queryKey: ["parents", "search-select", debouncedQuery],
    queryFn: () => listParentsForPicker(debouncedQuery),
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

  async function handleSelect(option: ParentOption): Promise<void> {
    setOpen(false);
    setResolving(true);
    try {
      const [detail, children] = await Promise.all([
        getParent(option.id),
        listStudentsForParent(option.id),
      ]);
      onChange({
        id: option.id,
        fullName: detail.fullName,
        phone: detail.phone,
        childrenCount: children.length,
      });
    } finally {
      setResolving(false);
    }
  }

  function handleClear(): void {
    setQuery("");
    onChange(null);
  }

  if (value) {
    return (
      <div className={styles.selected}>
        <UserRound size={16} className={styles.selectedIcon} />
        <div className={styles.selectedBody}>
          <div className={styles.selectedName}>{value.fullName}</div>
          <div className={styles.selectedMeta}>
            {value.phone ?? "No phone on file"} · {value.childrenCount} existing{" "}
            {value.childrenCount === 1 ? "child" : "children"}
          </div>
        </div>
        {!disabled && (
          <button type="button" className={styles.clearButton} onClick={handleClear} aria-label="Change parent">
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
        placeholder="Search by name or phone…"
        value={query}
        disabled={disabled || resolving}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        aria-label={rest["aria-label"] ?? "Search parent by name or phone"}
      />
      {open && (
        <div className={styles.dropdown} role="listbox">
          {(optionsQuery.isLoading || resolving) && <Skeleton height={16} />}
          {!optionsQuery.isLoading && !resolving && options.length === 0 && (
            <div className={styles.empty}>
              {query
                ? "No matching parent. Register one from the Parents page first."
                : "Type a name or phone number…"}
            </div>
          )}
          {!resolving &&
            options.map((option) => (
              <button
                key={option.id}
                type="button"
                role="option"
                aria-selected={false}
                className={styles.option}
                onClick={() => void handleSelect(option)}
              >
                {option.fullName}
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
