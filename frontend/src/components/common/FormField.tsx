import React from 'react';

interface FormFieldProps extends React.InputHTMLAttributes<HTMLInputElement | HTMLSelectElement> {
  label: string;
  error?: string;
  as?: 'input' | 'select';
  options?: { label: string; value: string | number }[];
}

export const FormField = React.forwardRef<HTMLInputElement | HTMLSelectElement, FormFieldProps>(
  ({ label, error, as = 'input', options, className = '', ...props }, ref) => {
    const baseInputClass = `input-modern ${
      error ? 'border-rose-400 focus:border-rose-500 focus:ring-rose-500/20' : 'border-slate-200'
    } ${className}`;

    return (
      <div className="mb-4 last:mb-0">
        <label htmlFor={props.id} className="block text-sm font-semibold text-slate-700 mb-1.5 ml-1">
          {label}
        </label>
        {as === 'select' ? (
          <select ref={ref as React.Ref<HTMLSelectElement>} className={baseInputClass} {...(props as React.SelectHTMLAttributes<HTMLSelectElement>)}>
            {options?.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        ) : (
          <input ref={ref as React.Ref<HTMLInputElement>} className={baseInputClass} {...(props as React.InputHTMLAttributes<HTMLInputElement>)} />
        )}
        {error && <p className="mt-1 text-sm text-red-500">{error}</p>}
      </div>
    );
  }
);

FormField.displayName = 'FormField';
