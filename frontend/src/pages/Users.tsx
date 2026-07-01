import React, { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { PencilSquareIcon, NoSymbolIcon, CheckCircleIcon, TrashIcon } from '@heroicons/react/24/outline';
import { getUsers, createUser, updateUser, deactivateUser, reactivateUser, deleteUser } from '../services/users';
import type { UserRead, UserCreate, UserUpdate } from '../types/models';
import { DataTable, type Column } from '../components/common/DataTable';
import { Modal } from '../components/common/Modal';
import { PageHeader } from '../components/common/PageHeader';
import { Alert } from '../components/common/Alert';
import { FormField } from '../components/common/FormField';
import { FormActions } from '../components/common/FormActions';

export default function Users() {
  const [users, setUsers] = useState<UserRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<UserRead | null>(null);


  const { register: registerCreate, handleSubmit: handleSubmitCreate, reset: resetCreate, formState: { errors: errorsCreate, isSubmitting: isCreating } } = useForm<UserCreate>();
  const { register: registerEdit, handleSubmit: handleSubmitEdit, reset: resetEdit, formState: { errors: errorsEdit, isSubmitting: isEditing } } = useForm<UserUpdate>();

  const fetchUsers = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await getUsers();
      setUsers(data.items);
    } catch (err: any) {
      console.error(err);
      setError(err.response?.data?.detail || 'Failed to load users.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const onCreate = async (data: UserCreate) => {
    try {
      setError(null);
      await createUser(data);
      setIsCreateModalOpen(false);
      resetCreate();
      fetchUsers();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create user.');
    }
  };

  const onEdit = async (data: UserUpdate) => {
    if (!selectedUser) return;
    try {
      setError(null);
      await updateUser(selectedUser.id, data);
      setIsEditModalOpen(false);
      setSelectedUser(null);
      resetEdit();
      fetchUsers();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to update user.');
    }
  };

  const openEditModal = (user: UserRead) => {
    setSelectedUser(user);
    resetEdit({
      full_name: user.full_name,
      email: user.email
    });
    setIsEditModalOpen(true);
  };

  const handleToggleStatus = async (user: UserRead) => {
    try {
      setError(null);
      if (user.is_active) {
        await deactivateUser(user.id);
      } else {
        await reactivateUser(user.id);
      }
      fetchUsers();
    } catch (err: any) {
      setError(err.response?.data?.detail || `Failed to ${user.is_active ? 'deactivate' : 'reactivate'} user.`);
    }
  };

  const handleDelete = async (user: UserRead) => {
    if (!window.confirm(`Are you sure you want to delete ${user.full_name}? This action cannot be undone.`)) {
      return;
    }
    try {
      setError(null);
      await deleteUser(user.id);
      fetchUsers();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete user.');
    }
  };

  const columns: Column<UserRead>[] = [
    { header: 'Name', accessor: 'full_name' },
    { header: 'Email', accessor: 'email' },
    { 
      header: 'Role', 
      accessor: (row) => (
        <span className="px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
          {row.role}
        </span>
      ) 
    },
    { 
      header: 'Status', 
      accessor: (row) => (
        <span className={`px-2 py-1 rounded-full text-xs font-medium ${row.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
          {row.is_active ? 'Active' : 'Inactive'}
        </span>
      ) 
    },
    {
      header: 'Actions',
      accessor: (row) => (
        <div className="flex items-center space-x-2">
          <button
            onClick={() => openEditModal(row)}
            className="text-blue-500 hover:text-blue-700 transition-colors p-1 rounded hover:bg-blue-50"
            title="Edit User"
          >
            <PencilSquareIcon className="w-5 h-5" />
          </button>
          
          <button
            onClick={() => handleToggleStatus(row)}
            className={`${row.is_active ? 'text-red-500 hover:text-red-700 hover:bg-red-50' : 'text-green-500 hover:text-green-700 hover:bg-green-50'} transition-colors p-1 rounded`}
            title={row.is_active ? 'Deactivate User' : 'Reactivate User'}
          >
            {row.is_active ? <NoSymbolIcon className="w-5 h-5" /> : <CheckCircleIcon className="w-5 h-5" />}
          </button>

          <button
            onClick={() => handleDelete(row)}
            className="text-red-600 hover:text-red-800 transition-colors p-1 rounded hover:bg-red-50"
            title="Delete User"
          >
            <TrashIcon className="w-5 h-5" />
          </button>
        </div>
      )
    }
  ];

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      <PageHeader
        title="Users"
        subtitle="Manage faculty and teaching assistants."
        actionLabel="Add User"
        onAction={() => setIsCreateModalOpen(true)}
      />

      {error && <Alert type="error" message={error} />}

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-1">
        <DataTable<UserRead>
          columns={columns} 
          data={users} 
          keyExtractor={(row) => row.id} 
          isLoading={isLoading} 
          emptyMessage="No users found."
        />
      </div>

      <Modal isOpen={isCreateModalOpen} onClose={() => { setIsCreateModalOpen(false); resetCreate(); }} title="Add New User">
        <form onSubmit={handleSubmitCreate(onCreate)}>
          <FormField
            id="full_name"
            label="Full Name"
            placeholder="e.g., Dr. Alice Smith"
            {...registerCreate('full_name', { required: 'Full name is required', minLength: { value: 2, message: 'Minimum 2 characters' } })}
            error={errorsCreate.full_name?.message as string}
          />
          <FormField
            id="email"
            label="Email"
            type="email"
            placeholder="alice@college.edu"
            {...registerCreate('email', { 
              required: 'Email is required',
              pattern: { value: /^[^\s@]+@[^\s@]+\.[^\s@]+$/, message: 'Invalid email format' }
            })}
            error={errorsCreate.email?.message as string}
          />
          <FormField
            id="role"
            label="Role"
            as="select"
            options={[{ label: 'Faculty', value: 'FACULTY' }, { label: 'Teaching Assistant', value: 'TA' }]}
            {...registerCreate('role', { required: 'Role is required' })}
            error={errorsCreate.role?.message as string}
          />
          <FormField
            id="password"
            label="Initial Password"
            type="password"
            placeholder="Min 8 characters"
            {...registerCreate('password', { 
              required: 'Password is required',
              minLength: { value: 8, message: 'Password must be at least 8 characters' }
            })}
            error={errorsCreate.password?.message as string}
          />
          <FormActions
            onCancel={() => { setIsCreateModalOpen(false); resetCreate(); }}
            isSubmitting={isCreating}
            submitLabel="Create User"
            submittingLabel="Creating..."
          />
        </form>
      </Modal>

      <Modal isOpen={isEditModalOpen} onClose={() => { setIsEditModalOpen(false); setSelectedUser(null); resetEdit(); }} title="Edit User">
        <form onSubmit={handleSubmitEdit(onEdit)}>
          <FormField
            id="edit_full_name"
            label="Full Name"
            {...registerEdit('full_name', { minLength: { value: 2, message: 'Minimum 2 characters' } })}
            error={errorsEdit.full_name?.message as string}
          />
          <FormField
            id="edit_email"
            label="Email"
            type="email"
            {...registerEdit('email', { 
              pattern: { value: /^[^\s@]+@[^\s@]+\.[^\s@]+$/, message: 'Invalid email format' }
            })}
            error={errorsEdit.email?.message as string}
          />
          <FormActions
            onCancel={() => { setIsEditModalOpen(false); setSelectedUser(null); resetEdit(); }}
            isSubmitting={isEditing}
            submitLabel="Save Changes"
            submittingLabel="Saving..."
          />
        </form>
      </Modal>
    </div>
  );
}
