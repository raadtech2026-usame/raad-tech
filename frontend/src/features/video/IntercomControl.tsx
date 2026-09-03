import { useEffect, useState } from "react";
import { Mic, MicOff, PhoneOff, Radio } from "lucide-react";
import clsx from "clsx";
import { Badge } from "../../shared/components/Badge/Badge";
import { Button } from "../../shared/components/Button/Button";
import { useIntercomController } from "./useIntercomController";
import styles from "./IntercomControl.module.css";

export interface IntercomControlProps {
  deviceId: string | null;
  /** The channel to intercom on — defaults to the device's first camera's `channel_no` (ADR-0036
   * §6): intercom is device-level (one `LSZ-M01` module per vehicle, not per camera), so this is
   * a deliberate simplification, not a claim that intercom is inherently tied to "camera 1." */
  cameraId: string | null;
}

/**
 * "Talk to Driver" — real, two-way voice intercom (ADR-0036), not a video control. Deliberately
 * visually distinct from the Live Video Start/Stop buttons beside it: a mic icon, a push-to-talk
 * button, and an unmistakable "transmitting" state, so an operator never confuses this with the
 * video-only controls it sits next to.
 */
export function IntercomControl({ deviceId, cameraId }: IntercomControlProps) {
  const intercom = useIntercomController(deviceId, cameraId);

  // Stop-on-unmount already happens inside the hook itself; this only guards against a stuck
  // "talking" state if the component unmounts mid-press (e.g. navigating away while held).
  // Local-only UI state: whether the secondary microphone picker is revealed.
  const [pickerOpen, setPickerOpen] = useState(false);
  // The only conditions that justify showing device controls at all. Everything else is the
  // normal, zero-choice flow.
  const showMicRecovery = intercom.micSilent || intercom.micError !== null;
  useEffect(() => {
    if (!showMicRecovery) setPickerOpen(false);
  }, [showMicRecovery]);

  useEffect(() => {
    return () => intercom.stopTalking();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isIdle = intercom.phase === "idle" || intercom.phase === "stopped";
  const isPending = intercom.phase === "requesting" || intercom.phase === "connecting";
  const isConnected = intercom.phase === "connected";
  // Bug 1 fix: "failed"/"ended" are the backend/relay-driven terminal states (session became
  // FAILED/ENDED while this browser was still connected, `useIntercomController`'s own
  // `terminalEvent`) — rendered in the same bucket as a request-time error/unavailability
  // (a Badge + Retry), but with `terminalMessage` below giving the operator the *actual* reason
  // instead of the generic "Intercom unavailable" a request-time failure shows.
  const hasError =
    intercom.phase === "error" ||
    intercom.phase === "unavailable" ||
    intercom.phase === "failed" ||
    intercom.phase === "ended";
  const terminalMessage =
    intercom.phase === "failed"
      ? `Intercom call failed${intercom.terminalEvent?.reason ? ` (${intercom.terminalEvent.reason})` : ""}`
      : intercom.phase === "ended"
        ? "Intercom call ended"
        : null;

  return (
    <div className={styles.container}>
      {/* Hidden - carries only the bus mic's own audio; no picture, ever. */}
      <audio ref={intercom.audioRef} autoPlay hidden />

      {isIdle && (
        <Button
          size="sm"
          variant="secondary"
          leadingIcon={<Mic size={14} />}
          onClick={intercom.start}
          disabled={!intercom.canStart}
        >
          Talk to Driver
        </Button>
      )}

      {isPending && (
        <Badge variant="info" dot pulsing className={styles.statusBadge}>
          <Mic size={12} />
          Connecting intercom…
        </Badge>
      )}

      {hasError && (
        <>
          <Badge variant="danger" dot className={styles.statusBadge}>
            {intercom.requestError?.alreadyInUse
              ? "Another operator is talking to this bus"
              : terminalMessage ?? intercom.requestError?.message ?? "Intercom unavailable"}
          </Badge>
          <Button size="sm" variant="secondary" onClick={intercom.start} disabled={!intercom.canStart}>
            Retry
          </Button>
        </>
      )}

      {isConnected && (
        <div className={styles.activeGroup}>
          <Badge
            variant={intercom.isTransmitting ? "warning" : "success"}
            dot
            pulsing={intercom.isTransmitting}
            className={styles.statusBadge}
          >
            <Radio size={12} />
            {intercom.isTransmitting ? "Transmitting" : "Intercom connected"}
          </Badge>

          <button
            type="button"
            className={clsx(styles.talkButton, intercom.isTransmitting && styles.talkButtonActive)}
            // Click-to-talk (2026-09-03). A single activation handler replaces the previous
            // onMouseDown/onMouseUp/onTouchStart/onTouchEnd pairs: a native `button`'s `onClick`
            // fires for mouse, touch and keyboard (Enter/Space) alike, so the interaction works
            // without depending on pointer-down/up pairing - which is unreliable on touch and
            // impossible by keyboard. `toggleTalking` is idempotent, so a double-click cannot
            // start two capture pipelines.
            onClick={intercom.toggleTalking}
            disabled={intercom.micUnavailable}
            aria-pressed={intercom.isTransmitting}
            aria-label={
              intercom.isTransmitting
                ? `Talking, stops automatically in ${intercom.talkSecondsRemaining} seconds. Activate to stop now.`
                : `Talk to the driver, up to ${intercom.maxTalkSeconds} seconds`
            }
          >
            {intercom.isTransmitting ? <Mic size={16} /> : <MicOff size={16} />}
            {intercom.isTransmitting
              ? `TALKING · ${intercom.talkSecondsRemaining}s`
              : "TALK"}
          </button>

          {/* Live microphone level. The operator's only feedback that their mic is actually
              producing sound: on 2026-09-03 a virtual "Voice Changer" input device was selected
              by the browser and delivered exact zeros, while every layer below reported success
              and correctly-framed packets reached the MDVR. A meter makes that obvious at a
              glance instead of needing a packet capture. */}
          <div
            className={styles.micMeter}
            role="meter"
            aria-label="Microphone level"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(Math.min(1, intercom.micLevel * 8) * 100)}
            title={intercom.micDeviceLabel ?? "Microphone"}
          >
            <span
              className={clsx(styles.micMeterFill, intercom.micSilent && styles.micMeterSilent)}
              // x8 so ordinary speech (RMS ~0.05-0.15) fills a useful part of the bar rather
              // than a sliver; clamped so a shout cannot overflow it.
              style={{ width: `${Math.round(Math.min(1, intercom.micLevel * 8) * 100)}%` }}
            />
          </div>

          <Button
            size="sm"
            variant="danger"
            leadingIcon={<PhoneOff size={14} />}
            onClick={() => void intercom.stop()}
          >
            End Intercom
          </Button>
        </div>
      )}

      {/* Microphone. **Normal operation shows no device controls at all** (RAAD Mic Architecture
          Decision, Option C + 2026-09-03 product requirement): RAAD requests a generic input with
          `getUserMedia({ audio: true })` and never names hardware, so the operator simply talks.
          The small level indicator is the confirmation that audio is really being captured.

          Device selection is an **exception path only** - it appears after RAAD measures
          sustained silence, or after a capture failure. It is never part of the successful flow,
          and devices are never classified by name: the measured signal level is the authority. */}
      {isConnected && !showMicRecovery && (
        <div className={styles.micRow}>
          <span className={styles.micStatus}>
            <Mic size={12} />
            Microphone ready
          </span>
        </div>
      )}

      {isConnected && showMicRecovery && (
        <div className={styles.micRecovery}>
          <span className={styles.micError} role="alert">
            {intercom.micSilent
              ? "⚠ No microphone signal detected. The driver will hear silence. Check your computer’s microphone settings."
              : intercom.micError}
          </span>
          {intercom.micDevices.length > 0 && !pickerOpen && (
            <button
              type="button"
              className={styles.micChange}
              onClick={() => setPickerOpen(true)}
            >
              Choose another microphone
            </button>
          )}
          {pickerOpen && intercom.micDevices.length > 0 && (
            <label className={styles.micPicker}>
              <span className={styles.micPickerLabel}>Microphone</span>
              <select
                value={intercom.selectedMicDeviceId ?? ""}
                onChange={(event) => intercom.selectMicDevice(event.target.value || null)}
              >
                <option value="">System Default</option>
                {intercom.micDevices.map((device) => (
                  <option key={device.deviceId} value={device.deviceId}>
                    {device.label || "Unnamed input"}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}

    </div>
  );
}
