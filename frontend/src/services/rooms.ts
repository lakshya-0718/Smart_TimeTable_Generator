import apiClient from '../api/client';
import type { Room, RoomCreate, RoomUpdate } from '../types/models';

export const getRooms = async (): Promise<Room[]> => {
  const { data } = await apiClient.get('/rooms');
  return data;
};

export const createRoom = async (payload: RoomCreate): Promise<Room> => {
  const { data } = await apiClient.post('/rooms', payload);
  return data;
};

export const updateRoom = async (id: string, payload: RoomUpdate): Promise<Room> => {
  const { data } = await apiClient.patch(`/rooms/${id}`, payload);
  return data;
};

export const deleteRoom = async (id: string): Promise<void> => {
  await apiClient.delete(`/rooms/${id}`);
};
