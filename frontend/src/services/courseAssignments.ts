import apiClient from '../api/client';
import type { 
  AssignmentRead, 
  AssignmentCreate, 
  AssignmentUpdate, 
  AssignmentListResponse 
} from '../types/models';

export const getAssignments = async (
  courseId?: string,
  sectionId?: string,
  facultyId?: string,
  skip = 0,
  limit = 200
): Promise<AssignmentListResponse> => {
  const params: any = { skip, limit };
  if (courseId) params.course_id = courseId;
  if (sectionId) params.section_id = sectionId;
  if (facultyId) params.faculty_id = facultyId;

  const { data } = await apiClient.get('/assignments', { params });
  return data;
};

export const getAssignment = async (id: string): Promise<AssignmentRead> => {
  const { data } = await apiClient.get(`/assignments/${id}`);
  return data;
};

export const createAssignment = async (payload: AssignmentCreate): Promise<AssignmentRead> => {
  const { data } = await apiClient.post('/assignments', payload);
  return data;
};

export const updateAssignment = async (id: string, payload: AssignmentUpdate): Promise<AssignmentRead> => {
  const { data } = await apiClient.patch(`/assignments/${id}`, payload);
  return data;
};

export const deleteAssignment = async (id: string): Promise<void> => {
  await apiClient.delete(`/assignments/${id}`);
};
