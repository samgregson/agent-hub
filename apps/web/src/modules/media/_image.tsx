import styles from "./media.module.css";

export function ImageOutputPreview({
  src,
  altText,
  title,
}: {
  src: string;
  altText: string;
  title?: string;
}) {
  return (
    <figure className={styles.preview}>
      {title ? <figcaption>{title}</figcaption> : null}
      <a
        href={src}
        target="_blank"
        rel="noreferrer"
        aria-label="Open image in a new tab"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt={altText} loading="lazy" />
      </a>
      {altText ? (
        <figcaption className={styles.caption}>{altText}</figcaption>
      ) : null}
    </figure>
  );
}
