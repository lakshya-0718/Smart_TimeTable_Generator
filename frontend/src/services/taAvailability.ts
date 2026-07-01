import apiClient from '../api/client';
import type { AvailabilityResponse, AvailabilitySlotRead, SlotInput } from '../types/models';

export const getTAAvailability = async (userId: string): Promise<AvailabilityResponse> => {
  const { data } = await apiClient.get(`/availability/ta/${userId}`);
  return data;
};

export const replaceTAAvailability = async (userId: string, slots: SlotInput[]): Promise<AvailabilityResponse> => {
  const { data } = await apiClient.put(`/availability/ta/${userId}`, { slots });
  return data;
};

export const addTASlot = async (userId: string, slot: SlotInput): Promise<AvailabilitySlotRead> => {
  const { data } = await apiClient.post(`/availability/ta/${userId}/slots`, slot);
  return data;
};

export const deleteTASlot = async (userId: string, slotId: string): Promise<void> => {
  await apiClient.delete(`/availability/ta/${userId}/slots/${slotId}`);
};
