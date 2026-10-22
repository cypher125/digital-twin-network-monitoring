"use client";

import { useMemo, useState, type ReactNode } from "react";
import { cx } from "./ui";

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** value used for sorting; leave out for an unsortable column */
  sort?: (row: T) => number | string | null | undefined;
  numeric?: boolean;
  className?: string;
}

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  initialSort,
  empty = "Nothing to show.",
  maxHeight,
  caption,
  onRowClick,
  dense,
}: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string | number;
  initialSort?: { key: string; desc?: boolean };
  empty?: ReactNode;
  maxHeight?: number;
  caption?: string;
  onRowClick?: (row: T) => void;
  dense?: boolean;
}) {
  const [sort, setSort] = useState(initialSort ?? null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((c) => c.key === sort.key);
    if (!column?.sort) return rows;
    const value = column.sort;
    return [...rows].sort((a, b) => {
      const x = value(a);
      const y = value(b);
      if (x == null && y == null) return 0;
      if (x == null) return 1; // empty values last either way
      if (y == null) return -1;
      const order = x < y ? -1 : x > y ? 1 : 0;
      return sort.desc ? -order : order;
    });
  }, [rows, columns, sort]);

  return (
    <div className="overflow-auto" style={maxHeight ? { maxHeight } : undefined}>
      <table className="w-full border-collapse text-sm">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead className="sticky top-0 z-10 bg-surface">
          <tr className="border-b border-line">
            {columns.map((column) => {
              const active = sort?.key === column.key;
              return (
                <th
                  key={column.key}
                  scope="col"
                  aria-sort={active ? (sort?.desc ? "descending" : "ascending") : undefined}
                  className={cx(
                    "whitespace-nowrap px-2 py-2 text-xs font-medium text-ink-2",
                    column.numeric ? "text-right" : "text-left",
                    column.className,
                  )}
                >
                  {column.sort ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 hover:text-ink"
                      onClick={() =>
                        setSort((current) =>
                          current?.key === column.key ? { key: column.key, desc: !current.desc } : { key: column.key, desc: !!column.numeric },
                        )
                      }
                    >
                      {column.header}
                      <span aria-hidden className={active ? "text-ink" : "text-muted"}>
                        {active ? (sort?.desc ? "↓" : "↑") : "↕"}
                      </span>
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-2 py-6 text-center text-ink-2">
                {empty}
              </td>
            </tr>
          ) : (
            sorted.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cx("border-b border-line last:border-0", onRowClick && "cursor-pointer hover:bg-surface-2")}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cx(
                      "px-2 align-middle text-ink",
                      dense ? "py-1" : "py-1.5",
                      column.numeric && "num text-right",
                      column.className,
                    )}
                  >
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
