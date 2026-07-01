import React from 'react';
import { PlusIcon } from '@heroicons/react/24/outline';

interface PageHeaderProps {
  title: string;
  subtitle: string;
  actionLabel?: string;
  onAction?: () => void;
  isActionDisabled?: boolean;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  subtitle,
  actionLabel,
  onAction,
  isActionDisabled = false
}) => {
  return (
    <div className="flex flex-col sm:flex-row justify-between sm:items-center glass-panel p-6 mb-8 gap-4 animate-fade-in">
      <div>
        <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-slate-900 to-slate-700">{title}</h1>
        <p className="mt-2 text-sm font-medium text-slate-500">{subtitle}</p>
      </div>
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          disabled={isActionDisabled}
          className="btn-premium flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed disabled:transform-none"
        >
          <PlusIcon className="w-5 h-5 mr-2 -ml-1" />
          {actionLabel}
        </button>
      )}
    </div>
  );
};
