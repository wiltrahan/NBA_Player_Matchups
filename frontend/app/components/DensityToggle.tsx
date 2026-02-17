"use client";

type Density = "comfortable" | "compact";

type DensityToggleProps = {
  value: Density;
  onChange: (value: Density) => void;
};

export function DensityToggle({ value, onChange }: DensityToggleProps) {
  return (
    <div className="density-toggle" role="group" aria-label="Table density">
      <button
        type="button"
        className={value === "comfortable" ? "density-option active" : "density-option"}
        onClick={() => onChange("comfortable")}
      >
        Comfortable
      </button>
      <button
        type="button"
        className={value === "compact" ? "density-option active" : "density-option"}
        onClick={() => onChange("compact")}
      >
        Compact
      </button>
    </div>
  );
}
