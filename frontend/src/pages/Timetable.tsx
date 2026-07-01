import React, { useState, useEffect } from 'react';
import { 
  ArrowPathIcon, 
  ExclamationTriangleIcon, 
  ArrowDownTrayIcon,
  CheckCircleIcon
} from '@heroicons/react/24/outline';
import { 
  generateTimetable, 
  getActiveTimetable, 
  getTimetableEntries, 
  getConflictReport,
  downloadTimetableCsv 
} from '../services/timetable';
import { getSemesters } from '../services/semesters';
import { getSections } from '../services/sections';
import { getUsers } from '../services/users';
import { getRooms } from '../services/rooms';
import { getAssignments } from '../services/courseAssignments';
import { getCourses } from '../services/courses';
import type { 
  Semester, 
  TimetableRead, 
  TimetableEntryRead, 
  ConflictReportRead,
  SectionRead,
  UserRead,
  Room,
  AssignmentRead,
  Course
} from '../types/models';
import { PageHeader } from '../components/common/PageHeader';
import { Alert } from '../components/common/Alert';

const DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI'] as const;
const SLOTS = Array.from({ length: 10 }, (_, i) => i + 8); // 8 to 17

export default function Timetable() {
  // Global Data
  const [semesters, setSemesters] = useState<Semester[]>([]);
  const [selectedSemesterId, setSelectedSemesterId] = useState<string>('');
  
  // Dictionaries for resolving UUIDs to names
  const [sections, setSections] = useState<Record<string, SectionRead>>({});
  const [faculty, setFaculty] = useState<Record<string, UserRead>>({});
  const [rooms, setRooms] = useState<Record<string, Room>>({});
  const [assignments, setAssignments] = useState<Record<string, AssignmentRead>>({});
  const [courses, setCourses] = useState<Record<string, Course>>({});

  // Timetable State
  const [activeTimetable, setActiveTimetable] = useState<TimetableRead | null>(null);
  const [entries, setEntries] = useState<TimetableEntryRead[]>([]);
  const [conflicts, setConflicts] = useState<ConflictReportRead | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  
  // UI State
  const [isLoading, setIsLoading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Filters for Grid
  const [filterType, setFilterType] = useState<'SECTION' | 'FACULTY' | 'ROOM'>('SECTION');
  const [filterId, setFilterId] = useState<string>('');

  useEffect(() => {
    const loadGlobals = async () => {
      try {
        const [sems, sects, facs, tas, rms, assigns] = await Promise.all([
          getSemesters(),
          getSections(),
          getUsers('FACULTY', 0, 200),
          getUsers('TA', 0, 200),
          getRooms(),
          getAssignments()
        ]);
        
        setSemesters(sems);
        setSections(sects.reduce((acc, s) => ({ ...acc, [s.id]: s }), {}));
        const users = [...facs.items, ...tas.items];
        setFaculty(users.reduce((acc, u) => ({ ...acc, [u.id]: u }), {}));
        setRooms(rms.reduce((acc, r) => ({ ...acc, [r.id]: r }), {}));
        setAssignments(assigns.items.reduce((acc, a) => ({ ...acc, [a.id]: a }), {}));

        const activeSem = sems.find(s => s.is_active);
        if (activeSem) {
          setSelectedSemesterId(activeSem.id);
        }
      } catch (err: any) {
        console.error(err);
        setError('Failed to load global data.');
      }
    };
    loadGlobals();
  }, []);

  const loadTimetableData = async (semesterId: string) => {
    if (!semesterId) {
      setActiveTimetable(null);
      setEntries([]);
      setConflicts(null);
      setWarnings([]);
      return;
    }
    
    setIsLoading(true);
    setError(null);
    setSuccessMsg(null);
    
    try {
      // 1. Fetch courses for this semester (to resolve names)
      const coursesData = await getCourses(semesterId, 1, 200);
      setCourses(coursesData.items.reduce((acc, c) => ({ ...acc, [c.id]: c }), {}));

      // 2. Try to get active timetable
      let tt: TimetableRead;
      try {
        tt = await getActiveTimetable(semesterId);
        setActiveTimetable(tt);
      } catch (err: any) {
        if (err.response?.status === 404) {
          setActiveTimetable(null);
          setEntries([]);
          setConflicts(null);
          return;
        }
        throw err;
      }

      // 3. If exists, fetch entries and conflicts
      const [entriesData, conflictsData] = await Promise.all([
        getTimetableEntries(tt.id, undefined, undefined, undefined, undefined, 0, 500),
        getConflictReport(tt.id)
      ]);
      setEntries(entriesData.items);
      setConflicts(conflictsData);
      
    } catch (err: any) {
      console.error(err);
      setError(err.response?.data?.detail || 'Failed to load timetable data.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadTimetableData(selectedSemesterId);
    // Auto-select first section as default filter if none selected
    if (!filterId && Object.keys(sections).length > 0 && filterType === 'SECTION') {
      setFilterId(Object.keys(sections)[0]);
    }
  }, [selectedSemesterId]);

  const handleGenerate = async () => {
    if (!selectedSemesterId) return;
    setIsGenerating(true);
    setError(null);
    setSuccessMsg(null);
    setWarnings([]);
    
    try {
      const res = await generateTimetable({ semester_id: selectedSemesterId });
      setWarnings(res.warnings || []);
      
      let msg = `Timetable generated successfully!`;
      if (res.conflict_count > 0) {
        msg += ` However, there are ${res.conflict_count} unscheduled sessions (conflicts).`;
      }
      setSuccessMsg(msg);
      
      // Reload the data
      await loadTimetableData(selectedSemesterId);
    } catch (err: any) {
      console.error(err);
      setError(err.response?.data?.detail || 'Timetable generation failed. Please check validation rules.');
    } finally {
      setIsGenerating(false);
    }
  };

  const getCourseName = (assignmentId: string) => {
    const assignment = assignments[assignmentId];
    if (!assignment) return 'Unknown';
    const course = courses[assignment.course_id];
    return course ? `${course.code} - ${course.name}` : 'Unknown';
  };

  // Filter entries based on UI selected filter
  const displayedEntries = entries.filter(e => {
    if (!filterId) return true;
    if (filterType === 'SECTION') return e.section_id === filterId;
    if (filterType === 'FACULTY') return e.faculty_id === filterId || e.ta_id === filterId;
    if (filterType === 'ROOM') return e.room_id === filterId;
    return true;
  });

  const getEntriesForCell = (day: string, slot: number) => {
    return displayedEntries.filter(e => e.day === day && e.start_slot === slot);
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12">
      <PageHeader
        title="Timetable Management"
        subtitle="Generate and view class schedules."
        actionLabel={isGenerating ? 'Generating...' : 'Generate Timetable'}
        onAction={handleGenerate}
        isActionDisabled={!selectedSemesterId || isGenerating}
        actionIcon={isGenerating ? <ArrowPathIcon className="animate-spin w-5 h-5 mr-2" /> : undefined}
      />

      {/* Controls */}
      <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100 flex flex-wrap items-end gap-4">
        <div className="flex-1 min-w-[200px]">
          <label className="block text-sm font-medium text-gray-700 mb-1">Semester</label>
          <select
            value={selectedSemesterId}
            onChange={(e) => setSelectedSemesterId(e.target.value)}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none"
          >
            <option value="">-- Select Semester --</option>
            {semesters.map((s) => (
              <option key={s.id} value={s.id}>{s.name} {s.is_active ? '(Active)' : ''}</option>
            ))}
          </select>
        </div>
        
        {activeTimetable && (
          <>
            <div className="flex-1 min-w-[200px]">
              <label className="block text-sm font-medium text-gray-700 mb-1">View By</label>
              <select
                value={filterType}
                onChange={(e) => {
                  const type = e.target.value as 'SECTION'|'FACULTY'|'ROOM';
                  setFilterType(type);
                  // Auto-pick first
                  if (type === 'SECTION') setFilterId(Object.keys(sections)[0] || '');
                  if (type === 'FACULTY') setFilterId(Object.keys(faculty)[0] || '');
                  if (type === 'ROOM') setFilterId(Object.keys(rooms)[0] || '');
                }}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none"
              >
                <option value="SECTION">Section</option>
                <option value="FACULTY">Faculty/TA</option>
                <option value="ROOM">Room</option>
              </select>
            </div>

            <div className="flex-1 min-w-[200px]">
              <label className="block text-sm font-medium text-gray-700 mb-1">Select {filterType}</label>
              <select
                value={filterId}
                onChange={(e) => setFilterId(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none"
              >
                <option value="">-- All --</option>
                {filterType === 'SECTION' && Object.values(sections).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                {filterType === 'FACULTY' && Object.values(faculty).map(f => <option key={f.id} value={f.id}>{f.full_name} ({f.role})</option>)}
                {filterType === 'ROOM' && Object.values(rooms).map(r => <option key={r.id} value={r.id}>{r.name} (Cap: {r.capacity})</option>)}
              </select>
            </div>
            
            <div className="flex gap-2 min-w-full lg:min-w-0 pt-2 lg:pt-0">
              <button 
                onClick={() => downloadTimetableCsv(activeTimetable.id, 'FULL')}
                className="flex items-center px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-medium rounded-lg transition-colors border border-gray-200"
              >
                <ArrowDownTrayIcon className="w-4 h-4 mr-2" /> Full CSV
              </button>
              {filterId && (
                <button 
                  onClick={() => downloadTimetableCsv(activeTimetable.id, filterType, filterId)}
                  className="flex items-center px-4 py-2 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-sm font-medium rounded-lg transition-colors border border-indigo-200"
                >
                  <ArrowDownTrayIcon className="w-4 h-4 mr-2" /> Export {filterType} CSV
                </button>
              )}
            </div>
          </>
        )}
      </div>

      {error && <Alert type="error" message={error} />}
      {successMsg && (
        <div className="p-4 bg-green-50 border border-green-200 rounded-lg flex items-start gap-3">
          <CheckCircleIcon className="w-5 h-5 text-green-600 mt-0.5" />
          <div className="text-green-800 font-medium">{successMsg}</div>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
          <div className="flex items-center gap-2 text-yellow-800 font-medium mb-2">
            <ExclamationTriangleIcon className="w-5 h-5" /> Generation Warnings
          </div>
          <ul className="list-disc pl-5 text-sm text-yellow-700 space-y-1">
            {warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </div>
      )}

      {conflicts && conflicts.total > 0 && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
          <div className="flex items-center gap-2 text-red-800 font-medium mb-2">
            <ExclamationTriangleIcon className="w-5 h-5" /> Conflicts ({conflicts.total} unscheduled sessions)
          </div>
          <div className="max-h-64 overflow-y-auto mt-3">
            <table className="w-full text-sm text-left text-red-900 border-collapse">
              <thead className="bg-red-100">
                <tr>
                  <th className="px-3 py-2 font-semibold">Course</th>
                  <th className="px-3 py-2 font-semibold">Section</th>
                  <th className="px-3 py-2 font-semibold">Type</th>
                  <th className="px-3 py-2 font-semibold">Reason</th>
                  <th className="px-3 py-2 font-semibold">Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-red-200">
                {conflicts.conflicts.map((c, idx) => (
                  <tr key={idx}>
                    <td className="px-3 py-2">{c.course_code || '-'}</td>
                    <td className="px-3 py-2">{c.section || '-'}</td>
                    <td className="px-3 py-2">{c.session_type || '-'}</td>
                    <td className="px-3 py-2 font-medium">{c.reason_code || '-'}</td>
                    <td className="px-3 py-2 text-xs">{c.reason_detail || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-20 text-gray-500">Loading timetable...</div>
      ) : !activeTimetable ? (
        <div className="text-center py-20 bg-white border border-gray-200 rounded-xl shadow-sm">
          <ExclamationTriangleIcon className="w-12 h-12 text-gray-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900">No timetable generated</h3>
          <p className="text-gray-500 mt-2 mb-6 max-w-md mx-auto">
            There is currently no active timetable for this semester. Click Generate Timetable to create one.
          </p>
          <button
            onClick={handleGenerate}
            disabled={isGenerating || !selectedSemesterId}
            className="px-6 py-2 bg-indigo-600 text-white font-medium rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50"
          >
            {isGenerating ? 'Generating...' : 'Generate Timetable'}
          </button>
        </div>
      ) : (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-x-auto">
          <table className="w-full text-sm text-left min-w-[1000px]">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-4 py-3 font-semibold text-gray-700 w-24 border-r border-gray-200">Time</th>
                {DAYS.map(day => (
                  <th key={day} className="px-4 py-3 font-semibold text-gray-700 text-center border-r border-gray-200 w-1/5">
                    {day}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {SLOTS.map(slot => (
                <tr key={slot} className="border-b border-gray-100">
                  <td className="px-4 py-3 font-medium text-gray-500 bg-gray-50 border-r border-gray-200 text-center">
                    {slot}:00 - {slot+1}:00
                  </td>
                  {DAYS.map(day => {
                    const cellEntries = getEntriesForCell(day, slot);
                    return (
                      <td key={`${day}-${slot}`} className="p-2 border-r border-gray-100 align-top h-24">
                        <div className="flex flex-col gap-2">
                          {cellEntries.map(entry => (
                            <div key={entry.id} className={`p-2 rounded border text-xs ${
                              entry.session_type === 'LECTURE' ? 'bg-blue-50 border-blue-200 text-blue-900' :
                              entry.session_type === 'LAB' ? 'bg-purple-50 border-purple-200 text-purple-900' :
                              'bg-green-50 border-green-200 text-green-900'
                            }`}>
                              <div className="font-bold">{getCourseName(entry.assignment_id)}</div>
                              <div className="flex justify-between items-center mt-1">
                                <span className="font-medium bg-white/50 px-1 rounded">{entry.session_type}</span>
                                <span>{sections[entry.section_id]?.name || 'Unknown Sec'}</span>
                              </div>
                              <div className="mt-1 text-gray-600">
                                {entry.session_type !== 'TUTORIAL' && (
                                  <div>Faculty: {faculty[entry.faculty_id]?.full_name?.split(' ')[0] || 'Unknown'}</div>
                                )}
                                {(entry.session_type === 'TUTORIAL' || entry.session_type === 'LAB') && entry.ta_id && (
                                  <div>TA: {faculty[entry.ta_id]?.full_name?.split(' ')[0] || 'Unknown'}</div>
                                )}
                                <div className="font-medium mt-0.5">Room: {rooms[entry.room_id]?.name || 'Unknown Room'}</div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
