export interface Semester {
  id: string;
  name: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SemesterCreate {
  name: string;
}

export interface SemesterUpdate {
  name?: string;
}

export type RoomType = 'LECTURE_HALL' | 'LAB';

export interface Room {
  id: string;
  name: string;
  room_type: RoomType;
  capacity: number;
  created_at: string;
  updated_at: string;
}

export interface RoomCreate {
  name: string;
  room_type: RoomType;
  capacity: number;
}

export interface RoomUpdate {
  name?: string;
  room_type?: RoomType;
  capacity?: number;
}

export type CourseTier = 'TIER_1' | 'TIER_2' | 'TIER_3' | 'TIER_4';

export interface Course {
  id: string;
  semester_id: string;
  name: string;
  code: string;
  tier: CourseTier;
  created_at: string;
  updated_at: string;
}

export interface CourseCreate {
  semester_id: string;
  name: string;
  code: string;
  tier: CourseTier;
}

export interface CourseUpdate {
  name?: string;
  code?: string;
  tier?: CourseTier;
}

export interface CourseListResponse {
  semester_id: string;
  total: number;
  items: Course[];
}

export interface PaginatedResponse<T> {
  total: number;
  items: T[];
  limit: number;
  offset: number;
}

// Users

export type UserRole = 'ADMIN' | 'FACULTY' | 'TA';

export interface UserRead {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface UserCreate {
  email: string;
  full_name: string;
  password?: string;
  role: UserRole;
}

export interface UserUpdate {
  email?: string;
  full_name?: string;
}

export interface UserListResponse {
  total: number;
  items: UserRead[];
}

// Sections

export interface SectionRead {
  id: string;
  name: string;
  year: number;
  label: 'A' | 'B';
  strength: number;
  created_at: string;
  updated_at: string;
}

export interface SectionCreate {
  year: number;
  label: 'A' | 'B';
  strength: number;
}

export interface SectionUpdate {
  strength?: number;
}

// Availability

export type DayOfWeek = 'MON' | 'TUE' | 'WED' | 'THU' | 'FRI';

export interface SlotInput {
  day: DayOfWeek;
  slot_hour: number;
}

export interface AvailabilitySlotRead {
  id: string;
  user_id: string;
  day: DayOfWeek;
  slot_hour: number;
  created_at: string;
}

export interface AvailabilityResponse {
  user_id: string;
  total: number;
  slots: AvailabilitySlotRead[];
}

// Course Assignments

export interface AssignmentRead {
  id: string;
  course_id: string;
  section_id: string;
  faculty_id: string;
  ta_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface AssignmentCreate {
  course_id: string;
  section_id: string;
  faculty_id: string;
  ta_id?: string | null;
}

export interface AssignmentUpdate {
  faculty_id?: string | null;
  ta_id?: string | null;
}

export interface AssignmentListResponse {
  total: number;
  items: AssignmentRead[];
}

// Timetable

export type SessionType = 'LECTURE' | 'TUTORIAL' | 'LAB';
export type TimetableStatus = 'ACTIVE' | 'SNAPSHOT';

export interface GenerateRequest {
  semester_id: string;
}

export interface TimetableRead {
  id: string;
  semester_id: string;
  status: TimetableStatus;
  generated_at: string;
  generated_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface TimetableEntryRead {
  id: string;
  timetable_id: string;
  assignment_id: string;
  session_type: SessionType;
  day: DayOfWeek;
  start_slot: number;
  end_slot: number;
  room_id: string;
  section_id: string;
  faculty_id: string;
  ta_id: string | null;
  created_at: string;
}

export interface ConflictItemRead {
  assignment_id?: string | null;
  course_code?: string | null;
  course_name?: string | null;
  section?: string | null;
  session_type?: string | null;
  reason_code?: string | null;
  reason_detail?: string | null;
  blocking_constraints: string[];
}

export interface ConflictReportRead {
  timetable_id: string;
  total: number;
  conflicts: ConflictItemRead[];
}

export interface TimetableEntriesResponse {
  timetable_id: string;
  total: number;
  items: TimetableEntryRead[];
}

export interface GenerateResponse {
  timetable_id: string;
  warnings: string[];
  conflict_count: number;
  snapshot_id: string | null;
}
