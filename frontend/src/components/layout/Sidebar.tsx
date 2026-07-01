import React from 'react';
import { NavLink } from 'react-router-dom';
import { sidebarNavigation } from '../../utils/navigation';
import { useAuth } from '../../context/AuthContext';
import { ArrowLeftStartOnRectangleIcon } from '@heroicons/react/24/outline';

function classNames(...classes: string[]) {
  return classes.filter(Boolean).join(' ');
}

export const Sidebar: React.FC = () => {
  const { logout, user } = useAuth();

  return (
    <div className="flex grow flex-col gap-y-5 overflow-y-auto border-r border-white/40 bg-white/60 backdrop-blur-xl px-6 pb-4 pt-8 h-full shadow-[4px_0_24px_-12px_rgba(0,0,0,0.1)]">
      <div className="flex h-8 shrink-0 items-center animate-fade-in">
        <h1 className="text-2xl font-extrabold bg-clip-text text-transparent bg-gradient-to-r from-indigo-600 to-purple-600 tracking-tight">
          Smart Timetable
        </h1>
      </div>
      <nav className="flex flex-1 flex-col">
        <ul role="list" className="flex flex-1 flex-col gap-y-7">
          <li>
            <ul role="list" className="-mx-2 space-y-1">
              {sidebarNavigation.map((item) => (
                <li key={item.name}>
                  <NavLink
                    to={item.href}
                    className={({ isActive }) =>
                      classNames(
                        isActive
                          ? 'bg-indigo-50/80 text-indigo-700 shadow-sm border border-indigo-100/50'
                          : 'text-slate-600 hover:bg-white/60 hover:text-indigo-600 border border-transparent',
                        'group flex gap-x-3 rounded-xl p-2.5 text-sm font-semibold leading-6 transition-all duration-200 ease-out hover:-translate-y-px hover:shadow-sm'
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <item.icon
                          className={classNames(
                            isActive ? 'text-indigo-600' : 'text-slate-400 group-hover:text-indigo-500',
                            'h-5 w-5 shrink-0 transition-colors'
                          )}
                          aria-hidden="true"
                        />
                        {item.name}
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </li>
          <li className="mt-auto">
            <div className="flex flex-col gap-y-4">
              <div className="flex items-center gap-x-4 p-2 rounded-xl bg-white/40 border border-white/60 shadow-sm backdrop-blur-sm">
                <div className="h-9 w-9 rounded-full bg-gradient-to-br from-indigo-100 to-purple-100 flex items-center justify-center text-indigo-700 font-bold uppercase shadow-inner">
                  {user?.full_name?.charAt(0) || user?.email?.charAt(0) || 'U'}
                </div>
                <div className="flex flex-col">
                  <span className="text-sm font-bold text-slate-800">{user?.full_name || 'Admin User'}</span>
                  <span className="text-xs font-medium text-slate-500">{user?.role}</span>
                </div>
              </div>
              <button
                onClick={logout}
                className="group flex gap-x-3 rounded-xl p-2.5 -mx-2 text-sm font-semibold leading-6 text-slate-600 hover:bg-white/60 hover:text-indigo-600 transition-all duration-200"
              >
                <ArrowLeftStartOnRectangleIcon
                  className="h-5 w-5 shrink-0 text-slate-400 group-hover:text-indigo-500 transition-colors"
                  aria-hidden="true"
                />
                Logout
              </button>
            </div>
          </li>
        </ul>
      </nav>
    </div>
  );
};
