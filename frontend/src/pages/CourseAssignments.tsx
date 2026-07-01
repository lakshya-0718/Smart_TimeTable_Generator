import React, { useState, useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { PencilSquareIcon, TrashIcon } from '@heroicons/react/24/outline';

import { getAssignments, createAssignment, updateAssignment, deleteAssignment } from '../services/courseAssignments';
import { getSemesters } from '../services/semesters';
import { getCourses } from '../services/courses';
import { getSections } from '../services/sections';
import { getUsers } from '../services/users';

import type { 
  AssignmentRead, AssignmentCreate, AssignmentUpdate, 
  Semester, Course, SectionRead, UserRead 
} from '../types/models';

import { DataTable, type Column } from '../components/common/DataTable';
import { Modal } from '../components/common/Modal';
import { ConfirmDeleteModal } from '../components/common/ConfirmDeleteModal';
import { PageHeader } from '../components/common/PageHeader';
import { Alert } from '../components/common/Alert';
import { FormField } from '../components/common/FormField';
import { FormActions } from '../components/common/FormActions';

export default function CourseAssignments() {
  // Global Data
  const [semesters, setSemesters] = useState<Semester[]>([]);
  const [selectedSemesterId, setSelectedSemesterId] = useState<string>('');
  const [sections, setSections] = useState<SectionRead[]>([]);
  const [facultyList, setFacultyList] = useState<UserRead[]>([]);
  const [taList, setTaList] = useState<UserRead[]>([]);
  
  // Semester-specific Data
  const [courses, setCourses] = useState<Course[]>([]);
  const [assignments, setAssignments] = useState<AssignmentRead[]>([]);
  
  // UI State
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal State
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedAssignment, setSelectedAssignment] = useState<AssignmentRead | null>(null);
  
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // Forms
  const { register: registerCreate, handleSubmit: handleSubmitCreate, reset: resetCreate, watch: watchCreate, setValue: setValueCreate, formState: { errors: errorsCreate, isSubmitting: isCreating } } = useForm<AssignmentCreate>();
  const { register: registerEdit, handleSubmit: handleSubmitEdit, reset: resetEdit, formState: { errors: errorsEdit, isSubmitting: isEditing } } = useForm<AssignmentUpdate>();

  const selectedCreateCourseId = watchCreate('course_id');
  const selectedCreateCourse = useMemo(() => courses.find(c => c.id === selectedCreateCourseId), [courses, selectedCreateCourseId]);

  const selectedEditAssignmentCourse = useMemo(() => {
    if (!selectedAssignment) return null;
    return courses.find(c => c.id === selectedAssignment.course_id) || null;
  }, [courses, selectedAssignment]);



  // Initial Data Load
  useEffect(() => {
    const loadGlobals = async () => {
      try {
        setIsLoading(true);
        const [sems, sects, facs, tas] = await Promise.all([
          getSemesters(),
          getSections(),
          getUsers('FACULTY', 0, 200),
          getUsers('TA', 0, 200)
        ]);
        setSemesters(sems);
        setSections(sects);
        setFacultyList(facs.items);
        setTaList(tas.items);

        const activeSem = sems.find(s => s.is_active);
        if (activeSem) {
          setSelectedSemesterId(activeSem.id);
        }
      } catch (err: any) {
        console.error(err);
        setError('Failed to load global data.');
      } finally {
        setIsLoading(false);
      }
    };
    loadGlobals();
  }, []);

  // Fetch courses and assignments when semester changes
  const fetchSemesterData = async () => {
    if (!selectedSemesterId) {
      setCourses([]);
      setAssignments([]);
      return;
    }
    try {
      setIsLoading(true);
      setError(null);
      const [coursesData, assignmentsData] = await Promise.all([
        getCourses(selectedSemesterId, 1, 200),
        getAssignments() // Fetches 200 globally
      ]);
      setCourses(coursesData.items);
      
      // Filter assignments client-side to only show ones for courses in this semester
      const courseIdsInSemester = new Set(coursesData.items.map(c => c.id));
      const filteredAssignments = assignmentsData.items.filter(a => courseIdsInSemester.has(a.course_id));
      setAssignments(filteredAssignments);
    } catch (err: any) {
      console.error(err);
      setError('Failed to load semester data.');
    } finally {
      setIsLoading(false);
    }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    fetchSemesterData();
  }, [selectedSemesterId]);

  // Map UUIDs to human-readable names for the table
  const getCourse = (id: string) => courses.find(c => c.id === id);
  const getSection = (id: string) => sections.find(s => s.id === id);
  const getFaculty = (id: string) => facultyList.find(f => f.id === id);
  const getTA = (id: string | null) => id ? taList.find(t => t.id === id) : null;

  const onCreate = async (data: AssignmentCreate) => {
    try {
      setError(null);
      // Ensure ta_id is sent as null if empty string or "null" is selected
      const payload: AssignmentCreate = {
        course_id: data.course_id,
        section_id: data.section_id,
        faculty_id: data.faculty_id,
        ta_id: data.ta_id && data.ta_id !== 'null' ? data.ta_id : null
      };
      await createAssignment(payload);
      setIsCreateModalOpen(false);
      resetCreate();
      fetchSemesterData();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create assignment.');
    }
  };

  const onEdit = async (data: AssignmentUpdate) => {
    if (!selectedAssignment) return;
    try {
      setError(null);
      const payload: AssignmentUpdate = {
        faculty_id: data.faculty_id,
        ta_id: data.ta_id && data.ta_id !== 'null' ? data.ta_id : null
      };
      await updateAssignment(selectedAssignment.id, payload);
      setIsEditModalOpen(false);
      setSelectedAssignment(null);
      resetEdit();
      fetchSemesterData();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to update assignment.');
    }
  };

  const openEditModal = (assignment: AssignmentRead) => {
    setSelectedAssignment(assignment);
    resetEdit({
      faculty_id: assignment.faculty_id,
      ta_id: assignment.ta_id || 'null'
    });
    setIsEditModalOpen(true);
  };

  const handleDelete = async () => {
    if (!deleteId) return;
    try {
      setIsDeleting(true);
      setError(null);
      await deleteAssignment(deleteId);
      setDeleteId(null);
      fetchSemesterData();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete assignment.');
      setDeleteId(null);
    } finally {
      setIsDeleting(false);
    }
  };

  const columns: Column<AssignmentRead>[] = [
    { 
      header: 'Course', 
      accessor: (row) => {
        const c = getCourse(row.course_id);
        return c ? `${c.code} - ${c.name}` : 'Unknown Course';
      }
    },
    { 
      header: 'Section', 
      accessor: (row) => getSection(row.section_id)?.name || 'Unknown Section'
    },
    { 
      header: 'Faculty', 
      accessor: (row) => getFaculty(row.faculty_id)?.full_name || 'Unknown Faculty'
    },
    { 
      header: 'TA', 
      accessor: (row) => getTA(row.ta_id)?.full_name || '-'
    },
    { 
      header: 'Tier / Pattern', 
      accessor: (row) => {
        const c = getCourse(row.course_id);
        if (!c) return '-';
        const labels: Record<string, string> = {
          'TIER_1': '4 Cr (3L+1T+1P)',
          'TIER_2': '3 Cr (3L+1T)',
          'TIER_3': '2 Cr (Lab)',
          'TIER_4': '1 Cr (Lab)'
        };
        return (
          <span className="px-2 py-1 rounded-full text-xs font-medium bg-indigo-100 text-indigo-800">
            {labels[c.tier] || c.tier}
          </span>
        );
      } 
    },
    {
      header: 'Actions',
      accessor: (row) => (
        <div className="flex items-center space-x-2">
          <button
            onClick={() => openEditModal(row)}
            className="text-blue-500 hover:text-blue-700 transition-colors p-1 rounded hover:bg-blue-50"
            title="Edit Faculty/TA"
          >
            <PencilSquareIcon className="w-5 h-5" />
          </button>
          
          <button
            onClick={() => setDeleteId(row.id)}
            className="text-red-500 hover:text-red-700 transition-colors p-1 rounded hover:bg-red-50"
            title="Delete Assignment"
          >
            <TrashIcon className="w-5 h-5" />
          </button>
        </div>
      )
    }
  ];

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <PageHeader
        title="Course Assignments"
        subtitle="Map courses to sections and assign faculty/TAs."
        actionLabel="New Assignment"
        onAction={() => setIsCreateModalOpen(true)}
        isActionDisabled={!selectedSemesterId || courses.length === 0}
      />

      <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100 flex items-end space-x-4">
        <div className="flex-1 max-w-sm">
          <label htmlFor="semesterSelect" className="block text-sm font-medium text-gray-700 mb-1">
            Filter by Semester
          </label>
          <select
            id="semesterSelect"
            value={selectedSemesterId}
            onChange={(e) => setSelectedSemesterId(e.target.value)}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
          >
            <option value="">-- Select Semester --</option>
            {semesters.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} {s.is_active ? '(Active)' : ''}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <Alert type="error" message={error} />}

      {!selectedSemesterId && (
        <Alert type="info" message="Please select a semester to view assignments." />
      )}

      {selectedSemesterId && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-1">
          <DataTable<AssignmentRead>
            columns={columns} 
            data={assignments} 
            keyExtractor={(row) => row.id} 
            isLoading={isLoading} 
            emptyMessage="No assignments found for this semester."
          />
        </div>
      )}

      <Modal isOpen={isCreateModalOpen} onClose={() => { setIsCreateModalOpen(false); resetCreate(); }} title="Create Course Assignment">
        <form onSubmit={handleSubmitCreate(onCreate)}>
          <div className="grid grid-cols-2 gap-4">
            <FormField
              id="course_id"
              label="Course"
              as="select"
              options={[{label: '-- Select Course --', value: ''}, ...courses.map(c => ({ label: `${c.code} - ${c.name}`, value: c.id }))]}
              {...registerCreate('course_id', { required: 'Course is required' })}
              error={errorsCreate.course_id?.message as string}
            />

            <FormField
              id="section_id"
              label="Section"
              as="select"
              options={[{label: '-- Select Section --', value: ''}, ...sections.map(s => ({ label: s.name, value: s.id }))]}
              {...registerCreate('section_id', { required: 'Section is required' })}
              error={errorsCreate.section_id?.message as string}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <FormField
              id="faculty_id"
              label="Faculty"
              as="select"
              options={[{label: '-- Select Faculty --', value: ''}, ...facultyList.map(f => ({ label: f.full_name, value: f.id }))]}
              {...registerCreate('faculty_id', { required: 'Faculty is required' })}
              error={errorsCreate.faculty_id?.message as string}
            />

            <FormField
              id="ta_id"
              label="Teaching Assistant"
              as="select"
              options={[{label: 'No TA (None)', value: 'null'}, ...taList.map(t => ({ label: t.full_name, value: t.id }))]}
              {...registerCreate('ta_id')}
              error={errorsCreate.ta_id?.message as string}
            />
          </div>

          <FormActions
            onCancel={() => { setIsCreateModalOpen(false); resetCreate(); }}
            isSubmitting={isCreating}
            submitLabel="Create Assignment"
            submittingLabel="Creating..."
          />
        </form>
      </Modal>

      <Modal isOpen={isEditModalOpen} onClose={() => { setIsEditModalOpen(false); setSelectedAssignment(null); resetEdit(); }} title="Edit Course Assignment">
        <form onSubmit={handleSubmitEdit(onEdit)}>
          <div className="mb-4 p-4 bg-gray-50 rounded-lg border border-gray-200 space-y-2">
            <p className="text-sm font-medium text-gray-700">
              Course: <span className="text-gray-900 font-normal">{selectedEditAssignmentCourse ? `${selectedEditAssignmentCourse.code} - ${selectedEditAssignmentCourse.name}` : 'Unknown'}</span>
            </p>
            <p className="text-sm font-medium text-gray-700">
              Section: <span className="text-gray-900 font-normal">{getSection(selectedAssignment?.section_id || '')?.name || 'Unknown'}</span>
            </p>
            <p className="text-xs text-gray-500">Course and Section cannot be changed. Delete and recreate to alter them.</p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <FormField
              id="edit_faculty_id"
              label="Faculty"
              as="select"
              options={[{label: '-- Select Faculty --', value: ''}, ...facultyList.map(f => ({ label: f.full_name, value: f.id }))]}
              {...registerEdit('faculty_id', { required: 'Faculty is required' })}
              error={errorsEdit.faculty_id?.message as string}
            />

            <FormField
              id="edit_ta_id"
              label="Teaching Assistant"
              as="select"
              options={[{label: 'No TA (None)', value: 'null'}, ...taList.map(t => ({ label: t.full_name, value: t.id }))]}
              {...registerEdit('ta_id')}
              error={errorsEdit.ta_id?.message as string}
            />
          </div>

          <FormActions
            onCancel={() => { setIsEditModalOpen(false); setSelectedAssignment(null); resetEdit(); }}
            isSubmitting={isEditing}
            submitLabel="Save Changes"
            submittingLabel="Saving..."
          />
        </form>
      </Modal>

      <ConfirmDeleteModal
        isOpen={!!deleteId}
        onClose={() => setDeleteId(null)}
        onConfirm={handleDelete}
        isDeleting={isDeleting}
        title="Delete Course Assignment"
      />
    </div>
  );
}
