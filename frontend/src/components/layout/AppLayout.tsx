import React from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';

export const AppLayout: React.FC = () => {
  return (
    <div className="flex min-h-screen w-full bg-transparent">
      <div className="hidden lg:flex lg:w-72 lg:flex-col lg:fixed lg:inset-y-0">
        <Sidebar />
      </div>
      
      <div className="flex flex-1 flex-col lg:pl-72 w-full">
        {/* Placeholder for topbar for mobile screens in the future */}
        <div className="sticky top-0 z-40 flex h-16 shrink-0 items-center gap-x-4 border-b border-white/40 bg-white/60 backdrop-blur-lg px-4 shadow-sm sm:gap-x-6 sm:px-6 lg:px-8 lg:hidden">
          <div className="flex flex-1 gap-x-4 self-stretch lg:gap-x-6 items-center animate-fade-in">
            <h1 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-indigo-600 to-purple-600 tracking-tight">
              Smart Timetable
            </h1>
          </div>
        </div>

        <main className="flex-1 py-10 w-full animate-slide-up">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
};
