import { useQueries } from "@tanstack/react-query";
import { Contact, UserRound, Users, type LucideIcon } from "lucide-react";
import { Card } from "../../shared/components/Card/Card";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import type { OffsetListParams } from "../../shared/api/listParams";
import { listDrivers } from "../../features/transport-ops/drivers/api";
import { countStudents } from "../../features/transport-ops/students/api";
import { countParents } from "../../features/transport-ops/parents/api";
import styles from "./PeopleSection.module.css";

/** `page_size=1` against drivers' own already-existing, already-tested list endpoint, reading
 * only `.page.total` — no new backend endpoint needed. Students/parents use the narrower
 * `GET /students/count`/`GET /parents/count` routes instead: RAAD Platform roles hold no
 * `transport_ops.students.list`/`.parents.list` permission (migration `c4d9a2e6f813`), so reusing
 * the list endpoint would 403. Outside ADR-0020's own four-module scope (`platform_audit
 * .application.queries.PlatformStatsDTO`'s own docstring flags "Active Drivers" as a deliberate
 * scope cut), so this remains the correct, only source for all three counts. */
const COUNT_ONLY_PARAMS: OffsetListParams = { page: 1, pageSize: 1, sort: null, filters: {}, search: "" };

interface PeopleStatDef {
  key: string;
  label: string;
  icon: LucideIcon;
  fetcher: () => Promise<number>;
}

const PEOPLE_STATS: PeopleStatDef[] = [
  { key: "drivers", label: "Total drivers", icon: UserRound, fetcher: async () => (await listDrivers(COUNT_ONLY_PARAMS)).page.total },
  { key: "students", label: "Total students", icon: Users, fetcher: countStudents },
  { key: "parents", label: "Total parents", icon: Contact, fetcher: countParents },
];

const numberFormatter = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

export function PeopleSection() {
  const results = useQueries({
    queries: PEOPLE_STATS.map((stat) => ({
      queryKey: ["platform-stats", stat.key],
      queryFn: stat.fetcher,
      staleTime: 60_000,
    })),
  });

  return (
    <div className={styles.grid}>
      {PEOPLE_STATS.map((stat, index) => {
        const result = results[index];
        const Icon = stat.icon;
        return (
          <Card key={stat.key} padded className={styles.tile}>
            <div className={styles.head}>
              <span className={styles.icon}>
                <Icon size={18} />
              </span>
              <span className={styles.label}>{stat.label}</span>
            </div>
            {result.isLoading ? (
              <Skeleton width={64} height={30} />
            ) : (
              <span className={styles.value}>{result.isError ? "—" : numberFormatter.format(result.data ?? 0)}</span>
            )}
          </Card>
        );
      })}
    </div>
  );
}
