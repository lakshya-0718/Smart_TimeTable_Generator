import React, { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { PencilSquareIcon, TrashIcon } from '@heroicons/react/24/outline';
import { getSections, createSection, updateSection, deleteSection } from '../services/sections';
import type { SectionRead, SectionCreate, SectionUpdate } from '../types/models';
import { DataTable, type Column } from '../components/common/DataTable';
import { Modal } from '../components/common/Modal';
import { ConfirmDeleteModal } from '../components/common/ConfirmDeleteModal';
import { PageHeader } from '../components/common/PageHeader';
import { Alert } from '../components/common/Alert';
import { FormField } from '../components/common/FormField';
import { FormActions } from '../components/common/FormActions';

export default function Sections() {
  const [sections, setSections] = useState<SectionRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedSection, setSelectedSection] = useState<SectionRead | null>(null);

  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const { register: registerCreate, handleSubmit: handleSubmitCreate, reset: resetCreate, formState: { errors: errorsCreate, isSubmitting: isCreating } } = useForm<SectionCreate>();
  const { register: registerEdit, handleSubmit: handleSubmitEdit, reset: resetEdit, formState: { errors: errorsEdit, isSubmitting: isEditing } } = useForm<SectionUpdate>();

  const fetchSections = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await getSections();
      setSections(data);
    } catch (err: any) {
      console.error(err);
      setError(err.response?.data?.detail || 'Failed to load sections.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSections();
  }, []);

  const onCreate = async (data: SectionCreate) => {
    try {
      setError(null);
      await createSection({
        ...data,
        year: Number(data.year),
        strength: Number(data.strength)
      });
      setIsCreateModalOpen(false);
      resetCreate();
      fetchSections();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create section.');
    }
  };

  const onEdit = async (data: SectionUpdate) => {
    if (!selectedSection) return;
    try {
      setError(null);
      await updateSection(selectedSection.id, {
        strength: Number(data.strength)
      });
      setIsEditModalOpen(false);
      setSelectedSection(null);
      resetEdit();
      fetchSections();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to update section.');
    }
  };

  const openEditModal = (section: SectionRead) => {
    setSelectedSection(section);
    resetEdit({
      strength: section.strength
    });
    setIsEditModalOpen(true);
  };

  const handleDelete = async () => {
    if (!deleteId) return;
    try {
      setIsDeleting(true);
      setError(null);
      await deleteSection(deleteId);
      setDeleteId(null);
      fetchSections();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete section.');
      setDeleteId(null);
    } finally {
      setIsDeleting(false);
    }
  };

  const columns: Column<SectionRead>[] = [
    { header: 'Section Name', accessor: 'name' },
    { header: 'Year', accessor: 'year' },
    { header: 'Label', accessor: 'label' },
    { header: 'Student Strength', accessor: 'strength' },
    {
      header: 'Actions',
      accessor: (row) => (
        <div className="flex items-center space-x-2">
          <button
            onClick={() => openEditModal(row)}
            className="text-blue-500 hover:text-blue-700 transition-colors p-1 rounded hover:bg-blue-50"
            title="Edit Strength"
          >
            <PencilSquareIcon className="w-5 h-5" />
          </button>
          
          <button
            onClick={() => setDeleteId(row.id)}
            className="text-red-500 hover:text-red-700 transition-colors p-1 rounded hover:bg-red-50"
            title="Delete Section"
          >
            <TrashIcon className="w-5 h-5" />
          </button>
        </div>
      )
    }
  ];

  const yearOptions = [
    { label: 'Year 1', value: 1 },
    { label: 'Year 2', value: 2 },
    { label: 'Year 3', value: 3 },
    { label: 'Year 4', value: 4 }
  ];

  const labelOptions = [
    { label: 'A', value: 'A' },
    { label: 'B', value: 'B' }
  ];

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      <PageHeader
        title="Sections"
        subtitle="Manage student cohorts (e.g., Y2A, Y3B) and their strength."
        actionLabel="Add Section"
        onAction={() => setIsCreateModalOpen(true)}
      />

      {error && <Alert type="error" message={error} />}

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-1">
        <DataTable<SectionRead>
          columns={columns} 
          data={sections} 
          keyExtractor={(row) => row.id} 
          isLoading={isLoading} 
          emptyMessage="No sections found."
        />
      </div>

      <Modal isOpen={isCreateModalOpen} onClose={() => { setIsCreateModalOpen(false); resetCreate(); }} title="Add New Section">
        <form onSubmit={handleSubmitCreate(onCreate)}>
          <div className="grid grid-cols-2 gap-4">
            <FormField
              id="year"
              label="Year"
              as="select"
              options={yearOptions}
              {...registerCreate('year', { required: 'Year is required' })}
              error={errorsCreate.year?.message as string}
            />
            <FormField
              id="label"
              label="Label"
              as="select"
              options={labelOptions}
              {...registerCreate('label', { required: 'Label is required' })}
              error={errorsCreate.label?.message as string}
            />
          </div>
          
          <FormField
            id="strength"
            label="Student Strength"
            type="number"
            placeholder="e.g., 60"
            {...registerCreate('strength', { 
              required: 'Strength is required',
              min: { value: 1, message: 'Strength must be greater than 0' }
            })}
            error={errorsCreate.strength?.message as string}
          />
          <FormActions
            onCancel={() => { setIsCreateModalOpen(false); resetCreate(); }}
            isSubmitting={isCreating}
            submitLabel="Create Section"
            submittingLabel="Creating..."
          />
        </form>
      </Modal>

      <Modal isOpen={isEditModalOpen} onClose={() => { setIsEditModalOpen(false); setSelectedSection(null); resetEdit(); }} title={`Edit Section: ${selectedSection?.name || ''}`}>
        <form onSubmit={handleSubmitEdit(onEdit)}>
          <FormField
            id="edit_strength"
            label="Student Strength"
            type="number"
            {...registerEdit('strength', { 
              required: 'Strength is required',
              min: { value: 1, message: 'Strength must be greater than 0' }
            })}
            error={errorsEdit.strength?.message as string}
          />
          <FormActions
            onCancel={() => { setIsEditModalOpen(false); setSelectedSection(null); resetEdit(); }}
            isSubmitting={isEditing}
            submitLabel="Save Changes"
            submittingLabel="Saving..."
          />
        </form>
      </Modal>

      <ConfirmDeleteModal
        isOpen={!!deleteId}
        onClose={() => setDeleteId(null)}
        onConfirm={handleDelete}
        isDeleting={isDeleting}
        title="Delete Section"
      />
    </div>
  );
}
