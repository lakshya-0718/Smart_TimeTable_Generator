import React, { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { TrashIcon } from '@heroicons/react/24/outline';
import { getRooms, createRoom, deleteRoom } from '../services/rooms';
import type { Room, RoomCreate } from '../types/models';
import { DataTable, type Column } from '../components/common/DataTable';
import { Modal } from '../components/common/Modal';
import { ConfirmDeleteModal } from '../components/common/ConfirmDeleteModal';
import { PageHeader } from '../components/common/PageHeader';
import { Alert } from '../components/common/Alert';
import { FormField } from '../components/common/FormField';
import { FormActions } from '../components/common/FormActions';

export default function Rooms() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<RoomCreate>();

  const fetchRooms = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await getRooms();
      setRooms(data);
    } catch (err: any) {
      console.error(err);
      setError(err.response?.data?.detail || 'Failed to load rooms.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchRooms();
  }, []);

  const onSubmit = async (data: RoomCreate) => {
    try {
      setError(null);
      await createRoom({
        ...data,
        capacity: Number(data.capacity)
      });
      setIsModalOpen(false);
      reset();
      fetchRooms();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create room.');
    }
  };

  const handleDelete = async () => {
    if (!deleteId) return;
    try {
      setIsDeleting(true);
      setError(null);
      await deleteRoom(deleteId);
      setDeleteId(null);
      fetchRooms();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete room. It might be in use.');
      setDeleteId(null);
    } finally {
      setIsDeleting(false);
    }
  };

  const columns: Column<Room>[] = [
    { header: 'Room Name', accessor: 'name' },
    { 
      header: 'Type', 
      accessor: (row) => (
        <span className={`px-2 py-1 rounded-full text-xs font-medium ${row.room_type === 'LAB' ? 'bg-purple-100 text-purple-800' : 'bg-blue-100 text-blue-800'}`}>
          {row.room_type.replace('_', ' ')}
        </span>
      ) 
    },
    { header: 'Capacity', accessor: 'capacity' },
    {
      header: 'Actions',
      accessor: (row) => (
        <button
          onClick={() => setDeleteId(row.id)}
          className="text-red-500 hover:text-red-700 transition-colors p-1 rounded hover:bg-red-50"
          title="Delete Room"
        >
          <TrashIcon className="w-5 h-5" />
        </button>
      )
    }
  ];

  const roomTypeOptions = [
    { label: 'Lecture Hall', value: 'LECTURE_HALL' },
    { label: 'Lab', value: 'LAB' }
  ];

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      <PageHeader
        title="Rooms"
        subtitle="Manage lecture halls and labs available for scheduling."
        actionLabel="Add Room"
        onAction={() => setIsModalOpen(true)}
      />

      {error && <Alert type="error" message={error} />}

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-1">
        <DataTable<Room> 
          columns={columns} 
          data={rooms} 
          keyExtractor={(row) => row.id} 
          isLoading={isLoading} 
          emptyMessage="No rooms found. Add a new room to get started."
        />
      </div>

      <Modal isOpen={isModalOpen} onClose={() => { setIsModalOpen(false); reset(); }} title="Add New Room">
        <form onSubmit={handleSubmit(onSubmit)}>
          <FormField
            id="name"
            label="Room Name"
            placeholder="e.g., LH-101"
            {...register('name', { required: 'Room name is required' })}
            error={errors.name?.message as string}
          />

          <FormField
            id="room_type"
            label="Room Type"
            as="select"
            options={roomTypeOptions}
            {...register('room_type', { required: 'Room type is required' })}
            error={errors.room_type?.message as string}
          />

          <FormField
            id="capacity"
            label="Capacity"
            type="number"
            placeholder="e.g., 60"
            {...register('capacity', { 
              required: 'Capacity is required',
              min: { value: 1, message: 'Capacity must be greater than zero' }
            })}
            error={errors.capacity?.message as string}
          />

          <FormActions
            onCancel={() => { setIsModalOpen(false); reset(); }}
            isSubmitting={isSubmitting}
            submitLabel="Add Room"
            submittingLabel="Adding..."
          />
        </form>
      </Modal>

      <ConfirmDeleteModal
        isOpen={!!deleteId}
        onClose={() => setDeleteId(null)}
        onConfirm={handleDelete}
        isDeleting={isDeleting}
        title="Delete Room"
      />
    </div>
  );
}
