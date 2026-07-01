import apiClient from '../api/client';
import type { 
  GenerateRequest, 
  GenerateResponse, 
  TimetableRead, 
  TimetableEntriesResponse, 
  ConflictReportRead,
  DayOfWeek
} from '../types/models';

export const generateTimetable = async (payload: GenerateRequest): Promise<GenerateResponse> => {
  const { data } = await apiClient.post('/timetable/generate', payload);
  return data;
};

export const getActiveTimetable = async (semesterId: string): Promise<TimetableRead> => {
  const { data } = await apiClient.get(`/timetable/active/${semesterId}`);
  return data;
};

export const getTimetableEntries = async (
  timetableId: string,
  sectionId?: string,
  facultyId?: string,
  roomId?: string,
  day?: DayOfWeek,
  skip = 0,
  limit = 200
): Promise<TimetableEntriesResponse> => {
  const params: any = { skip, limit };
  if (sectionId) params.section_id = sectionId;
  if (facultyId) params.faculty_id = facultyId;
  if (roomId) params.room_id = roomId;
  if (day) params.day = day;

  const { data } = await apiClient.get(`/timetable/${timetableId}/entries`, { params });
  return data;
};

export const getConflictReport = async (timetableId: string): Promise<ConflictReportRead> => {
  const { data } = await apiClient.get(`/timetable/${timetableId}/conflicts`);
  return data;
};

export const deleteTimetable = async (timetableId: string): Promise<void> => {
  await apiClient.delete(`/timetable/${timetableId}`);
};

export const downloadTimetableCsv = async (timetableId: string, exportType: string, filterId?: string): Promise<void> => {
  const params = new URLSearchParams({ export_type: exportType });
  if (filterId) {
    params.append('filter_id', filterId);
  }

  const response = await apiClient.get(`/timetable/${timetableId}/export?${params.toString()}`, {
    responseType: 'blob',
  });

  const blob = response.data;
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;

  let filename = 'timetable.csv';
  const contentDisposition = response.headers['content-disposition'];
  if (contentDisposition && contentDisposition.includes('filename=')) {
    const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/);
    if (filenameMatch && filenameMatch.length === 2) {
      filename = filenameMatch[1];
    }
  }

  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(url);
};
