import type { SelectHTMLAttributes } from "react";

function joinClasses(...names: Array<string | undefined | false>): string {
  return names.filter(Boolean).join(" ");
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...props} className={joinClasses("control-select", className)}>
      {children}
    </select>
  );
}
