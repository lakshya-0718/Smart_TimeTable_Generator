import React from 'react';

export interface Column<T> {
  header: string;
  accessor: keyof T | ((row: T) => React.ReactNode);
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  keyExtractor: (row: T) => string;
  isLoading?: boolean;
  emptyMessage?: string;
}

export function DataTable<T>({ columns, data, keyExtractor, isLoading, emptyMessage = 'No data available' }: DataTableProps<T>) {
  if (isLoading) {
    return (
      <div className="animate-pulse space-y-4 w-full glass-panel p-6">
        <div className="h-12 bg-indigo-50/50 rounded-xl w-full"></div>
        <div className="h-12 bg-slate-50/50 rounded-xl w-full"></div>
        <div className="h-12 bg-slate-50/50 rounded-xl w-full"></div>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="p-12 text-center text-slate-500 glass-panel flex flex-col items-center justify-center animate-fade-in">
        <div className="bg-slate-50 p-4 rounded-full mb-4">
          <svg className="w-8 h-8 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
          </svg>
        </div>
        <p className="font-medium text-lg">{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto glass-panel animate-fade-in">
      <table className="min-w-full divide-y divide-slate-100">
        <thead className="bg-slate-50/50 backdrop-blur-md">
          <tr>
            {columns.map((col, idx) => (
              <th
                key={idx}
                scope="col"
                className="px-6 py-4 text-left text-xs font-bold text-slate-500 uppercase tracking-widest border-b border-slate-100"
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-transparent divide-y divide-slate-50">
          {data.map((row) => (
            <tr key={keyExtractor(row)} className="table-row-hover">
              {columns.map((col, idx) => (
                <td key={idx} className="px-6 py-4 whitespace-nowrap text-sm text-slate-700 font-medium group">
                  {typeof col.accessor === 'function' ? col.accessor(row) : (row[col.accessor] as React.ReactNode)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
