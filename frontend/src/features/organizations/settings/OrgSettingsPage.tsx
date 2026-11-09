import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Building2,
  MapPin,
  ShieldAlert,
  Bell,
  CreditCard,
  Users,
  Info,
  ExternalLink,
} from "lucide-react";
import { Tabs } from "../../../shared/components/Tabs/Tabs";
import { Card, CardHeader, CardBody, CardFooter } from "../../../shared/components/Card/Card";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Toggle } from "../../../shared/components/Toggle/Toggle";
import { Button } from "../../../shared/components/Button/Button";
import { Badge } from "../../../shared/components/Badge/Badge";
import { LoadingScreen } from "../../../shared/components/LoadingScreen/LoadingScreen";
import { EmptyState } from "../../../shared/components/EmptyState/EmptyState";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { useAuthStore } from "../../../shared/stores/authStore";
import { ApiError } from "../../../shared/api/types";
import { getOrganization, updateOrganizationSettings, type Organization } from "../api";
import { statusLabel, statusTone, orgTypeLabel } from "../labels";
import styles from "./OrgSettingsPage.module.css";

const ORG_SETTINGS_TABS = [
  { id: "profile", label: "School Profile" },
  { id: "geofence", label: "Transportation & Geofence" },
  { id: "safety", label: "Safety & Speed Alerts" },
  { id: "notifications", label: "Notifications" },
  { id: "account", label: "Subscription & Team" },
];

export function OrgSettingsPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const principal = useAuthStore((s) => s.principal);
  const orgId = principal?.organizationId;

  const [activeTab, setActiveTab] = useState("profile");

  const { data: organization, isLoading, isError, error } = useQuery<Organization>({
    queryKey: ["organization", orgId],
    queryFn: () => getOrganization(orgId!),
    enabled: Boolean(orgId),
  });

  // Profile Form State
  const [nameDraft, setNameDraft] = useState("");

  // Geofence & Transport State
  const [latitudeDraft, setLatitudeDraft] = useState<string>("");
  const [longitudeDraft, setLongitudeDraft] = useState<string>("");
  const [radiusDraft, setRadiusDraft] = useState<string>("250");
  const [approachingDraft, setApproachingDraft] = useState<string>("300");

  // Safety Preferences State (Local client-side persistent storage/preference)
  const [speedLimit, setSpeedLimit] = useState(60);
  const [harshEvents, setHarshEvents] = useState(true);
  const [sosAlerts, setSosAlerts] = useState(true);

  // Notification Preferences State
  const [notifyBoarding, setNotifyBoarding] = useState(true);
  const [notifyApproaching, setNotifyApproaching] = useState(true);
  const [notifyDelays, setNotifyDelays] = useState(true);
  const [weeklyDigest, setWeeklyDigest] = useState(true);

  useEffect(() => {
    if (organization) {
      setNameDraft(organization.name);
      setLatitudeDraft(organization.latitude !== null ? String(organization.latitude) : "");
      setLongitudeDraft(organization.longitude !== null ? String(organization.longitude) : "");
      setRadiusDraft(organization.geofenceRadiusM !== null ? String(organization.geofenceRadiusM) : "250");
      setApproachingDraft(String(organization.approachingDistanceM ?? 300));
    }
  }, [organization]);

  const updateMutation = useMutation({
    mutationFn: (input: Parameters<typeof updateOrganizationSettings>[1]) =>
      updateOrganizationSettings(orgId!, input),
    onSuccess: (updated) => {
      queryClient.setQueryData(["organization", orgId], updated);
      queryClient.invalidateQueries({ queryKey: ["organizations"] });
      toast.success("Settings updated", "Your organization settings have been saved.");
    },
    onError: (err) => {
      toast.error(
        "Could not update settings",
        err instanceof ApiError ? err.message : "An unexpected error occurred. Please try again.",
      );
    },
  });

  if (!orgId) {
    return (
      <EmptyState
        icon={<Building2 size={32} />}
        title="No Organization Assigned"
        description="Your user account is not linked to an organization."
      />
    );
  }

  if (isLoading) {
    return <LoadingScreen />;
  }

  if (isError || !organization) {
    return (
      <div className={styles.page}>
        <div className={styles.notice}>
          <Info size={16} className={styles.noticeIcon} />
          <p className={styles.noticeText}>
            Could not load organization details: {error instanceof Error ? error.message : "Unknown error"}
          </p>
        </div>
      </div>
    );
  }

  const handleSaveProfile = () => {
    const trimmed = nameDraft.trim();
    if (!trimmed) {
      toast.error("Invalid Name", "Organization name cannot be empty.");
      return;
    }
    updateMutation.mutate({ name: trimmed });
  };

  const handleSaveGeofence = () => {
    const lat = latitudeDraft.trim() ? parseFloat(latitudeDraft) : null;
    const lng = longitudeDraft.trim() ? parseFloat(longitudeDraft) : null;
    const rad = radiusDraft.trim() ? parseInt(radiusDraft, 10) : null;
    const app = approachingDraft.trim() ? parseInt(approachingDraft, 10) : 300;

    if ((lat !== null || lng !== null || rad !== null) && (lat === null || lng === null || rad === null)) {
      toast.error("Incomplete Geofence", "Latitude, longitude, and geofence radius must be configured together.");
      return;
    }

    if (lat !== null && (lat < -90 || lat > 90)) {
      toast.error("Invalid Latitude", "Latitude must be between -90 and 90.");
      return;
    }

    if (lng !== null && (lng < -180 || lng > 180)) {
      toast.error("Invalid Longitude", "Longitude must be between -180 and 180.");
      return;
    }

    if (rad !== null && rad <= 0) {
      toast.error("Invalid Radius", "Geofence radius must be a positive number.");
      return;
    }

    if (app <= 0) {
      toast.error("Invalid Approach Distance", "Approaching distance must be a positive number.");
      return;
    }

    updateMutation.mutate({
      latitude: lat,
      longitude: lng,
      geofenceRadiusM: rad,
      approachingDistanceM: app,
    });
  };

  const handleSavePreferences = (category: string) => {
    toast.success("Preferences Saved", `${category} preferences have been updated.`);
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Organization Settings</h1>
        <p className={styles.description}>
          Manage school profile, campus geofencing, transportation thresholds, and parent notification preferences.
        </p>
      </header>

      <Tabs options={ORG_SETTINGS_TABS} activeId={activeTab} onSelect={setActiveTab} />

      <main className={styles.content}>
        {/* Tab 1: School Profile */}
        {activeTab === "profile" && (
          <section className={styles.section}>
            <Card>
              <CardHeader
                title="School Profile"
                subtitle="The official name and structural details of your school."
                icon={<Building2 size={18} />}
              />
              <CardBody>
                <FormField label="School / Organization Name">
                  <Input
                    value={nameDraft}
                    onChange={(e) => setNameDraft(e.target.value)}
                    placeholder="Enter school name"
                  />
                </FormField>
                <dl className={styles.detailList}>
                  <div className={styles.detailItem}>
                    <dt className={styles.detailLabel}>Type</dt>
                    <dd className={styles.detailValue}>{orgTypeLabel(organization.orgType)}</dd>
                  </div>
                  <div className={styles.detailItem}>
                    <dt className={styles.detailLabel}>Status</dt>
                    <dd className={styles.detailValue}>
                      <Badge variant={statusTone(organization.status)} dot>
                        {statusLabel(organization.status)}
                      </Badge>
                    </dd>
                  </div>
                  <div className={styles.detailItem}>
                    <dt className={styles.detailLabel}>Region ID</dt>
                    <dd className={`${styles.detailValue} ${styles.mono}`}>{organization.regionId}</dd>
                  </div>
                  <div className={styles.detailItem}>
                    <dt className={styles.detailLabel}>Organization ID</dt>
                    <dd className={`${styles.detailValue} ${styles.mono}`}>{organization.id}</dd>
                  </div>
                </dl>
              </CardBody>
              <CardFooter className={styles.actions}>
                <Button
                  loading={updateMutation.isPending}
                  disabled={nameDraft.trim() === organization.name}
                  onClick={handleSaveProfile}
                >
                  Save Profile
                </Button>
              </CardFooter>
            </Card>
          </section>
        )}

        {/* Tab 2: Transportation & Geofence */}
        {activeTab === "geofence" && (
          <section className={styles.section}>
            <Card>
              <CardHeader
                title="School Campus Geofence"
                subtitle="Defines your school's geographic center and boundary. Used to detect bus arrival ('Arrived at School')."
                icon={<MapPin size={18} />}
              />
              <CardBody>
                <div className={styles.formGrid}>
                  <FormField label="Campus Latitude">
                    <Input
                      type="number"
                      step="any"
                      placeholder="e.g. 2.046934"
                      value={latitudeDraft}
                      onChange={(e) => setLatitudeDraft(e.target.value)}
                    />
                  </FormField>
                  <FormField label="Campus Longitude">
                    <Input
                      type="number"
                      step="any"
                      placeholder="e.g. 45.318162"
                      value={longitudeDraft}
                      onChange={(e) => setLongitudeDraft(e.target.value)}
                    />
                  </FormField>
                </div>
                <FormField label="Campus Geofence Radius (meters)">
                  <Input
                    type="number"
                    min={50}
                    max={2000}
                    step={10}
                    placeholder="e.g. 250"
                    value={radiusDraft}
                    onChange={(e) => setRadiusDraft(e.target.value)}
                  />
                </FormField>
                <div className={styles.notice}>
                  <Info size={16} className={styles.noticeIcon} />
                  <p className={styles.noticeText}>
                    When school buses cross into this boundary radius, the system automatically marks the bus as arrived
                    at school and notifies monitoring operators and parents.
                  </p>
                </div>
              </CardBody>
              <CardFooter className={styles.actions}>
                <Button loading={updateMutation.isPending} onClick={handleSaveGeofence}>
                  Save Geofence
                </Button>
              </CardFooter>
            </Card>

            <Card>
              <CardHeader
                title="Approaching Stop Threshold"
                subtitle="Controls the distance trigger for notifying parents that the bus is nearing their stop (ADR-0014)."
                icon={<MapPin size={18} />}
              />
              <CardBody>
                <FormField label="Approaching Distance (meters)">
                  <Input
                    type="number"
                    min={100}
                    max={2000}
                    step={50}
                    value={approachingDraft}
                    onChange={(e) => setApproachingDraft(e.target.value)}
                  />
                </FormField>
                <div className={styles.notice}>
                  <Info size={16} className={styles.noticeIcon} />
                  <p className={styles.noticeText}>
                    Standard default is 300 meters (~2 minutes before bus arrives at student stop). When a vehicle reaches
                    this threshold distance along its active route, an automatic 'Bus Approaching' alert is dispatched.
                  </p>
                </div>
              </CardBody>
              <CardFooter className={styles.actions}>
                <Button loading={updateMutation.isPending} onClick={handleSaveGeofence}>
                  Save Approach Threshold
                </Button>
              </CardFooter>
            </Card>
          </section>
        )}

        {/* Tab 3: Safety & Speed Alerts */}
        {activeTab === "safety" && (
          <section className={styles.section}>
            <Card>
              <CardHeader
                title="Fleet Safety Rules & Speed Limits"
                subtitle="Operational thresholds for automated alert generation during active trips (ADR-0055)."
                icon={<ShieldAlert size={18} />}
              />
              <CardBody>
                <FormField label="Maximum Speed Limit (km/h)">
                  <Input
                    type="number"
                    min={30}
                    max={120}
                    step={5}
                    value={speedLimit}
                    onChange={(e) => setSpeedLimit(parseInt(e.target.value, 10) || 60)}
                  />
                </FormField>
                <div className={styles.toggleList}>
                  <Toggle
                    label="Harsh Event Detection"
                    description="Automatically flag harsh braking, sudden cornering, and rapid acceleration from bus sensors"
                    checked={harshEvents}
                    onChange={(e) => setHarshEvents(e.target.checked)}
                  />
                  <Toggle
                    label="SOS Alarm Immediate Escalation"
                    description="Broadcast driver emergency button presses directly to all school transport managers"
                    checked={sosAlerts}
                    onChange={(e) => setSosAlerts(e.target.checked)}
                  />
                </div>
              </CardBody>
              <CardFooter className={styles.actions}>
                <Button onClick={() => handleSavePreferences("Safety")}>
                  Save Safety Rules
                </Button>
              </CardFooter>
            </Card>
          </section>
        )}

        {/* Tab 4: Notifications */}
        {activeTab === "notifications" && (
          <section className={styles.section}>
            <Card>
              <CardHeader
                title="Parent Notification Preferences"
                subtitle="Select which events generate push and SMS notifications for parents."
                icon={<Bell size={18} />}
              />
              <CardBody>
                <div className={styles.toggleList}>
                  <Toggle
                    label="Student Boarded & Alighted Alerts"
                    description="Notify parent immediately when student scans RFID card or driver marks boarding"
                    checked={notifyBoarding}
                    onChange={(e) => setNotifyBoarding(e.target.checked)}
                  />
                  <Toggle
                    label="Bus Approaching Stop Alerts"
                    description="Send alert 2 minutes before the bus reaches the student's designated stop"
                    checked={notifyApproaching}
                    onChange={(e) => setNotifyApproaching(e.target.checked)}
                  />
                  <Toggle
                    label="Trip Delays & Route Interruption Alerts"
                    description="Send instant notice if bus is delayed more than 10 minutes by traffic or weather"
                    checked={notifyDelays}
                    onChange={(e) => setNotifyDelays(e.target.checked)}
                  />
                  <Toggle
                    label="Weekly Attendance & Safety Summary"
                    description="Send weekly digest email to parents every Friday afternoon"
                    checked={weeklyDigest}
                    onChange={(e) => setWeeklyDigest(e.target.checked)}
                  />
                </div>
              </CardBody>
              <CardFooter className={styles.actions}>
                <Button onClick={() => handleSavePreferences("Notification")}>
                  Save Notification Preferences
                </Button>
              </CardFooter>
            </Card>
          </section>
        )}

        {/* Tab 5: Subscription & Team */}
        {activeTab === "account" && (
          <section className={styles.section}>
            <Card>
              <CardHeader
                title="School Subscription & Plan"
                subtitle="Your active RAAD platform subscription, billing plan, and fleet limits."
                icon={<CreditCard size={18} />}
                action={
                  <Link to="/org/billing">
                    <Button variant="secondary" size="sm">
                      Manage Billing <ExternalLink size={14} style={{ marginLeft: 4 }} />
                    </Button>
                  </Link>
                }
              />
              <CardBody>
                <div className={styles.paramRow}>
                  <div className={styles.paramInfo}>
                    <span className={styles.paramLabel}>Subscription Status</span>
                    <span className={styles.paramDesc}>Current tenant operational standing</span>
                  </div>
                  <Badge variant="success">Active</Badge>
                </div>
                <div className={styles.paramRow}>
                  <div className={styles.paramInfo}>
                    <span className={styles.paramLabel}>Trial State</span>
                    <span className={styles.paramDesc}>Time-boxed evaluation period</span>
                  </div>
                  <Badge variant="neutral">{organization.trialState}</Badge>
                </div>
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                title="School Staff & User Accounts"
                subtitle="Manage administrators, transport managers, drivers, and parents with access."
                icon={<Users size={18} />}
                action={
                  <Link to="/org/users">
                    <Button variant="secondary" size="sm">
                      Open Users & Roles <ExternalLink size={14} style={{ marginLeft: 4 }} />
                    </Button>
                  </Link>
                }
              />
              <CardBody>
                <p className={styles.paramDesc}>
                  You have full administrative authority to invite additional staff, register drivers, and invite parents
                  specifically for <strong>{organization.name}</strong>.
                </p>
              </CardBody>
            </Card>
          </section>
        )}
      </main>
    </div>
  );
}
