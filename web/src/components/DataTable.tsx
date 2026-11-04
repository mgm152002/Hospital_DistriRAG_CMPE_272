export interface Column<T> { key: string; header: string; render: (row: T) => React.ReactNode; className?: string }

export function DataTable<T>({ columns, rows, rowKey, caption }:
  { columns: Column<T>[]; rows: T[]; rowKey: (row: T) => string; caption: string }) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-rule bg-card shadow-sm">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-rule bg-rail/40 text-left">
            {columns.map((c) => (
              <th key={c.key} scope="col"
                  className="px-4 py-2.5 text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft first:pl-5 last:pr-5">
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-rule/70">
          {rows.map((row) => (
            <tr key={rowKey(row)} className="group align-middle transition-colors hover:bg-bubble/40">
              {columns.map((c) => <td key={c.key} className={`px-4 py-3 first:pl-5 last:pr-5 ${c.className ?? ""}`}>{c.render(row)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
