import apiClient from '../api/client';
import type { Course, CourseCreate, CourseUpdate, CourseListResponse } from '../types/models';

export const getCourses = async (semesterId: string, page = 1, limit = 100): Promise<CourseListResponse> => {
  const { data } = await apiClient.get('/courses', {
    params: { semester_id: semesterId, page, limit }
  });
  return data;
};

export const createCourse = async (payload: CourseCreate): Promise<Course> => {
  const { data } = await apiClient.post('/courses', payload);
  return data;
};

export const updateCourse = async (id: string, payload: CourseUpdate): Promise<Course> => {
  const { data } = await apiClient.patch(`/courses/${id}`, payload);
  return data;
};

export const deleteCourse = async (id: string): Promise<void> => {
  await apiClient.delete(`/courses/${id}`);
};
