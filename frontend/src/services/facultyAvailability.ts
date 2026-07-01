import apiClient from '../api/client';
import type { AvailabilityResponse, AvailabilitySlotRead, SlotInput } from '../types/models';

export const getFacultyAvailability = async (userId: string): Promise<AvailabilityResponse> => {
  const { data } = await apiClient.get(`/availability/faculty/${userId}`);
  return data;
};

export const replaceFacultyAvailability = async (userId: string, slots: SlotInput[]): Promise<AvailabilityResponse> => {
  const { data } = await apiClient.put(`/availability/faculty/${userId}`, { slots });
  return data;
};

export const addFacultySlot = async (userId: string, slot: SlotInput): Promise<AvailabilitySlotRead> => {
  const { data } = await apiClient.post(`/availability/faculty/${userId}/slots`, slot);
  return data;
};

export const deleteFacultySlot = async (userId: string, slotId: string): Promise<void> => {
  await apiClient.delete(`/availability/faculty/${userId}/slots/${slotId}`);
};
