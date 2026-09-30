import { type ReactNode } from "react";

import styles from "./collection.module.css";

export function CollectionItem({
  actions,
  details,
  id,
  openLabel,
  onOpen,
  title,
}: {
  actions?: ReactNode;
  details?: ReactNode;
  id?: string;
  openLabel?: string;
  onOpen?: () => void;
  title: ReactNode;
}) {
  const content = (
    <>
      <span>{title}</span>
      {details ? <small>{details}</small> : null}
    </>
  );

  return (
    <article className={styles.item} id={id} tabIndex={id ? -1 : undefined}>
      {onOpen ? (
        <button
          aria-label={
            openLabel ?? (typeof title === "string" ? title : undefined)
          }
          className={styles.open}
          onClick={onOpen}
          type="button"
        >
          {content}
        </button>
      ) : (
        <div className={styles.content}>{content}</div>
      )}
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </article>
  );
}

export function Collection({ children }: { children: ReactNode }) {
  return <section className={styles.collection}>{children}</section>;
}
