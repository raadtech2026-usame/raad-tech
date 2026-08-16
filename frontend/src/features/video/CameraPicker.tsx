import { FormField } from "../../shared/components/FormField/FormField";
import { Select } from "../../shared/components/Select/Select";
import type { VideoCameraOption } from "./api";

export interface CameraPickerProps {
  cameras: VideoCameraOption[];
  value: string;
  onChange: (cameraId: string) => void;
  /** Defaults to disabled whenever there is nothing to pick from (`cameras.length === 0`) —
   * override explicitly when the caller's own selection state (e.g. "no device chosen yet")
   * should drive it instead, matching `VideoPage`'s original `disabled={!selectedDevice}`. */
  disabled?: boolean;
}

/**
 * ADR-0028 §G: the camera `<Select>` block extracted from `VideoPage`, reused unchanged by both
 * the standalone device-first page and the unified Vehicle Operations view (where `cameras`
 * comes from `useVehicleActiveDevice`'s already-resolved device, never a manually-picked one).
 */
export function CameraPicker({ cameras, value, onChange, disabled }: CameraPickerProps) {
  return (
    <FormField label="Camera">
      <Select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label="Camera"
        disabled={disabled ?? cameras.length === 0}
      >
        <option value="">Select a camera</option>
        {cameras.map((camera) => (
          <option key={camera.id} value={camera.id}>
            {camera.label ?? `Channel ${camera.channelNo}`} ({camera.position})
          </option>
        ))}
      </Select>
    </FormField>
  );
}
