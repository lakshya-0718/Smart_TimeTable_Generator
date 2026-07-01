import React from 'react';
import { useAuth } from '../context/AuthContext';
import { CheckCircleIcon } from '@heroicons/react/24/solid';

export const Dashboard: React.FC = () => {
  const { user } = useAuth();

  return (
    <div className="bg-white px-6 py-24 sm:py-32 lg:px-8 rounded-lg shadow-sm ring-1 ring-gray-900/5 h-full">
      <div className="mx-auto max-w-2xl text-center">
        <h2 className="text-4xl font-bold tracking-tight text-gray-900 sm:text-6xl">
          Smart Timetable Generator
        </h2>
        <p className="mt-6 text-lg leading-8 text-gray-600">
          Welcome back, {user?.full_name}!
        </p>
        <div className="mt-10 flex items-center justify-center gap-x-2">
          <CheckCircleIcon className="h-6 w-6 text-green-500" />
          <span className="text-sm font-semibold leading-6 text-gray-900">
            Backend Connected
          </span>
        </div>
      </div>
    </div>
  );
};
