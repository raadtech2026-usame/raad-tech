import {
  forwardRef,
  useRef,
  useImperativeHandle,
  useEffect,
  type InputHTMLAttributes,
  type ChangeEvent,
} from "react";
import clsx from "clsx";
import { Input } from "./Input";
import styles from "./PhoneInput.module.css";

export interface PhoneInputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> {
  value?: string;
  onChange?: (e: ChangeEvent<HTMLInputElement>) => void;
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

export const PhoneInput = forwardRef<HTMLInputElement, PhoneInputProps>(
  function PhoneInput(
    { value, onChange, invalid, className, placeholder = "612345678", ...rest },
    ref,
  ) {
    const inputRef = useRef<HTMLInputElement | null>(null);
    useImperativeHandle(ref, () => inputRef.current as HTMLInputElement);

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
        // If national is empty, form receives ""; if national has digits/text, prefix with +252 for E.164
        const e164 = national.length > 0 ? (national.startsWith("+") ? national : `+252${national}`) : "";
        const synthetic = {
          ...e,
          target: {
            ...e.target,
            name: e.target.name,
            value: e164,
          },
        };
        onChange(synthetic as unknown as ChangeEvent<HTMLInputElement>);
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
          placeholder={placeholder}
          {...rest}
        />
      </div>
    );
  },
);
