import React, { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { XMarkIcon } from '@heroicons/react/24/outline';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}

export const Modal: React.FC<ModalProps> = ({ isOpen, onClose, title, children }) => {
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (isOpen) {
      document.addEventListener('keydown', handleEscape);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = 'unset';
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const modalContent = (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-md transition-opacity animate-fade-in">
      <div 
        ref={modalRef}
        className="glass-panel w-full max-w-lg overflow-hidden transform transition-all animate-scale-in shadow-[0_20px_60px_-15px_rgba(0,0,0,0.2)] border border-white/60 bg-white/90"
      >
        <div className="flex items-center justify-between px-6 py-5 border-b border-slate-100 bg-white/50">
          <h3 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-slate-900 to-slate-700">{title}</h3>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-rose-500 transition-colors p-1.5 rounded-full hover:bg-rose-50 focus:outline-none focus:ring-2 focus:ring-rose-500/20"
          >
            <XMarkIcon className="w-5 h-5" />
          </button>
        </div>
        <div className="p-6">
          {children}
        </div>
      </div>
    </div>
  );

  return typeof document !== 'undefined' ? createPortal(modalContent, document.body) : null;
};
