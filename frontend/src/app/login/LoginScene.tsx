import { useEffect, useRef, useState } from "react";
import type { LoginPhase } from "./useLoginPhase";
import styles from "./LoginScene.module.css";

/** One route through the map, kept clear of the centred card for most of its length. The stop
 * dots below sit on its segment endpoints, so they are exactly on the line. */
const ROUTE_PATH =
  "M -40 780 C 140 760 220 620 260 480 S 300 220 520 180 S 1000 140 1180 220 S 1420 420 1380 620 S 1480 840 1660 860";
const ROUTE_STOPS: ReadonlyArray<[number, number]> = [
  [260, 480],
  [520, 180],
  [1180, 220],
  [1380, 620],
];
const ROADS = [
  "M 0 300 C 400 330 900 250 1600 300",
  "M 0 640 C 500 610 1100 690 1600 640",
  "M 420 0 C 450 300 370 700 460 1000",
  "M 1120 0 C 1090 400 1190 700 1140 1000",
  "M 0 900 C 600 860 1000 940 1600 880",
];

export interface LoginSceneProps {
  phase: LoginPhase;
  reducedMotion: boolean;
}

/**
 * The sign-in backdrop: RAAD's live map, drawn abstractly, with a bus waiting at the stop.
 *
 * Purely decorative (`aria-hidden`) and deliberately free of numbers — no speeds, satellite
 * counts or bus ids — because anything that looks like live telemetry on a page nobody is
 * signed in to would be invented. Every state it shows is also stated in text on the card.
 *
 * Driven entirely by `data-phase`; the CSS module owns every transition.
 */
export function LoginScene({ phase, reducedMotion }: LoginSceneProps) {
  const mapRef = useRef<SVGSVGElement>(null);
  const [hidden, setHidden] = useState(false);

  // A background tab should cost nothing: CSS loops are paused via `data-paused`, and the SMIL
  // marker needs its own pause because CSS does not reach it.
  useEffect(() => {
    const onVisibility = () => {
      const isHidden = document.visibilityState === "hidden";
      setHidden(isHidden);
      const svg = mapRef.current;
      if (svg && typeof svg.pauseAnimations === "function") {
        if (isHidden) svg.pauseAnimations();
        else svg.unpauseAnimations();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  return (
    <div
      className={styles.scene}
      data-phase={phase}
      data-paused={hidden || undefined}
      aria-hidden="true"
    >
      <svg
        ref={mapRef}
        className={styles.map}
        viewBox="0 0 1600 1000"
        preserveAspectRatio="xMidYMid slice"
        focusable="false"
      >
        <defs>
          <radialGradient id="raad-login-marker-glow">
            <stop offset="0%" stopColor="#1e63ff" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#1e63ff" stopOpacity="0" />
          </radialGradient>
        </defs>

        <g className={styles.roads}>
          {ROADS.map((d) => (
            <path key={d} d={d} />
          ))}
        </g>

        <path id="raad-login-route" className={styles.route} d={ROUTE_PATH} />
        {/* Same geometry again, normalised to length 1 so CSS can dash and draw it. */}
        <path className={styles.routeActivity} d={ROUTE_PATH} pathLength={1} />

        <g className={styles.stops}>
          {ROUTE_STOPS.map(([x, y]) => (
            <circle key={`${x}-${y}`} cx={x} cy={y} r={5} />
          ))}
        </g>

        {!reducedMotion && (
          <g className={styles.marker}>
            <circle r={34} fill="url(#raad-login-marker-glow)" />
            <circle className={styles.markerPulse} r={10} />
            <rect x={-11} y={-5} width={22} height={10} rx={3} className={styles.markerBody} />
            <animateMotion dur="56s" repeatCount="indefinite" rotate="auto">
              <mpath href="#raad-login-route" />
            </animateMotion>
          </g>
        )}
      </svg>

      <div className={styles.horizon} />

      <svg className={styles.bus} viewBox="0 0 640 200" focusable="false">
        <defs>
          <linearGradient id="raad-login-beam" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor="#dbe7ff" stopOpacity="0.5" />
            <stop offset="100%" stopColor="#dbe7ff" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="raad-login-scan" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#60a5fa" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#60a5fa" stopOpacity="0" />
          </linearGradient>
        </defs>

        <g className={styles.vehicle}>
          <polygon className={styles.beam} points="504,126 640,104 640,168 504,140" />

          <path
            className={styles.body}
            d="M60 150 L60 58 Q60 40 78 40 L452 40 Q478 40 486 62 L500 110 Q504 122 504 134 L504 150 Q504 156 498 156 L66 156 Q60 156 60 150 Z"
          />
          <line className={styles.rail} x1={60} y1={112} x2={502} y2={112} />

          <g className={styles.windows}>
            {[80, 130, 180, 230, 280, 330].map((x) => (
              <rect key={x} x={x} y={56} width={42} height={38} rx={5} />
            ))}
            <path d="M432 56 L466 56 Q476 56 480 66 L492 98 L432 98 Z" />
          </g>

          <g className={styles.door}>
            <rect x={384} y={54} width={44} height={100} rx={3} className={styles.doorFrame} />
            <rect x={386} y={56} width={19} height={96} rx={2} className={styles.doorLeafLeft} />
            <rect x={407} y={56} width={19} height={96} rx={2} className={styles.doorLeafRight} />
          </g>

          <rect className={styles.sign} x={440} y={45} width={36} height={6} rx={3} />

          <g className={styles.camera}>
            <polygon className={styles.scan} points="452,34 400,110 500,110" />
            <rect x={444} y={28} width={16} height={9} rx={3} className={styles.cameraBody} />
            <circle className={styles.rec} cx={456} cy={32.5} r={2} />
          </g>

          <rect className={styles.headlight} x={498} y={128} width={7} height={10} rx={2} />
          <rect className={styles.taillight} x={59} y={126} width={5} height={12} rx={2} />
          <circle className={styles.hazard} cx={500} cy={118} r={4.5} />
          <circle className={styles.hazard} cx={63} cy={118} r={4.5} />

          <g className={styles.wheels}>
            {[130, 430].map((cx) => (
              <g key={cx}>
                <circle cx={cx} cy={156} r={20} />
                <circle cx={cx} cy={156} r={6} />
              </g>
            ))}
          </g>
        </g>
      </svg>
    </div>
  );
}
