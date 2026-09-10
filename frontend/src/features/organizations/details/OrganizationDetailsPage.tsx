import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Info } from "lucide-react";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Card, CardBody, CardHeader } from "../../../shared/components/Card/Card";
import { EmptyState } from "../../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { Tabs } from "../../../shared/components/Tabs/Tabs";
import { ApiError } from "../../../shared/api/types";
import { usePageHeader } from "../../../app/layout/PageHeaderContext";
import { getOrganization, listRegions } from "../api";
import { orgTypeLabel, statusLabel, statusTone } from "../labels";
import {
  ORGANIZATION_DETAIL_TABS,
  type OrganizationDetailTabId,
} from "./tabs";
import { OrganizationTabPanel } from "./OrganizationTabPanel";
import styles from "./OrganizationDetailsPage.module.css";

/**
 * Founder → one organization, everything RAAD may see about it.
 *
 * **A composition, not a new read model.** Every tab calls the list client that already owns its
 * resource with one extra `organization_id` filter — see `./api.ts`. No tab has its own endpoint,
 * so nothing here can drift from the page that owns the resource.
 *
 * **Two tabs show a count and no roster, on purpose.** RAAD staff hold `.count` but not `.list`
 * for students and parents: the platform manages organizations, not individual children and
 * families. The tabs say so rather than rendering an empty table that looks like a bug.
 *
 * **Tab data loads only when its tab is opened.** Fifteen tabs firing on mount would be fifteen
 * requests for a page where a Founder usually wants one — the same `enabled` discipline
 * `OrgFinancePage`'s ledger already applies.
 */
export function OrganizationDetailsPage() {
  const { organizationId = "" } = useParams<{ organizationId: string }>();
  const [tab, setTab] = useState<OrganizationDetailTabId>("overview");

  const organization = useQuery({
    queryKey: ["organizations", "detail", organizationId],
    queryFn: () => getOrganization(organizationId),
    enabled: Boolean(organizationId),
    staleTime: 60_000,
  });

  // The organization carries `regionId` only; the name comes from the region list, the same
  // "resolve names client-side from a small cached read" shape `OrganizationsPage` already uses.
  const regions = useQuery({
    queryKey: ["regions", "lookup"],
    queryFn: () =>
      listRegions({
        page: 1,
        pageSize: 100,
        sort: { field: "name", direction: "asc" },
        filters: {},
        search: "",
      }),
    staleTime: 5 * 60_000,
  });

  const regionName = useMemo(() => {
    const id = organization.data?.regionId;
    if (!id) return null;
    return regions.data?.data.find((region) => region.id === id)?.name ?? id;
  }, [organization.data, regions.data]);

  usePageHeader(
    organization.data?.name ?? "Organization",
    organization.data
      ? `${orgTypeLabel(organization.data.orgType)}${regionName ? ` · ${regionName}` : ""}`
      : "Loading…",
  );

  if (organization.isPending) {
    return (
      <div className={styles.page}>
        <Skeleton height={28} />
        <Skeleton height={180} />
      </div>
    );
  }

  if (organization.isError) {
    return (
      <div className={styles.page}>
        <EmptyState
          icon={<Info size={22} />}
          title="Could not load this organization"
          description={
            organization.error instanceof ApiError
              ? organization.error.message
              : "Something went wrong. Please try again."
          }
        />
        <Link to="/platform/organizations" className={styles.backLink}>
          <ArrowLeft size={14} /> Back to organizations
        </Link>
      </div>
    );
  }

  return (
    <div className={clsx(styles.page, "raad-view-transition")}>
      <div className={styles.breadcrumb}>
        <Link to="/platform/organizations" className={styles.backLink}>
          <ArrowLeft size={14} /> All organizations
        </Link>
        <Badge variant={statusTone(organization.data.status)} dot>
          {statusLabel(organization.data.status)}
        </Badge>
      </div>

      <div className={styles.tabBar}>
        <Tabs
          options={ORGANIZATION_DETAIL_TABS.map((t) => ({ id: t.id, label: t.label }))}
          activeId={tab}
          onSelect={(id) => setTab(id as OrganizationDetailTabId)}
        />
      </div>

      <Card>
        <CardHeader
          icon={ORGANIZATION_DETAIL_TABS.find((t) => t.id === tab)?.icon}
          title={ORGANIZATION_DETAIL_TABS.find((t) => t.id === tab)?.label ?? ""}
          subtitle={ORGANIZATION_DETAIL_TABS.find((t) => t.id === tab)?.description}
        />
        <CardBody>
          <OrganizationTabPanel
            tab={tab}
            organizationId={organizationId}
            organization={organization.data}
            regionName={regionName}
          />
        </CardBody>
      </Card>
    </div>
  );
}
