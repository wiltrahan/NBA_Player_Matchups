"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

type InjuryTone = "danger" | "warning" | "success";

type InjuryStatusBadgeProps = {
  label: string;
  tone: InjuryTone;
  tooltip: string;
};

type TooltipPosition = {
  top: number;
  left: number;
};

const VIEWPORT_MARGIN = 12;
const GAP = 10;

export function InjuryStatusBadge({ label, tone, tooltip }: InjuryStatusBadgeProps) {
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const closeTimerRef = useRef<number | null>(null);
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<TooltipPosition | null>(null);

  const clearCloseTimer = useCallback(() => {
    if (closeTimerRef.current != null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }, []);

  const closeSoon = useCallback(() => {
    clearCloseTimer();
    closeTimerRef.current = window.setTimeout(() => {
      setOpen(false);
    }, 120);
  }, [clearCloseTimer]);

  const openNow = useCallback(() => {
    clearCloseTimer();
    setOpen(true);
  }, [clearCloseTimer]);

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current;
    const popover = tooltipRef.current;
    if (!trigger || !popover) return;

    const triggerRect = trigger.getBoundingClientRect();
    const tooltipRect = popover.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    let left = triggerRect.right + GAP;
    let top = triggerRect.top + triggerRect.height / 2 - tooltipRect.height / 2;

    if (left + tooltipRect.width > viewportWidth - VIEWPORT_MARGIN) {
      left = triggerRect.left - tooltipRect.width - GAP;
    }
    if (left < VIEWPORT_MARGIN) {
      left = VIEWPORT_MARGIN;
    }

    if (top + tooltipRect.height > viewportHeight - VIEWPORT_MARGIN) {
      top = viewportHeight - tooltipRect.height - VIEWPORT_MARGIN;
    }
    if (top < VIEWPORT_MARGIN) {
      top = VIEWPORT_MARGIN;
    }

    setPosition({ left, top });
  }, []);

  useEffect(() => {
    setMounted(true);
    return () => {
      clearCloseTimer();
    };
  }, [clearCloseTimer]);

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();

    const onViewportChange = () => updatePosition();
    window.addEventListener("resize", onViewportChange);
    window.addEventListener("scroll", onViewportChange, true);
    return () => {
      window.removeEventListener("resize", onViewportChange);
      window.removeEventListener("scroll", onViewportChange, true);
    };
  }, [open, updatePosition]);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`injury-icon injury-icon--${tone}`}
        aria-label={tooltip}
        aria-expanded={open}
        onMouseEnter={openNow}
        onMouseLeave={closeSoon}
        onFocus={openNow}
        onBlur={closeSoon}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          clearCloseTimer();
          setOpen((current) => !current);
        }}
        onKeyDown={(event) => {
          event.stopPropagation();
        }}
      >
        {label}
      </button>

      {mounted && open
        ? createPortal(
            <div
              ref={tooltipRef}
              className="injury-tooltip"
              role="tooltip"
              style={{
                top: position?.top ?? -9999,
                left: position?.left ?? -9999,
              }}
              onMouseEnter={openNow}
              onMouseLeave={closeSoon}
            >
              {tooltip}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
