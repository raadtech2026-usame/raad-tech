import React, { useRef } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useForm } from "react-hook-form";
import { describe, expect, it, vi } from "vitest";
import { PhoneInput } from "./PhoneInput";

describe("PhoneInput", () => {
  describe("controlled mode", () => {
    it("strips +252 visually from the controlled value", () => {
      render(<PhoneInput value="+252612345678" onChange={vi.fn()} />);
      const input = screen.getByRole("textbox") as HTMLInputElement;
      expect(input.value).toBe("612345678");
      expect(screen.getByText("+252")).toBeInTheDocument();
    });

    it("calls onChange with normalized E.164 when typing national number", async () => {
      const handleChange = vi.fn();
      render(<PhoneInput value="" onChange={handleChange} />);
      const input = screen.getByPlaceholderText("612345678");

      await userEvent.type(input, "6");
      expect(handleChange).toHaveBeenCalled();
      const lastCall = handleChange.mock.calls[handleChange.mock.calls.length - 1][0];
      expect(lastCall.target.value).toBe("+2526");
    });

    it("normalizes pasted +252 numbers into national display and E.164 onChange", async () => {
      const handleChange = vi.fn();
      render(<PhoneInput onChange={handleChange} />);
      const input = screen.getByRole("textbox") as HTMLInputElement;

      await userEvent.type(input, "+252615551234");
      expect(input.value).toBe("615551234");
      expect(handleChange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          target: expect.objectContaining({ value: "+252615551234" }),
        }),
      );
    });
  });

  describe("forwardRef attachment", () => {
    it("attaches ref directly to the native HTMLInputElement without proxying", () => {
      let refHandle: HTMLInputElement | null = null;
      function TestComponent() {
        const inputRef = useRef<HTMLInputElement | null>(null);
        return (
          <div>
            <PhoneInput
              ref={(node) => {
                inputRef.current = node;
                refHandle = node;
              }}
              defaultValue="612345678"
            />
          </div>
        );
      }

      render(<TestComponent />);
      expect(refHandle).not.toBeNull();
      expect(refHandle).toBeInstanceOf(HTMLInputElement);
      expect(refHandle!.value).toBe("612345678");
    });

    it("allows standard DOM methods such as focus() and blur() without illegal invocation", () => {
      const ref = React.createRef<HTMLInputElement>();
      render(<PhoneInput ref={ref} />);
      expect(typeof ref.current?.focus).toBe("function");
      expect(typeof ref.current?.blur).toBe("function");

      ref.current?.focus();
      expect(document.activeElement).toBe(screen.getByRole("textbox"));
    });
  });

  describe("React Hook Form integration (uncontrolled)", () => {
    interface FormValues {
      phone: string;
    }

    function TestRHFForm({ onSubmit }: { onSubmit: (vals: FormValues) => void }) {
      const { register, handleSubmit } = useForm<FormValues>({
        defaultValues: { phone: "" },
      });

      return (
        <form onSubmit={handleSubmit(onSubmit)}>
          <PhoneInput {...register("phone", { required: true })} />
          <button type="submit">Submit</button>
        </form>
      );
    }

    it("submits E.164 normalized phone number when user inputs national digits", async () => {
      const onSubmit = vi.fn();
      render(<TestRHFForm onSubmit={onSubmit} />);

      const input = screen.getByPlaceholderText("612345678");
      await userEvent.type(input, "612345678");
      await userEvent.click(screen.getByRole("button", { name: "Submit" }));

      expect(onSubmit).toHaveBeenCalledTimes(1);
      expect(onSubmit).toHaveBeenCalledWith(
        { phone: "+252612345678" },
        expect.anything(),
      );
    });

    it("normalizes phone on blur so form state contains E.164 even after tabbing away", async () => {
      const onSubmit = vi.fn();
      render(
        <div>
          <TestRHFForm onSubmit={onSubmit} />
          <input data-testid="outside" />
        </div>,
      );

      const input = screen.getByPlaceholderText("612345678");
      await userEvent.type(input, "612345678");
      await userEvent.click(screen.getByTestId("outside")); // triggers blur
      await userEvent.click(screen.getByRole("button", { name: "Submit" }));

      expect(onSubmit).toHaveBeenCalledTimes(1);
      expect(onSubmit).toHaveBeenCalledWith(
        { phone: "+252612345678" },
        expect.anything(),
      );
    });

    it("handles leading zero stripping e.g. 0612345678", async () => {
      const onSubmit = vi.fn();
      render(<TestRHFForm onSubmit={onSubmit} />);

      const input = screen.getByPlaceholderText("612345678");
      await userEvent.type(input, "0612345678");
      await userEvent.click(screen.getByRole("button", { name: "Submit" }));

      expect(onSubmit).toHaveBeenCalledTimes(1);
      expect(onSubmit).toHaveBeenCalledWith(
        { phone: "+252612345678" },
        expect.anything(),
      );
    });
  });
});
