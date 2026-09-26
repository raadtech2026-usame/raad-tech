/**
 * ADR-0046 §1 - whether the terminal itself reports a video signal on a camera's channel (`0x0200`
 * item `0x15`). `absent` = no camera connected (or its cable cut); `unknown` = no report yet, treated
 * exactly as before ADR-0046. Kept out of `api.ts` so components can use it while tests mock the
 * network layer.
 */
export type CameraVideoSignal = "present" | "absent" | "unknown";

export function toCameraVideoSignal(raw: string | null | undefined): CameraVideoSignal {
  return raw === "present" || raw === "absent" ? raw : "unknown";
}

/** A camera the terminal reports as having no video signal is never presented or requested. */
export function isCameraConnected(camera: { videoSignal?: CameraVideoSignal }): boolean {
  return camera.videoSignal !== "absent";
}
