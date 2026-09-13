import { useState } from "react";
import { Select } from "../../../shared/components/Select/Select";
import { Input } from "../../../shared/components/Input/Input";
import { FormField } from "../../../shared/components/FormField/FormField";
import styles from "./DateRangePresetFilter.module.css";

export interface DateRange {
  start: string;
  end: string;
}

export interface DateRangePresetFilterProps {
  start: string;
  end: string;
  onChange: (range: DateRange) => void;
}

/** Formats a `Date` as `YYYY-MM-DD` using its own *local* calendar date — never
 * `.toISOString()`, which normalises to UTC first and silently shifts the day across midnight
 * for any timezone behind UTC. */
function isoDate(d: Date): string {
  const year = String(d.getFullYear()).padStart(4, "0");
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function mondayOf(d: Date): Date {
  const dayOfWeek = d.getDay(); // 0 = Sunday
  const offsetFromMonday = (dayOfWeek + 6) % 7;
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() - offsetFromMonday);
}

interface Preset {
  id: string;
  label: string;
  range: () => DateRange | null;
}

/** The Report Center's one reusable date-range filter (directive Section 1: "One reusable
 * date-range filter... Today/This Week/This Month/Last Month/This Quarter/This Year/Last Year/
 * Custom Range"). "This X" presets run from the start of the period to *today*, never to the
 * period's own future end — a report has no data past today regardless, and clamping to today
 * keeps the picked range legible rather than silently including unreached dates. "Last X" presets
 * keep the full prior period, since every day in it has already happened. */
const PRESETS: Preset[] = [
  { id: "custom", label: "Custom range", range: () => null },
  { id: "today", label: "Today", range: () => ({ start: isoDate(new Date()), end: isoDate(new Date()) }) },
  {
    id: "this_week",
    label: "This week",
    range: () => {
      const now = new Date();
      return { start: isoDate(mondayOf(now)), end: isoDate(now) };
    },
  },
  {
    id: "this_month",
    label: "This month",
    range: () => {
      const now = new Date();
      return { start: isoDate(new Date(now.getFullYear(), now.getMonth(), 1)), end: isoDate(now) };
    },
  },
  {
    id: "last_month",
    label: "Last month",
    range: () => {
      const now = new Date();
      const start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      const end = new Date(now.getFullYear(), now.getMonth(), 0);
      return { start: isoDate(start), end: isoDate(end) };
    },
  },
  {
    id: "this_quarter",
    label: "This quarter",
    range: () => {
      const now = new Date();
      const quarterStartMonth = Math.floor(now.getMonth() / 3) * 3;
      return { start: isoDate(new Date(now.getFullYear(), quarterStartMonth, 1)), end: isoDate(now) };
    },
  },
  {
    id: "this_year",
    label: "This year",
    range: () => {
      const now = new Date();
      return { start: isoDate(new Date(now.getFullYear(), 0, 1)), end: isoDate(now) };
    },
  },
  {
    id: "last_year",
    label: "Last year",
    range: () => {
      const now = new Date();
      return {
        start: isoDate(new Date(now.getFullYear() - 1, 0, 1)),
        end: isoDate(new Date(now.getFullYear() - 1, 11, 31)),
      };
    },
  },
];

/** Preset dropdown + editable From/To dates that stays in sync in both directions: picking a
 * preset fills in From/To, and hand-editing either date afterwards is preserved as-is (this
 * component does not force "Custom" back onto the caller — `ReportsPage` does that itself by
 * tracking which preset is active alongside the two dates). */
export function DateRangePresetFilter({ start, end, onChange }: DateRangePresetFilterProps) {
  const [presetId, setPresetId] = useState("custom");

  return (
    <div className={styles.row}>
      <FormField label="Date range">
        <Select
          value={presetId}
          onChange={(e) => {
            const id = e.target.value;
            setPresetId(id);
            const range = PRESETS.find((p) => p.id === id)?.range();
            if (range) onChange(range);
          }}
        >
          {PRESETS.map((preset) => (
            <option key={preset.id} value={preset.id}>
              {preset.label}
            </option>
          ))}
        </Select>
      </FormField>
      <FormField label="From">
        <Input
          type="date"
          value={start}
          onChange={(e) => {
            setPresetId("custom");
            onChange({ start: e.target.value, end });
          }}
        />
      </FormField>
      <FormField label="To">
        <Input
          type="date"
          value={end}
          onChange={(e) => {
            setPresetId("custom");
            onChange({ start, end: e.target.value });
          }}
        />
      </FormField>
    </div>
  );
}
