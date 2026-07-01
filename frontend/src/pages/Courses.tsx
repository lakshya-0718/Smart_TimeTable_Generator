import React, { useState, useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { TrashIcon } from '@heroicons/react/24/outline';
import { getCourses, createCourse, deleteCourse } from '../services/courses';
import { getSemesters } from '../services/semesters';
import type { Course, CourseCreate, Semester } from '../types/models';
import { DataTable, type Column } from '../components/common/DataTable';
import { Modal } from '../components/common/Modal';
import { ConfirmDeleteModal } from '../components/common/ConfirmDeleteModal';
import { PageHeader } from '../components/common/PageHeader';
import { Alert } from '../components/common/Alert';
import { FormField } from '../components/common/FormField';
import { FormActions } from '../components/common/FormActions';

export default function Courses() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [semesters, setSemesters] = useState<Semester[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const activeSemester = useMemo(() => semesters.find(s => s.is_active), [semesters]);

  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<CourseCreate>();

  const fetchData = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const sems = await getSemesters();
      setSemesters(sems);
      const active = sems.find(s => s.is_active);
      if (active) {
        const data = await getCourses(active.id);
        setCourses(data.items);
      } else {
        setCourses([]);
      }
    } catch (err: any) {
      console.error(err);
      setError(err.response?.data?.detail || 'Failed to load courses.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const onSubmit = async (data: CourseCreate) => {
    if (!activeSemester) return;
    try {
      setError(null);
      await createCourse({
        ...data,
        semester_id: activeSemester.id
      });
      setIsModalOpen(false);
      reset();
      fetchData();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create course.');
    }
  };

  const handleDelete = async () => {
    if (!deleteId) return;
    try {
      setIsDeleting(true);
      setError(null);
      await deleteCourse(deleteId);
      setDeleteId(null);
      fetchData();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete course.');
      setDeleteId(null);
    } finally {
      setIsDeleting(false);
    }
  };

  const columns: Column<Course>[] = [
    { header: 'Code', accessor: 'code' },
    { header: 'Course Name', accessor: 'name' },
    { 
      header: 'Tier / Pattern', 
      accessor: (row) => {
        const labels: Record<string, string> = {
          'TIER_1': '4 Credit (3L+1T+1P)',
          'TIER_2': '3 Credit (3L+1T)',
          'TIER_3': '2 Credit (4hr Lab Only)',
          'TIER_4': '1 Credit (2hr Lab Only)'
        };
        return (
          <span className="px-2 py-1 rounded-full text-xs font-medium bg-indigo-100 text-indigo-800">
            {labels[row.tier] || row.tier}
          </span>
        );
      } 
    },
    {
      header: 'Actions',
      accessor: (row) => (
        <button
          onClick={() => setDeleteId(row.id)}
          className="text-red-500 hover:text-red-700 transition-colors p-1 rounded hover:bg-red-50"
          title="Delete Course"
        >
          <TrashIcon className="w-5 h-5" />
        </button>
      )
    }
  ];

  const tierOptions = [
    { label: 'Tier 1 - 4 Credit (3L+1T+1P)', value: 'TIER_1' },
    { label: 'Tier 2 - 3 Credit (3L+1T)', value: 'TIER_2' },
    { label: 'Tier 3 - 2 Credit (4hr Lab Only)', value: 'TIER_3' },
    { label: 'Tier 4 - 1 Credit (2hr Lab Only)', value: 'TIER_4' }
  ];

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      <PageHeader
        title="Courses"
        subtitle={activeSemester ? `Managing courses for ${activeSemester.name}` : 'No active semester selected.'}
        actionLabel="Add Course"
        onAction={() => setIsModalOpen(true)}
        isActionDisabled={!activeSemester}
      />

      {error && <Alert type="error" message={error} />}
      
      {!activeSemester && !isLoading && (
        <Alert type="warning" message="Please set an active semester in the Semesters page first before adding courses." />
      )}

      {activeSemester && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-1">
          <DataTable<Course> 
            columns={columns} 
            data={courses} 
            keyExtractor={(row) => row.id} 
            isLoading={isLoading} 
            emptyMessage={`No courses found for ${activeSemester.name}.`}
          />
        </div>
      )}

      <Modal isOpen={isModalOpen} onClose={() => { setIsModalOpen(false); reset(); }} title="Add New Course">
        <form onSubmit={handleSubmit(onSubmit)}>
          <FormField
            id="code"
            label="Course Code"
            placeholder="e.g., CS301"
            className="uppercase"
            {...register('code', { required: 'Course code is required' })}
            error={errors.code?.message as string}
          />

          <FormField
            id="name"
            label="Course Name"
            placeholder="e.g., Data Structures"
            {...register('name', { required: 'Course name is required' })}
            error={errors.name?.message as string}
          />

          <FormField
            id="tier"
            label="Credit Pattern (Tier)"
            as="select"
            options={tierOptions}
            {...register('tier', { required: 'Pattern is required' })}
            error={errors.tier?.message as string}
          />

          <FormActions
            onCancel={() => { setIsModalOpen(false); reset(); }}
            isSubmitting={isSubmitting}
            submitLabel="Add Course"
            submittingLabel="Adding..."
          />
        </form>
      </Modal>

      <ConfirmDeleteModal
        isOpen={!!deleteId}
        onClose={() => setDeleteId(null)}
        onConfirm={handleDelete}
        isDeleting={isDeleting}
        title="Delete Course"
      />
    </div>
  );
}
