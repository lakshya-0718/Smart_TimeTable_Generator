import React, { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { TrashIcon } from '@heroicons/react/24/outline';
import { getFacultyAvailability, addFacultySlot, deleteFacultySlot } from '../services/facultyAvailability';
import { getUsers } from '../services/users';
import type { UserRead, AvailabilitySlotRead, SlotInput } from '../types/models';
import { DataTable, type Column } from '../components/common/DataTable';
import { Modal } from '../components/common/Modal';
import { ConfirmDeleteModal } from '../components/common/ConfirmDeleteModal';
import { PageHeader } from '../components/common/PageHeader';
import { Alert } from '../components/common/Alert';
import { FormField } from '../components/common/FormField';
import { FormActions } from '../components/common/FormActions';

export default function FacultyAvailability() {
  const [facultyList, setFacultyList] = useState<UserRead[]>([]);
  const [selectedFacultyId, setSelectedFacultyId] = useState<string>('');
  
  const [slots, setSlots] = useState<AvailabilitySlotRead[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<SlotInput>();

  useEffect(() => {
    // Load faculty list on mount
    const loadFaculty = async () => {
      try {
        const data = await getUsers('FACULTY', 0, 200);
        setFacultyList(data.items);
      } catch (err: any) {
        console.error(err);
        setError('Failed to load faculty list.');
      }
    };
    loadFaculty();
  }, []);

  const fetchAvailability = async (userId: string) => {
    if (!userId) {
      setSlots([]);
      return;
    }
    try {
      setIsLoading(true);
      setError(null);
      const data = await getFacultyAvailability(userId);
      setSlots(data.slots);
    } catch (err: any) {
      console.error(err);
      setError(err.response?.data?.detail || 'Failed to load availability slots.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAvailability(selectedFacultyId);
  }, [selectedFacultyId]);

  const onAddSlot = async (data: SlotInput) => {
    if (!selectedFacultyId) return;
    try {
      setError(null);
      await addFacultySlot(selectedFacultyId, {
        day: data.day,
        slot_hour: Number(data.slot_hour)
      });
      setIsModalOpen(false);
      reset();
      fetchAvailability(selectedFacultyId);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to add availability slot.');
    }
  };

  const handleDelete = async () => {
    if (!deleteId || !selectedFacultyId) return;
    try {
      setIsDeleting(true);
      setError(null);
      await deleteFacultySlot(selectedFacultyId, deleteId);
      setDeleteId(null);
      fetchAvailability(selectedFacultyId);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete slot.');
      setDeleteId(null);
    } finally {
      setIsDeleting(false);
    }
  };

  const columns: Column<AvailabilitySlotRead>[] = [
    { header: 'Day', accessor: 'day' },
    { 
      header: 'Time Slot', 
      accessor: (row) => {
        const start = row.slot_hour;
        const end = start + 1;
        // Format e.g., 8:00 AM - 9:00 AM
        const formatHour = (h: number) => {
          const ampm = h >= 12 ? 'PM' : 'AM';
          const hr12 = h % 12 || 12;
          return `${hr12}:00 ${ampm}`;
        };
        return `${formatHour(start)} - ${formatHour(end)}`;
      } 
    },
    {
      header: 'Actions',
      accessor: (row) => (
        <button
          onClick={() => setDeleteId(row.id)}
          className="text-red-500 hover:text-red-700 transition-colors p-1 rounded hover:bg-red-50"
          title="Delete Slot"
        >
          <TrashIcon className="w-5 h-5" />
        </button>
      )
    }
  ];

  const dayOptions = [
    { label: 'Monday', value: 'MON' },
    { label: 'Tuesday', value: 'TUE' },
    { label: 'Wednesday', value: 'WED' },
    { label: 'Thursday', value: 'THU' },
    { label: 'Friday', value: 'FRI' }
  ];

  const hourOptions = Array.from({ length: 10 }, (_, i) => {
    const start = i + 8;
    const end = start + 1;
    const formatHour = (h: number) => {
      const ampm = h >= 12 ? 'PM' : 'AM';
      const hr12 = h % 12 || 12;
      return `${hr12}:00 ${ampm}`;
    };
    return { label: `${formatHour(start)} - ${formatHour(end)}`, value: start };
  });

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      <PageHeader
        title="Faculty Availability"
        subtitle="Manage unavailable time slots for faculty members."
        actionLabel="Add Unavailable Slot"
        onAction={() => setIsModalOpen(true)}
        isActionDisabled={!selectedFacultyId}
      />

      <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100 flex items-end space-x-4">
        <div className="flex-1 max-w-sm">
          <label htmlFor="facultySelect" className="block text-sm font-medium text-gray-700 mb-1">
            Select Faculty
          </label>
          <select
            id="facultySelect"
            value={selectedFacultyId}
            onChange={(e) => setSelectedFacultyId(e.target.value)}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
          >
            <option value="">-- Choose a faculty member --</option>
            {facultyList.map((f) => (
              <option key={f.id} value={f.id}>
                {f.full_name} ({f.email})
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <Alert type="error" message={error} />}

      {!selectedFacultyId && (
        <Alert type="info" message="Please select a faculty member to view and manage their availability." />
      )}

      {selectedFacultyId && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-1">
          <DataTable<AvailabilitySlotRead>
            columns={columns} 
            data={slots} 
            keyExtractor={(row) => row.id} 
            isLoading={isLoading} 
            emptyMessage="This faculty member is available for all slots."
          />
        </div>
      )}

      <Modal isOpen={isModalOpen} onClose={() => { setIsModalOpen(false); reset(); }} title="Add Unavailable Slot">
        <form onSubmit={handleSubmit(onAddSlot)}>
          <FormField
            id="day"
            label="Day of Week"
            as="select"
            options={dayOptions}
            {...register('day', { required: 'Day is required' })}
            error={errors.day?.message as string}
          />

          <FormField
            id="slot_hour"
            label="Time Slot"
            as="select"
            options={hourOptions}
            {...register('slot_hour', { required: 'Time slot is required' })}
            error={errors.slot_hour?.message as string}
          />

          <FormActions
            onCancel={() => { setIsModalOpen(false); reset(); }}
            isSubmitting={isSubmitting}
            submitLabel="Block Slot"
            submittingLabel="Blocking..."
          />
        </form>
      </Modal>

      <ConfirmDeleteModal
        isOpen={!!deleteId}
        onClose={() => setDeleteId(null)}
        onConfirm={handleDelete}
        isDeleting={isDeleting}
        title="Remove Blocked Slot"
      />
    </div>
  );
}
