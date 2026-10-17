import {
  datasetColumnText,
  datasetColumns,
  type DatasetTableRecord,
  scalarText,
} from "./_table";
import styles from "./dataset.module.css";

function DatasetValue({
  value,
  depth = 0,
}: {
  value: unknown;
  depth?: number;
}) {
  const scalar = scalarText(value);
  if (scalar !== null) return <span>{scalar}</span>;
  if (depth >= 8) return <span>Additional nested data</span>;
  if (Array.isArray(value)) {
    return value.length ? (
      <ol className={styles.datasetValueList}>
        {value.map((item, index) => (
          <li key={index}>
            <DatasetValue depth={depth + 1} value={item} />
          </li>
        ))}
      </ol>
    ) : (
      <span>Empty list</span>
    );
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value);
    return entries.length ? (
      <dl className={styles.datasetValueDetails}>
        {entries.map(([key, item]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>
              <DatasetValue depth={depth + 1} value={item} />
            </dd>
          </div>
        ))}
      </dl>
    ) : (
      <span>Empty object</span>
    );
  }
  return <span>—</span>;
}

export function DatasetRecordsTable({
  records,
  ariaLabel = "Dataset records",
}: {
  records: readonly DatasetTableRecord[];
  ariaLabel?: string;
}) {
  const columns = datasetColumns(records);
  return (
    <div
      aria-label={ariaLabel}
      className={styles.datasetTableWrap}
      role="region"
      tabIndex={0}
    >
      <table className={styles.datasetTable}>
        <thead>
          <tr>
            <th scope="col">Order</th>
            <th scope="col">Record</th>
            {columns.map((column) => (
              <th key={column.id} scope="col">
                {column.label}
              </th>
            ))}
            <th scope="col">Details</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => (
            <tr key={`${record.id}-${record.position}`}>
              <td>{record.position + 1}</td>
              <td>
                <strong>{record.sourceKey ?? record.id}</strong>
              </td>
              {columns.map((column) => (
                <td key={column.id}>
                  {datasetColumnText(record.value, column) ?? "—"}
                </td>
              ))}
              <td>
                <details className={styles.datasetRecordDetails}>
                  <summary>Inspect record</summary>
                  <DatasetValue value={record.value} />
                </details>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {records.length === 0 ? <p>No Records to display.</p> : null}
    </div>
  );
}
