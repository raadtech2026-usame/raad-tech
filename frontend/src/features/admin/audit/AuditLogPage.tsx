import { useState, useMemo, useEffect } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Search, ScrollText } from "lucide-react";
import { usePaginatedQuery } from "../../../shared/hooks/usePaginatedQuery";
import { DataTable } from "../../../shared/components/Table/DataTable";
import { Pagination } from "../../../shared/components/Table/Pagination";
import { Badge, type BadgeVariant } from "../../../shared/components/Badge/Badge";
import { Input } from "../../../shared/components/Input/Input";
import { DetailDrawer } from "../../../shared/components/Drawer/DetailDrawer";
import { listAuditEntries, type AuditEntry } from "../../platform-analytics/api";
import styles from "./AuditLogPage.module.css";

const SEARCH_DEBOUNCE_MS = 250;

function formatAuditDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-GB", {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

function actionTone(action: string): BadgeVariant {
  if (action.includes("deleted") || action.includes("suspended") || action.includes("deactivated")) {
    return "danger";
  }
  if (action.includes("created") || action.includes("registered") || action.includes("reactivated")) {
    return "success";
  }
  if (action.includes("updated") || action.includes("renamed") || action.includes("set")) {
    return "info";
  }
  return "neutral";
}

export function AuditLogPage() {
  const [selectedEntry, setSelectedEntry] = useState<AuditEntry | null>(null);
  const [searchInput, setSearchInput] = useState("");

  const {
    rows,
    total,
    page,
    pageSize,
    isLoading,
    setPage,
    setSearch,
  } = usePaginatedQuery<AuditEntry>({
    queryKey: ["admin", "audit-log"],
    fetcher: listAuditEntries,
    initialSort: { field: "created_at", direction: "desc" },
  });

  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [searchInput, setSearch]);

  const columns = useMemo<ColumnDef<AuditEntry>[]>(() => [
    {
      accessorKey: "createdAt",
      header: "Timestamp",
      cell: ({ row }) => (
        <span className={styles.mono}>
          {formatAuditDate(row.original.createdAt)}
        </span>
      ),
    },
    {
      accessorKey: "action",
      header: "Action",
      cell: ({ row }) => (
        <Badge variant={actionTone(row.original.action)}>
          {row.original.action}
        </Badge>
      ),
    },
    {
      accessorKey: "actorUserId",
      header: "Actor",
      cell: ({ row }) => (
        <span className={styles.mono}>
          {row.original.actorUserId ?? "system"}
        </span>
      ),
    },
    {
      accessorKey: "entityType",
      header: "Target Entity",
      cell: ({ row }) => (
        <span>
          {row.original.entityType ? (
            <strong>{row.original.entityType}</strong>
          ) : (
            "—"
          )}
        </span>
      ),
    },
    {
      accessorKey: "entityId",
      header: "Entity ID",
      cell: ({ row }) => (
        <span className={styles.mono}>
          {row.original.entityId ?? "—"}
        </span>
      ),
    },
    {
      accessorKey: "organizationId",
      header: "Organization ID",
      cell: ({ row }) => (
        <span className={styles.mono}>
          {row.original.organizationId ?? "platform"}
        </span>
      ),
    },
  ], []);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>System Audit Log</h1>
        <p className={styles.description}>
          Append-only, immutable transaction ledger recording all security, operational, and financial events (ADR-0007).
        </p>
      </header>

      <div className={styles.controls}>
        <div className={styles.searchWrap}>
          <Search size={16} className={styles.searchIcon} aria-hidden="true" />
          <Input
            placeholder="Search action or entity..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className={styles.searchInput}
          />
        </div>
      </div>

      <DataTable
        columns={columns}
        data={rows}
        getRowId={(row) => row.id}
        isLoading={isLoading}
        onRowClick={(entry) => setSelectedEntry(entry)}
      />

      <Pagination
        page={page}
        pageSize={pageSize}
        total={total}
        onPageChange={setPage}
      />

      {selectedEntry && (
        <DetailDrawer
          open={Boolean(selectedEntry)}
          onClose={() => setSelectedEntry(null)}
          icon={<ScrollText size={20} />}
          iconTint="rgba(20, 184, 166, 0.15)"
          iconColor="var(--color-primary-600)"
          title="Audit Entry Details"
          status={
            <Badge variant={actionTone(selectedEntry.action)}>
              {selectedEntry.action}
            </Badge>
          }
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
            <div>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--color-text-muted)" }}>Timestamp</span>
              <p style={{ margin: 0, fontWeight: "var(--font-weight-medium)" }}>{formatAuditDate(selectedEntry.createdAt)}</p>
            </div>
            <div>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--color-text-muted)" }}>Actor User ID</span>
              <p className={styles.mono} style={{ margin: 0 }}>{selectedEntry.actorUserId ?? "system"}</p>
            </div>
            <div>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--color-text-muted)" }}>Target Entity</span>
              <p style={{ margin: 0 }}>{selectedEntry.entityType ?? "—"} ({selectedEntry.entityId ?? "—"})</p>
            </div>
            <div>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--color-text-muted)" }}>Organization Scope</span>
              <p className={styles.mono} style={{ margin: 0 }}>{selectedEntry.organizationId ?? "platform"}</p>
            </div>
            <div>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--color-text-muted)" }}>Metadata & Payload</span>
              {selectedEntry.metadata ? (
                <pre className={styles.metadataPre}>
                  {JSON.stringify(selectedEntry.metadata, null, 2)}
                </pre>
              ) : (
                <p style={{ margin: 0, color: "var(--color-text-muted)" }}>No additional metadata recorded.</p>
              )}
            </div>
          </div>
        </DetailDrawer>
      )}
    </div>
  );
}
