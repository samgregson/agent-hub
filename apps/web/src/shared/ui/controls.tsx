import { type ButtonHTMLAttributes, type ReactNode } from "react";

import styles from "./controls.module.css";

export function Button({
  children,
  variant = "secondary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  variant?: "danger" | "primary" | "secondary";
}) {
  return (
    <button
      {...props}
      className={`${styles.button} ${styles[variant]} ${props.className ?? ""}`}
    >
      {children}
    </button>
  );
}

export function Field({
  children,
  label,
}: {
  children: ReactNode;
  label: ReactNode;
}) {
  return (
    <label className={styles.field}>
      <span>{label}</span>
      {children}
    </label>
  );
}
