import React, { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { TrashIcon } from '@heroicons/react/24/outline';
import { getSemesters, createSemester, setActiveSemester, deleteSemester } from '../services/semesters';
import type { Semester, SemesterCreate } from '../types/models';
import { DataTable, type Column } from '../components/common/DataTable';
import { Modal } from '../components/common/Modal';
import { ConfirmDeleteModal } from '../components/common/ConfirmDeleteModal';
import { PageHeader } from '../components/common/PageHeader';
import { Alert } from '../components/common/Alert';
import { FormField } from '../components/common/FormField';
import { FormActions } from '../components/common/FormActions';

interface SemesterFormData extends SemesterCreate {
  start_date: string;
  end_date: string;
}

export default function Semesters() {
  const [semesters, setSemesters] = useState<Semester[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const { register, handleSubmit, reset, watch, formState: { errors, isSubmitting } } = useForm<SemesterFormData>();

  const startDate = watch('start_date');

  const fetchSemesters = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await getSemesters();
      setSemesters(data);
    } catch (err: any) {
      console.error(err);
      setError(err.response?.data?.detail || 'Failed to load semesters.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSemesters();
  }, []);

  const onSubmit = async (data: SemesterFormData) => {
    try {
      setError(null);
      // We explicitly pass only what the backend requires, while satisfying UI validation
      await createSemester({ name: data.name });
      setIsModalOpen(false);
      reset();
      fetchSemesters();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create semester.');
    }
  };

  const handleSetActive = async (id: string) => {
    try {
      await setActiveSemester(id);
      fetchSemesters();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to set active semester.');
    }
  };

  const handleDelete = async () => {
    if (!deleteId) return;
    try {
      setIsDeleting(true);
      setError(null);
      await deleteSemester(deleteId);
      setDeleteId(null);
      fetchSemesters();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete semester. Ensure it is not active.');
      setDeleteId(null);
    } finally {
      setIsDeleting(false);
    }
  };

  const columns: Column<Semester>[] = [
    { header: 'Name', accessor: 'name' },
    { 
      header: 'Status', 
      accessor: (row) => (
        <span className={`px-2 py-1 rounded-full text-xs font-medium ${row.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'}`}>
          {row.is_active ? 'Active' : 'Inactive'}
        </span>
      ) 
    },
    { 
      header: 'Created At', 
      accessor: (row) => new Date(row.created_at).toLocaleDateString() 
    },
    {
      header: 'Actions',
      accessor: (row) => (
        <div className="flex items-center space-x-3">
          <button
            onClick={() => handleSetActive(row.id)}
            disabled={row.is_active}
            className={`text-sm font-medium ${row.is_active ? 'text-gray-400 cursor-not-allowed' : 'text-indigo-600 hover:text-indigo-800'}`}
          >
            {row.is_active ? 'Current' : 'Set Active'}
          </button>
          {!row.is_active && (
            <button
              onClick={() => setDeleteId(row.id)}
              className="text-red-500 hover:text-red-700 transition-colors p-1 rounded hover:bg-red-50"
              title="Delete Semester"
            >
              <TrashIcon className="w-5 h-5" />
            </button>
          )}
        </div>
      )
    }
  ];

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      <PageHeader
        title="Semesters"
        subtitle="Manage academic terms and select the active semester."
        actionLabel="Add Semester"
        onAction={() => setIsModalOpen(true)}
      />

      {error && <Alert type="error" message={error} />}

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-1">
        <DataTable<Semester>
          columns={columns} 
          data={semesters} 
          keyExtractor={(row) => row.id} 
          isLoading={isLoading} 
          emptyMessage="No semesters found. Create one to get started."
        />
      </div>

      <Modal isOpen={isModalOpen} onClose={() => { setIsModalOpen(false); reset(); }} title="Add New Semester">
        <form onSubmit={handleSubmit(onSubmit)}>
          <FormField
            id="name"
            label="Semester Name"
            placeholder="e.g., 2024-25 Odd Sem"
            {...register('name', { required: 'Semester name is required' })}
            error={errors.name?.message as string}
          />

          <div className="grid grid-cols-2 gap-4">
            <FormField
              id="start_date"
              label="Start Date"
              type="date"
              {...register('start_date', { required: 'Start date is required' })}
              error={errors.start_date?.message as string}
            />
            <FormField
              id="end_date"
              label="End Date"
              type="date"
              {...register('end_date', { 
                required: 'End date is required',
                validate: value => !startDate || new Date(value) > new Date(startDate) || 'End date must be after start date'
              })}
              error={errors.end_date?.message as string}
            />
          </div>

          <FormActions
            onCancel={() => { setIsModalOpen(false); reset(); }}
            isSubmitting={isSubmitting}
            submitLabel="Create Semester"
            submittingLabel="Creating..."
          />
        </form>
      </Modal>

      <ConfirmDeleteModal
        isOpen={!!deleteId}
        onClose={() => setDeleteId(null)}
        onConfirm={handleDelete}
        isDeleting={isDeleting}
        title="Delete Semester"
      />
    </div>
  );
}
