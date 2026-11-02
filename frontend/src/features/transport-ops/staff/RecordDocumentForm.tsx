import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileBadge } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Select } from "../../../shared/components/Select/Select";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { listDocumentTypes, recordStaffDocument, type StaffDocument } from "./api";
import styles from "./Staff.module.css";

const schema = z
  .object({
    typeId: z.string().min(1, "Choose a document type"),
    number: z.string().trim().max(64, "At most 64 characters"),
    issuedOn: z.string(),
    expiresOn: z.string(),
    notes: z.string().trim().max(500, "At most 500 characters"),
  })
  .refine((values) => !values.issuedOn || !values.expiresOn || values.expiresOn >= values.issuedOn, {
    message: "The expiry date is before the issue date",
    path: ["expiresOn"],
  });

type FormValues = z.infer<typeof schema>;

export interface RecordDocumentFormProps {
  open: boolean;
  onClose: () => void;
  staffId: string;
  staffName: string;
  /** When set, this is a renewal: the type is fixed and the old document becomes "Renewed". */
  renewing?: StaffDocument | null;
}

/**
 * Records a staff document's details (ADR-0051): no file or scan is stored, only what the
 * document says. A renewal is a new document; the old one is kept as history and stops
 * producing alerts.
 */
export function RecordDocumentForm({ open, onClose, staffId, staffName, renewing }: RecordDocumentFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const typesQuery = useQuery({
    queryKey: ["transport-staff", "document-types"],
    queryFn: () => listDocumentTypes(),
    enabled: open,
    staleTime: 60_000,
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { typeId: "", number: "", issuedOn: "", expiresOn: "", notes: "" },
  });

  const [fileName, setFileName] = useState<string | null>(null);
  const [fileContentType, setFileContentType] = useState<string | null>(null);
  const [fileData, setFileData] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      reset({ typeId: renewing?.typeId ?? "", number: "", issuedOn: "", expiresOn: "", notes: "" });
      setFileName(null);
      setFileContentType(null);
      setFileData(null);
    }
  }, [open, renewing, reset]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setFileContentType(file.type || "application/octet-stream");
    const reader = new FileReader();
    reader.onload = () => {
      setFileData(reader.result as string);
    };
    reader.readAsDataURL(file);
  };

  const handleRemoveFile = () => {
    setFileName(null);
    setFileContentType(null);
    setFileData(null);
  };

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      recordStaffDocument(staffId, {
        typeId: values.typeId,
        number: values.number.trim() || null,
        issuedOn: values.issuedOn || null,
        expiresOn: values.expiresOn || null,
        notes: values.notes.trim() || null,
        replacesId: renewing?.id ?? null,
        fileName,
        fileContentType,
        fileData,
      }),
    onSuccess: (document) => {
      queryClient.invalidateQueries({ queryKey: ["transport-staff", "documents"] });
      queryClient.invalidateQueries({ queryKey: ["transport-staff", "expiring"] });
      toast.success(renewing ? "Renewal recorded" : "Document recorded", document.typeName);
      onClose();
    },
    onError: (error) => {
      toast.error("Could not save", error instanceof ApiError ? error.message : "Please try again.");
    },
  });

  const onValid = handleSubmit((values) => mutation.mutate(values));
  const types = (typesQuery.data ?? []).filter((type) => !type.isArchived || type.id === renewing?.typeId);

  return (
    <FormDrawer
      open={open}
      onClose={() => !mutation.isPending && onClose()}
      icon={<FileBadge size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title={renewing ? `Renew ${renewing.typeName}` : "Add document"}
      subtitle={staffName}
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={mutation.isPending} onClick={onValid}>
            Save
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        <FormField
          label="Document type"
          error={errors.typeId?.message}
          hint={types.length === 0 && !typesQuery.isLoading ? "No document types yet — add them under Setup." : undefined}
        >
          <Select {...register("typeId")} aria-label="Document type" disabled={Boolean(renewing) || typesQuery.isLoading}>
            <option value="">Choose…</option>
            {types.map((type) => (
              <option key={type.id} value={type.id}>
                {type.name}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="Document number" hint="Visible to Org Admins only" error={errors.number?.message}>
          <Input {...register("number")} aria-label="Document number" autoComplete="off" />
        </FormField>
        <div className={styles.formRow}>
          <FormField label="Issued">
            <Input type="date" {...register("issuedOn")} aria-label="Issued" />
          </FormField>
          <FormField label="Expires" hint="Leave empty if it never expires" error={errors.expiresOn?.message}>
            <Input type="date" {...register("expiresOn")} aria-label="Expires" />
          </FormField>
        </div>
        <FormField
          label="Attachments / Identity Documents"
          hint="Upload national ID, driving license, or certificate (PDF, JPG, PNG)"
        >
          {fileName ? (
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "4px" }}>
              <span style={{ fontSize: "14px", fontWeight: 500, color: "var(--color-text-primary)" }}>
                {fileName}
              </span>
              <Button type="button" variant="ghost" size="sm" onClick={handleRemoveFile}>
                Remove
              </Button>
            </div>
          ) : (
            <Input
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,image/jpeg,image/png,application/pdf"
              aria-label="Attachments / Identity Documents"
              onChange={handleFileChange}
            />
          )}
        </FormField>
        <FormField label="Notes" error={errors.notes?.message}>
          <Input {...register("notes")} aria-label="Notes" />
        </FormField>
      </form>
    </FormDrawer>
  );
}
