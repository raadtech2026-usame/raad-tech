import {
  forwardRef,
  useRef,
  useImperativeHandle,
  useEffect,
  type InputHTMLAttributes,
  type ChangeEvent,
  type FocusEvent,
} from "react";
import clsx from "clsx";
import { Input } from "./Input";
import styles from "./PhoneInput.module.css";

export interface PhoneInputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> {
  value?: string;
  onChange?: (e: ChangeEvent<HTMLInputElement>) => void;
  onBlur?: (e: FocusEvent<HTMLInputElement>) => void;
  invalid?: boolean;
}

/**
 * Normalizes input so any pasted "+252...", "252...", or "0..." is stripped down
 * to the national digits.
 */
function cleanToNational(val?: string | number | readonly string[]): string {
  if (val === undefined || val === null) return "";
  let s = String(val).trim();
  if (s.startsWith("+252")) {
    s = s.slice(4);
  } else if (s.startsWith("252")) {
    s = s.slice(3);
  } else if (s.startsWith("0")) {
    s = s.replace(/^0+/, "");
  }
  return s;
}

function toE164(national: string): string {
  const clean = cleanToNational(national);
  if (!clean) return "";
  return clean.startsWith("+") ? clean : `+252${clean}`;
}

export const PhoneInput = forwardRef<HTMLInputElement, PhoneInputProps>(
  function PhoneInput(
    { value, onChange, onBlur, invalid, className, placeholder = "612345678", ...rest },
    ref,
  ) {
    const inputRef = useRef<HTMLInputElement | null>(null);

    useImperativeHandle(ref, () => {
      const el = inputRef.current;
      if (!el) return {} as HTMLInputElement;
      return new Proxy(el, {
        get(target, prop, receiver) {
          if (prop === "value") {
            return toE164(target.value);
          }
          const val = Reflect.get(target, prop, receiver);
          return typeof val === "function" ? val.bind(target) : val;
        },
        set(target, prop, val, receiver) {
          if (prop === "value") {
            target.value = cleanToNational(val);
            return true;
          }
          return Reflect.set(target, prop, val, receiver);
        },
      });
    });

    // If an external reset() or default value set an E.164 string on the DOM element directly,
    // ensure the displayed text in the input box is the national number.
    useEffect(() => {
      if (inputRef.current) {
        const raw = inputRef.current.value;
        if (raw.startsWith("+252") || raw.startsWith("252") || raw.startsWith("0")) {
          inputRef.current.value = cleanToNational(raw);
        }
      }
    });

    const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
      const raw = e.target.value;
      const national = cleanToNational(raw);

      // Keep the input visually displaying the national digits
      if (e.target.value !== national && (raw.includes("+") || raw.startsWith("0") || raw.startsWith("252"))) {
        e.target.value = national;
      }

      if (onChange) {
        const e164 = toE164(national);
        const synthetic = {
          ...e,
          target: {
            ...e.target,
            name: e.target.name,
            value: e164,
          },
          currentTarget: {
            ...e.currentTarget,
            name: e.currentTarget?.name,
            value: e164,
          },
        };
        onChange(synthetic as unknown as ChangeEvent<HTMLInputElement>);
      }
    };

    const handleBlur = (e: FocusEvent<HTMLInputElement>) => {
      if (onBlur) {
        const raw = e.target.value;
        const e164 = toE164(raw);
        const synthetic = {
          ...e,
          target: {
            ...e.target,
            name: e.target.name,
            value: e164,
          },
          currentTarget: {
            ...e.currentTarget,
            name: e.currentTarget?.name,
            value: e164,
          },
        };
        onBlur(synthetic as unknown as FocusEvent<HTMLInputElement>);
      }
    };

    return (
      <div className={clsx(styles.container, className)}>
        <span className={styles.prefix} aria-hidden="true">
          +252
        </span>
        <Input
          ref={inputRef}
          type="tel"
          className={styles.input}
          invalid={invalid}
          value={value !== undefined ? cleanToNational(value) : undefined}
          onChange={handleChange}
          onBlur={handleBlur}
          placeholder={placeholder}
          {...rest}
        />
      </div>
    );
  },
);
