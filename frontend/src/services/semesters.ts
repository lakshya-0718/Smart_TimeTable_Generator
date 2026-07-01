import apiClient from '../api/client';
import type { Semester, SemesterCreate, SemesterUpdate } from '../types/models';

export const getSemesters = async (): Promise<Semester[]> => {
  const { data } = await apiClient.get('/semesters');
  return data;
};

export const createSemester = async (payload: SemesterCreate): Promise<Semester> => {
  const { data } = await apiClient.post('/semesters', payload);
  return data;
};

export const updateSemester = async (id: string, payload: SemesterUpdate): Promise<Semester> => {
  const { data } = await apiClient.patch(`/semesters/${id}`, payload);
  return data;
};

export const deleteSemester = async (id: string): Promise<void> => {
  await apiClient.delete(`/semesters/${id}`);
};

export const setActiveSemester = async (id: string): Promise<Semester> => {
  const { data } = await apiClient.post(`/semesters/${id}/set-active`);
  return data;
};
