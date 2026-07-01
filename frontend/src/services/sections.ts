import apiClient from '../api/client';
import type { SectionRead, SectionCreate, SectionUpdate } from '../types/models';

export const getSections = async (): Promise<SectionRead[]> => {
  const { data } = await apiClient.get('/sections');
  return data;
};

export const getSection = async (id: string): Promise<SectionRead> => {
  const { data } = await apiClient.get(`/sections/${id}`);
  return data;
};

export const createSection = async (payload: SectionCreate): Promise<SectionRead> => {
  const { data } = await apiClient.post('/sections', payload);
  return data;
};

export const updateSection = async (id: string, payload: SectionUpdate): Promise<SectionRead> => {
  const { data } = await apiClient.patch(`/sections/${id}`, payload);
  return data;
};

export const deleteSection = async (id: string): Promise<void> => {
  await apiClient.delete(`/sections/${id}`);
};
