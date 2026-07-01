import React from 'react';

interface AlertProps {
  type: 'error' | 'warning' | 'info';
  message: string;
}

export const Alert: React.FC<AlertProps> = ({ type, message }) => {
  const styles = {
    error: 'bg-red-50 text-red-600 border-red-100',
    warning: 'bg-yellow-50 text-yellow-800 border-yellow-200',
    info: 'bg-blue-50 text-blue-800 border-blue-200'
  };

  return (
    <div className={`p-4 rounded-lg border flex items-center ${styles[type]}`}>
      <span className="block sm:inline">{message}</span>
    </div>
  );
};
