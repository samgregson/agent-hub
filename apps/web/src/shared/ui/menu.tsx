"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import styles from "./menu.module.css";

export function Menu({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function closeWhenFocusLeaves(event: FocusEvent) {
      if (!root.current?.contains(event.relatedTarget as Node | null)) {
        setIsOpen(false);
      }
    }

    const element = root.current;
    element?.addEventListener("focusout", closeWhenFocusLeaves);
    return () => element?.removeEventListener("focusout", closeWhenFocusLeaves);
  }, []);

  return (
    <div className={styles.root} ref={root}>
      <button
        aria-expanded={isOpen}
        aria-haspopup="menu"
        aria-label={label}
        className={styles.trigger}
        onClick={() => setIsOpen((open) => !open)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setIsOpen(false);
        }}
        type="button"
      >
        <span aria-hidden="true">•••</span>
      </button>
      {isOpen ? (
        <div aria-label={label} className={styles.content} role="menu">
          {children}
        </div>
      ) : null}
    </div>
  );
}

export function MenuItem({
  children,
  destructive = false,
  onSelect,
}: {
  children: ReactNode;
  destructive?: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      className={destructive ? styles.destructiveItem : styles.item}
      onClick={onSelect}
      role="menuitem"
      type="button"
    >
      {children}
    </button>
  );
}
