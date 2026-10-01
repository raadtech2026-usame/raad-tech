import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Select } from "../../../shared/components/Select/Select";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import {
  addDefaultDocumentTypes,
  getDocumentTypeImpact,
  addDefaultStaffRoles,
  createDocumentType,
  createStaffRole,
  listDocumentTypes,
  listStaffRoles,
  updateDocumentType,
  updateStaffRole,
  type DocumentEnforcement,
  type DocumentRequirement,
  type DocumentType,
  type StaffRole,
} from "./api";
import { REQUIREMENTS, enforcementLabel, requirementLabel } from "./labels";
import styles from "./Staff.module.css";

/** "30, 7" → [30, 7]; `null` when any entry is not a whole number from 1 to 365. */
export function parseLeadDays(raw: string): number[] | null {
  const parts = raw
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length === 0 || parts.length > 5) return null;
  const values = parts.map(Number);
  if (values.some((value) => !Number.isInteger(value) || value < 1 || value > 365)) return null;
  return [...new Set(values)].sort((a, b) => b - a);
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Please try again.";
}

function JobTitlesCard({ canManage }: { canManage: boolean }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const rolesQuery = useQuery({ queryKey: ["transport-staff", "roles"], queryFn: () => listStaffRoles() });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["transport-staff"] });

  const defaults = useMutation({
    mutationFn: addDefaultStaffRoles,
    onSuccess: () => {
      invalidate();
      toast.success("Default job titles added", "Driver, Attendant, Assistant, Conductor, Supervisor");
    },
    onError: (error) => toast.error("Could not add defaults", errorMessage(error)),
  });
  const create = useMutation({
    mutationFn: (value: string) =>
      createStaffRole({ name: value, sortOrder: ((rolesQuery.data ?? []).length + 1) * 10 }),
    onSuccess: () => {
      invalidate();
      setName("");
    },
    onError: (error) => toast.error("Could not add the job title", errorMessage(error)),
  });
  const update = useMutation({
    mutationFn: (input: { role: StaffRole; name?: string; isArchived?: boolean }) =>
      updateStaffRole(input.role.id, {
        name: input.name ?? input.role.name,
        sortOrder: input.role.sortOrder,
        isArchived: input.isArchived ?? input.role.isArchived,
      }),
    onSuccess: () => {
      invalidate();
      setRenaming(null);
    },
    onError: (error) => toast.error("Could not update the job title", errorMessage(error)),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim()) create.mutate(name.trim());
  }

  const roles = rolesQuery.data ?? [];
  return (
    <section className={styles.section} aria-label="Job titles">
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Job titles</span>
        {canManage && (
          <Button size="sm" variant="secondary" loading={defaults.isPending} onClick={() => defaults.mutate()}>
            Add default titles
          </Button>
        )}
      </div>
      <p className={styles.itemMeta}>
        A title is a label. Only “Give driver access” lets someone drive a trip, whatever their title.
      </p>
      {rolesQuery.isLoading ? (
        <Skeleton height={48} />
      ) : roles.length === 0 ? (
        <p className={styles.empty}>No job titles yet.</p>
      ) : (
        <ul className={styles.list}>
          {roles.map((role) => (
            <li key={role.id} className={styles.item}>
              {renaming?.id === role.id ? (
                <form
                  className={styles.inlineForm}
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (renaming.name.trim()) update.mutate({ role, name: renaming.name.trim() });
                  }}
                >
                  <Input
                    aria-label={`New name for ${role.name}`}
                    value={renaming.name}
                    onChange={(event) => setRenaming({ id: role.id, name: event.target.value })}
                    autoFocus
                  />
                  <Button size="sm" type="submit" loading={update.isPending}>
                    Save
                  </Button>
                  <Button size="sm" variant="ghost" type="button" onClick={() => setRenaming(null)}>
                    Cancel
                  </Button>
                </form>
              ) : (
                <>
                  <div className={styles.itemMain}>
                    <span className={styles.itemTitle}>{role.name}</span>
                  </div>
                  <div className={styles.itemActions}>
                    {role.isArchived && <Badge variant="neutral">Archived</Badge>}
                    {canManage && (
                      <>
                        <Button size="sm" variant="ghost" onClick={() => setRenaming({ id: role.id, name: role.name })}>
                          Rename
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => update.mutate({ role, isArchived: !role.isArchived })}
                        >
                          {role.isArchived ? "Restore" : "Archive"}
                        </Button>
                      </>
                    )}
                  </div>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <form className={styles.inlineForm} onSubmit={submit}>
          <FormField label="New job title">
            <Input aria-label="New job title" value={name} maxLength={80} onChange={(event) => setName(event.target.value)} />
          </FormField>
          <Button type="submit" size="sm" loading={create.isPending} disabled={!name.trim()}>
            Add
          </Button>
        </form>
      )}
    </section>
  );
}

/**
 * ADR-0058 §1/§3: who must hold a document of this type, and whether a lapse only warns or also
 * blocks new planning. Shows how many people the choice affects before it is saved, because
 * marking a type required before the documents are recorded flags everyone at once.
 */
function RequirementEditor({
  type,
  saving,
  onSave,
  onCancel,
}: {
  type: DocumentType;
  saving: boolean;
  onSave: (requiredFor: DocumentRequirement, enforcement: DocumentEnforcement) => void;
  onCancel: () => void;
}) {
  const [requiredFor, setRequiredFor] = useState<DocumentRequirement>(type.requiredFor);
  const [enforcement, setEnforcement] = useState<DocumentEnforcement>(type.enforcement);
  const impact = useQuery({
    queryKey: ["transport-staff", "document-type-impact", type.id, requiredFor],
    queryFn: () => getDocumentTypeImpact(type.id, requiredFor),
    enabled: requiredFor !== "none",
  });
  return (
    <form
      className={styles.inlineForm}
      onSubmit={(event) => {
        event.preventDefault();
        onSave(requiredFor, enforcement);
      }}
    >
      <FormField label={`Who needs ${type.name}`}>
        <Select
          aria-label={`Who needs ${type.name}`}
          value={requiredFor}
          onChange={(event) => setRequiredFor(event.target.value as DocumentRequirement)}
        >
          {REQUIREMENTS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </Select>
      </FormField>
      {requiredFor !== "none" && (
        <FormField label="If missing or expired">
          <Select
            aria-label={`If ${type.name} is missing or expired`}
            value={enforcement}
            onChange={(event) => setEnforcement(event.target.value as DocumentEnforcement)}
          >
            <option value="warn">Warn only</option>
            <option value="block">Block new planning</option>
          </Select>
        </FormField>
      )}
      {requiredFor !== "none" && (
        <p className={impact.data && impact.data.notCompliant > 0 ? styles.warning : styles.itemMeta} role="status">
          {impact.isLoading || !impact.data
            ? "Checking who this affects…"
            : `Applies to ${impact.data.appliesTo} staff; ${impact.data.notCompliant} of them will be not compliant today.`}
        </p>
      )}
      <Button size="sm" type="submit" loading={saving}>
        Save
      </Button>
      <Button size="sm" variant="ghost" type="button" onClick={onCancel}>
        Cancel
      </Button>
    </form>
  );
}

function DocumentTypesCard({ canManage }: { canManage: boolean }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [leadDays, setLeadDays] = useState("30, 7");
  const [editing, setEditing] = useState<{ id: string; leadDays: string } | null>(null);
  const [requiring, setRequiring] = useState<string | null>(null);
  const typesQuery = useQuery({ queryKey: ["transport-staff", "document-types"], queryFn: () => listDocumentTypes() });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["transport-staff"] });

  const defaults = useMutation({
    mutationFn: addDefaultDocumentTypes,
    onSuccess: () => {
      invalidate();
      toast.success("Default document types added", "Each alerts 30 and 7 days before expiry.");
    },
    onError: (error) => toast.error("Could not add defaults", errorMessage(error)),
  });
  const create = useMutation({
    mutationFn: (input: { name: string; alertLeadDays: number[] }) => createDocumentType(input),
    onSuccess: () => {
      invalidate();
      setName("");
      setLeadDays("30, 7");
    },
    onError: (error) => toast.error("Could not add the document type", errorMessage(error)),
  });
  const update = useMutation({
    mutationFn: (input: {
      type: DocumentType;
      alertLeadDays?: number[];
      isArchived?: boolean;
      requiredFor?: DocumentRequirement;
      enforcement?: DocumentEnforcement;
    }) =>
      updateDocumentType(input.type.id, {
        name: input.type.name,
        alertLeadDays: input.alertLeadDays ?? input.type.alertLeadDays,
        isArchived: input.isArchived ?? input.type.isArchived,
        requiredFor: input.requiredFor,
        enforcement: input.enforcement,
      }),
    onSuccess: () => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: ["daily-operations"] });
      setEditing(null);
      setRequiring(null);
    },
    onError: (error) => toast.error("Could not update the document type", errorMessage(error)),
  });

  const parsedNew = parseLeadDays(leadDays);
  const types = typesQuery.data ?? [];

  return (
    <section className={styles.section} aria-label="Document types">
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Document types</span>
        {canManage && (
          <Button size="sm" variant="secondary" loading={defaults.isPending} onClick={() => defaults.mutate()}>
            Add default types
          </Button>
        )}
      </div>
      <p className={styles.itemMeta}>
        Org Admins get an in-app alert this many days before a document expires, and once more when it does. A
        required type also flags anyone who lacks a valid one, on their profile and on the daily board.
      </p>
      {typesQuery.isLoading ? (
        <Skeleton height={48} />
      ) : types.length === 0 ? (
        <p className={styles.empty}>No document types yet.</p>
      ) : (
        <ul className={styles.list}>
          {types.map((type) => {
            const parsedEdit = editing?.id === type.id ? parseLeadDays(editing.leadDays) : null;
            return (
              <li key={type.id} className={styles.item}>
                {requiring === type.id ? (
                  <RequirementEditor
                    type={type}
                    saving={update.isPending}
                    onSave={(requiredFor, enforcement) => update.mutate({ type, requiredFor, enforcement })}
                    onCancel={() => setRequiring(null)}
                  />
                ) : editing?.id === type.id ? (
                  <form
                    className={styles.inlineForm}
                    onSubmit={(event) => {
                      event.preventDefault();
                      if (parsedEdit) update.mutate({ type, alertLeadDays: parsedEdit });
                    }}
                  >
                    <FormField label={`Alert days for ${type.name}`} error={parsedEdit ? undefined : "1–5 numbers from 1 to 365"}>
                      <Input
                        aria-label={`Alert days for ${type.name}`}
                        value={editing.leadDays}
                        onChange={(event) => setEditing({ id: type.id, leadDays: event.target.value })}
                      />
                    </FormField>
                    <Button size="sm" type="submit" loading={update.isPending} disabled={!parsedEdit}>
                      Save
                    </Button>
                    <Button size="sm" variant="ghost" type="button" onClick={() => setEditing(null)}>
                      Cancel
                    </Button>
                  </form>
                ) : (
                  <>
                    <div className={styles.itemMain}>
                      <span className={styles.itemTitle}>{type.name}</span>
                      <span className={styles.itemMeta}>Alerts {type.alertLeadDays.join(", ")} days before expiry</span>
                      {type.requiredFor !== "none" && type.isArchived && (
                        <span className={styles.warning}>Archived, so it is not required of anyone.</span>
                      )}
                    </div>
                    <div className={styles.itemActions}>
                      {type.requiredFor !== "none" && (
                        <Badge variant={type.enforcement === "block" ? "danger" : "warning"}>
                          {requirementLabel(type.requiredFor)} · {enforcementLabel(type.enforcement)}
                        </Badge>
                      )}
                      {type.isArchived && <Badge variant="neutral">Archived</Badge>}
                      {canManage && (
                        <>
                          <Button size="sm" variant="ghost" onClick={() => setRequiring(type.id)}>
                            Requirement
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setEditing({ id: type.id, leadDays: type.alertLeadDays.join(", ") })}
                          >
                            Alert days
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => update.mutate({ type, isArchived: !type.isArchived })}>
                            {type.isArchived ? "Restore" : "Archive"}
                          </Button>
                        </>
                      )}
                    </div>
                  </>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {canManage && (
        <form
          className={styles.inlineForm}
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim() && parsedNew) create.mutate({ name: name.trim(), alertLeadDays: parsedNew });
          }}
        >
          <FormField label="New document type">
            <Input aria-label="New document type" value={name} maxLength={80} onChange={(event) => setName(event.target.value)} />
          </FormField>
          <FormField label="Alert days" error={parsedNew ? undefined : "1–5 numbers from 1 to 365"}>
            <Input aria-label="Alert days" value={leadDays} onChange={(event) => setLeadDays(event.target.value)} />
          </FormField>
          <Button type="submit" size="sm" loading={create.isPending} disabled={!name.trim() || !parsedNew}>
            Add
          </Button>
        </form>
      )}
    </section>
  );
}

/** Setup tab of the Transport Staff page: the organization's job titles and document types. */
export function StaffSetupPanel({ canManage }: { canManage: boolean }) {
  return (
    <div className={styles.setupGrid}>
      <JobTitlesCard canManage={canManage} />
      <DocumentTypesCard canManage={canManage} />
    </div>
  );
}
