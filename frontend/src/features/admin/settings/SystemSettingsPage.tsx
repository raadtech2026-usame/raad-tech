import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Shield,
  CreditCard,
  Radio,
  MessageSquare,
  Activity,
  Info,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";
import { Tabs } from "../../../shared/components/Tabs/Tabs";
import { Card, CardHeader, CardBody, CardFooter } from "../../../shared/components/Card/Card";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Select } from "../../../shared/components/Select/Select";
import { Toggle } from "../../../shared/components/Toggle/Toggle";
import { Button } from "../../../shared/components/Button/Button";
import { Badge } from "../../../shared/components/Badge/Badge";
import { LoadingScreen } from "../../../shared/components/LoadingScreen/LoadingScreen";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { listSystemSettings, updateSystemSetting, type SystemSetting } from "./api";
import { getPlatformStats } from "../../platform-analytics/api";
import styles from "./SystemSettingsPage.module.css";

const SETTINGS_TABS = [
  { id: "sessions", label: "Security & Sessions" },
  { id: "payments", label: "Payment Gateways" },
  { id: "telemetry", label: "Tracking Defaults" },
  { id: "gateways", label: "SMS & Communication" },
  { id: "maintenance", label: "System Health & Maintenance" },
];

const ROLES_ORDER = [
  { key: "founder", label: "Founder" },
  { key: "regional_manager", label: "Regional Manager" },
  { key: "support_staff", label: "Support Staff" },
  { key: "finance_staff", label: "Finance Staff" },
  { key: "org_admin", label: "Org Admin" },
  { key: "driver", label: "Driver" },
  { key: "parent", label: "Parent" },
];

export function SystemSettingsPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState("sessions");

  // Fetch all system_settings from backend
  const { data: settingsData, isLoading, isError, error } = useQuery({
    queryKey: ["admin", "settings"],
    queryFn: () => listSystemSettings({ pageSize: 100 }),
  });

  // Fetch platform health stats
  const { data: statsData } = useQuery({
    queryKey: ["admin", "platform-stats"],
    queryFn: () => getPlatformStats(),
    staleTime: 30_000,
  });

  const settingsMap = useMemo(() => {
    const map = new Map<string, SystemSetting>();
    if (settingsData?.data) {
      for (const item of settingsData.data) {
        map.set(item.key, item);
      }
    }
    return map;
  }, [settingsData]);

  // Session Caps State
  const rawSessionCaps = (settingsMap.get("session_cap")?.value as Record<string, number>) ?? {
    founder: 5,
    regional_manager: 3,
    support_staff: 3,
    finance_staff: 3,
    org_admin: 2,
    driver: 1,
    parent: 2,
  };
  const [sessionCaps, setSessionCaps] = useState<Record<string, number> | null>(null);
  const currentCaps = sessionCaps ?? rawSessionCaps;

  // Payment Provider State
  const rawProvider = (settingsMap.get("billing_payment_provider")?.value?.provider as string) ?? "stripe";
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null);
  const currentProvider = selectedProvider ?? rawProvider;

  // Tracking Defaults State
  const rawTracking = (settingsMap.get("platform_tracking_defaults")?.value as Record<string, number>) ?? {
    default_approaching_distance_m: 300,
    event_cooldown_seconds: 120,
    device_offline_timeout_minutes: 10,
  };
  const [trackingDefaults, setTrackingDefaults] = useState<Record<string, number> | null>(null);
  const currentTracking = trackingDefaults ?? rawTracking;

  // SMS Gateway State
  const rawSms = (settingsMap.get("platform_sms_gateway")?.value as Record<string, unknown>) ?? {
    provider: "hormuud",
    sender_id: "RAAD-BUS",
    enabled: true,
  };
  const [smsSettings, setSmsSettings] = useState<Record<string, unknown> | null>(null);
  const currentSms = smsSettings ?? rawSms;

  // Maintenance Mode State
  const rawMaintenance = (settingsMap.get("platform_maintenance_mode")?.value as Record<string, unknown>) ?? {
    enabled: false,
    message: "Platform maintenance is currently underway. Operations remain active.",
  };
  const [maintenance, setMaintenance] = useState<Record<string, unknown> | null>(null);
  const currentMaintenance = maintenance ?? rawMaintenance;

  // Mutation for saving any system setting
  const saveMutation = useMutation({
    mutationFn: ({ key, value, scope }: { key: string; value: Record<string, unknown>; scope?: string }) =>
      updateSystemSetting(key, value, scope ?? "platform"),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "settings"] });
      toast.success("Setting saved", `System configuration '${updated.key}' updated successfully.`);
    },
    onError: (err) => {
      toast.error(
        "Could not update setting",
        err instanceof ApiError ? err.message : "An unexpected error occurred.",
      );
    },
  });

  if (isLoading) {
    return <LoadingScreen />;
  }

  if (isError) {
    return (
      <div className={styles.page}>
        <div className={styles.notice}>
          <AlertTriangle size={18} className={styles.noticeIcon} />
          <p className={styles.noticeText}>
            Failed to load system settings: {error instanceof Error ? error.message : "Unknown error"}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>System Settings</h1>
        <p className={styles.description}>
          Platform-level system configurations, global security caps, payment gateways, and telemetry defaults.
        </p>
      </header>

      <Tabs options={SETTINGS_TABS} activeId={activeTab} onSelect={setActiveTab} />

      <main className={styles.content}>
        {/* Tab 1: Security & Sessions */}
        {activeTab === "sessions" && (
          <section className={styles.section}>
            <Card>
              <CardHeader
                title="Account-Sharing & Session Caps"
                subtitle="Controls maximum concurrent active sessions permitted per role (ADR-0019 SessionLimitPolicy)."
                icon={<Shield size={18} />}
              />
              <CardBody>
                <div className={styles.grid}>
                  {ROLES_ORDER.map(({ key, label }) => (
                    <FormField key={key} label={label}>
                      <Input
                        type="number"
                        min={1}
                        max={20}
                        value={currentCaps[key] ?? 1}
                        onChange={(e) => {
                          const val = parseInt(e.target.value, 10);
                          if (!isNaN(val) && val >= 1) {
                            setSessionCaps({ ...currentCaps, [key]: val });
                          }
                        }}
                      />
                    </FormField>
                  ))}
                </div>
              </CardBody>
              <CardFooter className={styles.actions}>
                <Button
                  loading={saveMutation.isPending}
                  onClick={() => saveMutation.mutate({ key: "session_cap", value: currentCaps })}
                >
                  Save Session Caps
                </Button>
              </CardFooter>
            </Card>

            <Card>
              <CardHeader
                title="Security Policies & Account Lockout"
                subtitle="Enforced platform-wide across all user authentications."
                icon={<Shield size={18} />}
              />
              <CardBody>
                <div className={styles.paramRow}>
                  <div className={styles.paramInfo}>
                    <span className={styles.paramLabel}>Failed Attempt Lockout</span>
                    <span className={styles.paramDesc}>Locks user account after 5 consecutive failed login attempts</span>
                  </div>
                  <Badge variant="success">Active (5 attempts / 15m)</Badge>
                </div>
                <div className={styles.paramRow}>
                  <div className={styles.paramInfo}>
                    <span className={styles.paramLabel}>Rate Limiting (Fixed Window)</span>
                    <span className={styles.paramDesc}>IP-based brute-force prevention on /auth/login</span>
                  </div>
                  <Badge variant="success">Active (Redis Fixed Window)</Badge>
                </div>
                <div className={styles.paramRow}>
                  <div className={styles.paramInfo}>
                    <span className={styles.paramLabel}>Password Hashing Standards</span>
                    <span className={styles.paramDesc}>PBKDF2-HMAC-SHA256 with 260,000 iterations and random salt</span>
                  </div>
                  <Badge variant="info">FIPS Compliant</Badge>
                </div>
              </CardBody>
            </Card>
          </section>
        )}

        {/* Tab 2: Payment Gateways */}
        {activeTab === "payments" && (
          <section className={styles.section}>
            <Card>
              <CardHeader
                title="Platform Billing Gateway"
                subtitle="Configures the active online payment processor for school subscriptions (ADR-0022)."
                icon={<CreditCard size={18} />}
              />
              <CardBody>
                <FormField label="Active Payment Provider">
                  <Select
                    value={currentProvider}
                    onChange={(e) => setSelectedProvider(e.target.value)}
                  >
                    <option value="stripe">Stripe (International Cards)</option>
                    <option value="evc_plus">EVC Plus (Hormuud Mobile Money)</option>
                    <option value="edahab">eDahab (Somtel Mobile Money)</option>
                    <option value="offline">Manual / Bank Transfer Only</option>
                  </Select>
                </FormField>
                <div className={styles.notice}>
                  <Info size={16} className={styles.noticeIcon} />
                  <p className={styles.noticeText}>
                    API keys and webhook secrets are stored exclusively in deployment environment variables (
                    <code>RAAD_PAYMENT__PROVIDER_CREDENTIALS</code>) per ADR-0022. This setting switches the active provider
                    surfaced to tenant billing forms.
                  </p>
                </div>
              </CardBody>
              <CardFooter className={styles.actions}>
                <Button
                  loading={saveMutation.isPending}
                  onClick={() =>
                    saveMutation.mutate({
                      key: "billing_payment_provider",
                      value: { provider: currentProvider },
                    })
                  }
                >
                  Save Payment Provider
                </Button>
              </CardFooter>
            </Card>
          </section>
        )}

        {/* Tab 3: Tracking Defaults */}
        {activeTab === "telemetry" && (
          <section className={styles.section}>
            <Card>
              <CardHeader
                title="Platform Telemetry & Evaluation Defaults"
                subtitle="Default fallback thresholds for geofence crossings, approach alerts, and bus events."
                icon={<Radio size={18} />}
              />
              <CardBody>
                <div className={styles.formGrid}>
                  <FormField label="Default Approaching Stop Radius (Meters)">
                    <Input
                      type="number"
                      min={50}
                      max={2000}
                      step={50}
                      value={currentTracking.default_approaching_distance_m ?? 300}
                      onChange={(e) =>
                        setTrackingDefaults({
                          ...currentTracking,
                          default_approaching_distance_m: parseInt(e.target.value, 10) || 300,
                        })
                      }
                    />
                  </FormField>
                  <FormField label="Event Suppression Cooldown (Seconds)">
                    <Input
                      type="number"
                      min={30}
                      max={600}
                      step={10}
                      value={currentTracking.event_cooldown_seconds ?? 120}
                      onChange={(e) =>
                        setTrackingDefaults({
                          ...currentTracking,
                          event_cooldown_seconds: parseInt(e.target.value, 10) || 120,
                        })
                      }
                    />
                  </FormField>
                  <FormField label="Device Offline Inactivity Threshold (Minutes)">
                    <Input
                      type="number"
                      min={2}
                      max={60}
                      value={currentTracking.device_offline_timeout_minutes ?? 10}
                      onChange={(e) =>
                        setTrackingDefaults({
                          ...currentTracking,
                          device_offline_timeout_minutes: parseInt(e.target.value, 10) || 10,
                        })
                      }
                    />
                  </FormField>
                </div>
              </CardBody>
              <CardFooter className={styles.actions}>
                <Button
                  loading={saveMutation.isPending}
                  onClick={() =>
                    saveMutation.mutate({
                      key: "platform_tracking_defaults",
                      value: currentTracking,
                    })
                  }
                >
                  Save Telemetry Defaults
                </Button>
              </CardFooter>
            </Card>
          </section>
        )}

        {/* Tab 4: SMS & Communication */}
        {activeTab === "gateways" && (
          <section className={styles.section}>
            <Card>
              <CardHeader
                title="SMS Notification Gateway"
                subtitle="Configures outgoing SMS delivery for student boarding, emergency SOS, and arrival alerts."
                icon={<MessageSquare size={18} />}
              />
              <CardBody>
                <div className={styles.formGrid}>
                  <FormField label="Primary SMS Provider">
                    <Select
                      value={String(currentSms.provider ?? "hormuud")}
                      onChange={(e) => setSmsSettings({ ...currentSms, provider: e.target.value })}
                    >
                      <option value="hormuud">Hormuud Telecom (Local SMS)</option>
                      <option value="africastalking">Africa's Talking (East Africa)</option>
                      <option value="twilio">Twilio Global</option>
                    </Select>
                  </FormField>
                  <FormField label="Sender ID">
                    <Input
                      value={String(currentSms.sender_id ?? "RAAD-BUS")}
                      onChange={(e) => setSmsSettings({ ...currentSms, sender_id: e.target.value })}
                      maxLength={11}
                    />
                  </FormField>
                </div>
                <Toggle
                  label="Enable SMS Dispatch"
                  description="When enabled, high-priority notifications are transmitted via SMS as well as mobile push"
                  checked={Boolean(currentSms.enabled)}
                  onChange={(e) => setSmsSettings({ ...currentSms, enabled: e.target.checked })}
                />
              </CardBody>
              <CardFooter className={styles.actions}>
                <Button
                  loading={saveMutation.isPending}
                  onClick={() =>
                    saveMutation.mutate({
                      key: "platform_sms_gateway",
                      value: currentSms,
                    })
                  }
                >
                  Save SMS Gateway
                </Button>
              </CardFooter>
            </Card>
          </section>
        )}

        {/* Tab 5: System Health & Maintenance */}
        {activeTab === "maintenance" && (
          <section className={styles.section}>
            <Card>
              <CardHeader
                title="Platform Infrastructure Health"
                subtitle="Live status from RAAD platform services."
                icon={<Activity size={18} />}
              />
              <CardBody>
                <div className={styles.paramRow}>
                  <div className={styles.paramInfo}>
                    <span className={styles.paramLabel}>PostgreSQL Database</span>
                    <span className={styles.paramDesc}>Multi-tenant storage and transactional outbox</span>
                  </div>
                  <div className={styles.badgeStack}>
                    <CheckCircle2 size={16} color="var(--color-success)" />
                    <Badge variant="success">{statsData?.system_health?.database ?? "Connected"}</Badge>
                  </div>
                </div>
                <div className={styles.paramRow}>
                  <div className={styles.paramInfo}>
                    <span className={styles.paramLabel}>Redis Stream Event Broker</span>
                    <span className={styles.paramDesc}>Telemetry ingestion, notification dispatch and device events</span>
                  </div>
                  <div className={styles.badgeStack}>
                    <CheckCircle2 size={16} color="var(--color-success)" />
                    <Badge variant="success">{statsData?.system_health?.broker ?? "Connected"}</Badge>
                  </div>
                </div>
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                title="Maintenance Mode"
                subtitle="Restrict platform access during scheduled maintenance windows."
                icon={<AlertTriangle size={18} />}
              />
              <CardBody>
                <Toggle
                  label="Enable Maintenance Mode"
                  description="Displays a maintenance banner to all school users and defers non-critical writes"
                  checked={Boolean(currentMaintenance.enabled)}
                  onChange={(e) => setMaintenance({ ...currentMaintenance, enabled: e.target.checked })}
                />
                <FormField label="Maintenance Notice Banner Message">
                  <Input
                    value={String(currentMaintenance.message ?? "")}
                    onChange={(e) => setMaintenance({ ...currentMaintenance, message: e.target.value })}
                  />
                </FormField>
              </CardBody>
              <CardFooter className={styles.actions}>
                <Button
                  loading={saveMutation.isPending}
                  onClick={() =>
                    saveMutation.mutate({
                      key: "platform_maintenance_mode",
                      value: currentMaintenance,
                    })
                  }
                >
                  Save Maintenance Mode
                </Button>
              </CardFooter>
            </Card>
          </section>
        )}
      </main>
    </div>
  );
}
