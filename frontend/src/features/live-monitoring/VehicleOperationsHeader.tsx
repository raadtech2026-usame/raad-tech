import { useState, useRef, useEffect } from "react";
import { Bus, ChevronDown, Cpu, Radio, Search, Video, WifiOff } from "lucide-react";
import clsx from "clsx";
import { Badge } from "../../shared/components/Badge/Badge";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import type { ActiveDevice, VehicleOption } from "./api";
import { GpsFixBadge } from "./GpsFixBadge";
import type { VehicleActiveDeviceStatus } from "./useVehicleActiveDevice";
import type { UseVehiclePositionResult } from "./useVehiclePosition";
import styles from "./VehicleOperationsHeader.module.css";

/** ADR-0031 — the vehicle picker's sentinel value for the fleet-wide "All Vehicles" mode, a
 * third state distinct from both `""` (nothing selected yet) and a real vehicle id. Exported so
 * `LiveTrackingPage.tsx` can recognize it without duplicating the literal. */
export const ALL_VEHICLES_ID = "__all__";

export interface VehicleOperationsHeaderProps {
  vehicles: VehicleOption[];
  vehiclesLoading: boolean;
  selectedVehicleId: string;
  onSelectVehicle: (vehicleId: string) => void;
  gps: Pick<
    UseVehiclePositionResult,
    "wsStatus" | "isAuthOrPolicyClose" | "livePosition" | "gpsFixStatus"
  >;
  deviceStatus: VehicleActiveDeviceStatus;
  device: ActiveDevice | null;
  showCameraChip: boolean;
  showAllVehiclesOption: boolean;
}

export function VehicleOperationsHeader({
  vehicles,
  vehiclesLoading,
  selectedVehicleId,
  onSelectVehicle,
  gps,
  deviceStatus,
  device,
  showCameraChip,
  showAllVehiclesOption,
}: VehicleOperationsHeaderProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [searchFilter, setSearchFilter] = useState("");
  const pickerRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const isFleetMode = selectedVehicleId === ALL_VEHICLES_ID;
  const selectedVehicle = vehicles.find((v) => v.id === selectedVehicleId) ?? null;
  const gpsConnected =
    selectedVehicleId !== "" && gps.wsStatus === "open" && !gps.isAuthOrPolicyClose;
  const deviceOnline = deviceStatus === "ready" && device !== null && device.isOnline;
  const cameraCount = deviceStatus === "ready" && device !== null ? device.cameras.length : null;

  // Click outside to dismiss popover
  useEffect(() => {
    if (!isOpen) return;
    const onPointerDown = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen]);

  // Focus search input when popover opens
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => searchInputRef.current?.focus(), 50);
    } else {
      setSearchFilter("");
    }
  }, [isOpen]);

  const filteredVehicles = vehicles.filter((v) => {
    if (!searchFilter.trim()) return true;
    const term = searchFilter.toLowerCase();
    return v.plateNo.toLowerCase().includes(term) || (v.label && v.label.toLowerCase().includes(term));
  });

  return (
    <div className={styles.header}>
      <div className={styles.vehiclePicker} ref={pickerRef}>
        <span className={styles.vehicleIcon} aria-hidden="true">
          <Bus size={18} />
        </span>
        <div className={styles.vehiclePickerBody}>
          {vehiclesLoading ? (
            <Skeleton width={180} height={26} />
          ) : (
            <div className={styles.pickerContainer}>
              {/* Rich styled trigger button */}
              <button
                type="button"
                className={clsx(styles.pickerTrigger, isOpen && styles.pickerTriggerOpen)}
                onClick={() => setIsOpen((prev) => !prev)}
                aria-haspopup="listbox"
                aria-expanded={isOpen}
              >
                <div className={styles.pickerTriggerText}>
                  {isFleetMode ? (
                    <span className={styles.fleetSelectedLabel}>All Vehicles</span>
                  ) : selectedVehicle ? (
                    <div className={styles.vehicleSelectedSummary}>
                      <span className={styles.selectedPlateBadge}>{selectedVehicle.plateNo}</span>
                      {selectedVehicle.label && (
                        <span className={styles.selectedLabelText}>{selectedVehicle.label}</span>
                      )}
                    </div>
                  ) : (
                    <span className={styles.pickerPlaceholder}>Select a vehicle…</span>
                  )}
                </div>
                <ChevronDown
                  size={15}
                  className={clsx(styles.pickerChevron, isOpen && styles.pickerChevronOpen)}
                  aria-hidden="true"
                />
              </button>

              {/* Rich Dropdown Popover */}
              {isOpen && (
                <div className={styles.pickerDropdown} role="listbox">
                  <div className={styles.searchWrapper}>
                    <Search size={14} className={styles.searchIcon} aria-hidden="true" />
                    <input
                      ref={searchInputRef}
                      type="text"
                      className={styles.pickerSearchInput}
                      placeholder="Search plate or route…"
                      value={searchFilter}
                      onChange={(e) => setSearchFilter(e.target.value)}
                    />
                  </div>

                  <div className={styles.optionsContainer}>
                    {showAllVehiclesOption && (
                      <button
                        type="button"
                        className={clsx(styles.optionRow, isFleetMode && styles.optionRowActive)}
                        onClick={() => {
                          onSelectVehicle(ALL_VEHICLES_ID);
                          setIsOpen(false);
                        }}
                      >
                        <Radio size={14} className={styles.fleetOptionIcon} />
                        <div className={styles.optionInfo}>
                          <span className={styles.optionPlateName}>All Vehicles</span>
                          <span className={styles.optionMetaHint}>Fleet-wide Live Overview</span>
                        </div>
                        {isFleetMode && <span className={styles.activeCheck}>✓</span>}
                      </button>
                    )}

                    {filteredVehicles.map((vehicle) => {
                      const isSelected = vehicle.id === selectedVehicleId;
                      return (
                        <button
                          key={vehicle.id}
                          type="button"
                          className={clsx(styles.optionRow, isSelected && styles.optionRowActive)}
                          onClick={() => {
                            onSelectVehicle(vehicle.id);
                            setIsOpen(false);
                          }}
                        >
                          <div className={styles.optionVehicleBadge}>
                            <Bus size={13} className={styles.optionBusIcon} aria-hidden="true" />
                            <span className={styles.optionPlateName}>{vehicle.plateNo}</span>
                            {vehicle.label && (
                              <span className={styles.optionLabelSub}>{vehicle.label}</span>
                            )}
                          </div>
                          {isSelected && <span className={styles.activeCheck}>✓</span>}
                        </button>
                      );
                    })}

                    {filteredVehicles.length === 0 && (
                      <div className={styles.emptyOptions}>No vehicles match "{searchFilter}"</div>
                    )}
                  </div>
                </div>
              )}

              {/* Underlying accessible select for screen readers and automated test harnesses */}
              <select
                className={styles.accessibleSelect}
                value={selectedVehicleId}
                onChange={(e) => onSelectVehicle(e.target.value)}
                aria-label="Vehicle"
                tabIndex={-1}
              >
                <option value="">Select a vehicle</option>
                {showAllVehiclesOption && <option value={ALL_VEHICLES_ID}>All Vehicles</option>}
                {vehicles.map((vehicle) => (
                  <option key={vehicle.id} value={vehicle.id}>
                    {vehicle.plateNo}
                    {vehicle.label ? ` — ${vehicle.label}` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}
          <span className={styles.vehicleHint}>
            {isFleetMode
              ? "Fleet Overview — every online vehicle"
              : selectedVehicle
                ? "Vehicle Operations"
                : "Select a vehicle to begin"}
          </span>
        </div>
      </div>

      {selectedVehicleId !== "" && !isFleetMode && (
        <div className={styles.statChips}>
          <div className={styles.chip} data-testid="chip-gps">
            <span className={styles.chipLabel}>GPS</span>
            {gpsConnected ? (
              <GpsFixBadge status={gps.gpsFixStatus} />
            ) : (
              <>
                <WifiOff size={14} className={styles.chipIconMuted} />
                <Badge variant="neutral">
                  {gps.isAuthOrPolicyClose ? "Not authorized" : "Connecting"}
                </Badge>
              </>
            )}
          </div>

          <div className={styles.chip} data-testid="chip-device">
            <Cpu size={14} className={deviceOnline ? styles.chipIconLive : styles.chipIconMuted} />
            <span className={styles.chipLabel}>Device</span>
            {deviceStatus === "loading" && <Skeleton width={64} height={16} />}
            {deviceStatus === "no-assignment" && <Badge variant="neutral">No device</Badge>}
            {deviceStatus === "error" && <Badge variant="danger">Unavailable</Badge>}
            {deviceStatus === "ready" && device && (
              <>
                <Badge variant={device.isOnline ? "success" : "warning"} dot pulsing={device.isOnline}>
                  {device.isOnline ? "Online" : "Offline"}
                </Badge>
                <span className={styles.terminalId}>{device.terminalId}</span>
              </>
            )}
          </div>

          {showCameraChip && (
            <div className={styles.chip} data-testid="chip-cameras">
              <Video size={14} className={cameraCount ? styles.chipIconLive : styles.chipIconMuted} />
              <span className={styles.chipLabel}>Cameras</span>
              <Badge variant={cameraCount ? "info" : "neutral"}>
                {cameraCount === null ? "—" : cameraCount}
              </Badge>
            </div>
          )}

          {gps.livePosition && (
            <span className={styles.lastUpdate}>
              {gps.gpsFixStatus === "no_fix" ? "Last valid position" : "Last GPS update"}{" "}
              {new Date(gps.livePosition.eventTime).toLocaleTimeString()}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
