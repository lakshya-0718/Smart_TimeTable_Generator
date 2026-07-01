import apiClient from '../api/client';
import type { UserRead, UserCreate, UserUpdate, UserListResponse, UserRole } from '../types/models';

export const getUsers = async (role?: UserRole, skip = 0, limit = 100): Promise<UserListResponse> => {
  const params: any = { skip, limit };
  if (role) {
    params.role = role;
  }
  const { data } = await apiClient.get('/users', { params });
  return data;
};

export const getUser = async (id: string): Promise<UserRead> => {
  const { data } = await apiClient.get(`/users/${id}`);
  return data;
};

export const createUser = async (payload: UserCreate): Promise<UserRead> => {
  const { data } = await apiClient.post('/users', payload);
  return data;
};

export const updateUser = async (id: string, payload: UserUpdate): Promise<UserRead> => {
  const { data } = await apiClient.patch(`/users/${id}`, payload);
  return data;
};

export const deactivateUser = async (id: string): Promise<UserRead> => {
  const { data } = await apiClient.post(`/users/${id}/deactivate`);
  return data;
};

export const reactivateUser = async (id: string): Promise<UserRead> => {
  const { data } = await apiClient.post(`/users/${id}/reactivate`);
  return data;
};

export const deleteUser = async (id: string): Promise<void> => {
  await apiClient.delete(`/users/${id}`);
};
