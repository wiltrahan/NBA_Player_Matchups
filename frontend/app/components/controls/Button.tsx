import type { ButtonHTMLAttributes } from "react";

type ButtonVariant = "primary" | "secondary";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  loading?: boolean;
  variant?: ButtonVariant;
};

function joinClasses(...names: Array<string | undefined | false>): string {
  return names.filter(Boolean).join(" ");
}

export function Button({ loading = false, variant = "secondary", className, children, ...props }: ButtonProps) {
  return (
    <button
      {...props}
      className={joinClasses("button-base", `button-${variant}`, loading && "is-loading", className)}
      aria-busy={loading}
    >
      {loading ? <span className="button-loader" aria-hidden="true" /> : null}
      <span>{children}</span>
    </button>
  );
}
