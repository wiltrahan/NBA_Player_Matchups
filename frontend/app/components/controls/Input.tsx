import type { InputHTMLAttributes, ReactNode } from "react";

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  leadingIcon?: ReactNode;
  trailingControl?: ReactNode;
};

function joinClasses(...names: Array<string | undefined | false>): string {
  return names.filter(Boolean).join(" ");
}

export function Input({ leadingIcon, trailingControl, className, ...props }: InputProps) {
  const hasLeadingIcon = Boolean(leadingIcon);
  const hasTrailingControl = Boolean(trailingControl);

  if (!hasLeadingIcon && !hasTrailingControl) {
    return <input {...props} className={joinClasses("control-input", className)} />;
  }

  return (
    <div className="input-shell">
      {hasLeadingIcon ? <span className="input-icon">{leadingIcon}</span> : null}
      <input
        {...props}
        className={joinClasses(
          "control-input",
          hasLeadingIcon && "control-input-with-leading",
          hasTrailingControl && "control-input-with-trailing",
          className,
        )}
      />
      {hasTrailingControl ? <span className="input-trailing">{trailingControl}</span> : null}
    </div>
  );
}
