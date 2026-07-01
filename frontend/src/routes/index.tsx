import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { ProtectedRoute } from './ProtectedRoute';
import { AppLayout } from '../components/layout/AppLayout';
import { Login } from '../pages/Login';
import { Dashboard } from '../pages/Dashboard';
import { NotFound } from '../pages/NotFound';
import Semesters from '../pages/Semesters';
import Rooms from '../pages/Rooms';
import Courses from '../pages/Courses';
import Users from '../pages/Users';
import Sections from '../pages/Sections';
import FacultyAvailability from '../pages/FacultyAvailability';
import TAAvailability from '../pages/TAAvailability';
import CourseAssignments from '../pages/CourseAssignments';
import Timetable from '../pages/Timetable';

export const AppRoutes: React.FC = () => {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      
      {/* Protected Routes */}
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          
          {/* Core Entity Management */}
          <Route path="/semesters" element={<Semesters />} />
          <Route path="/users" element={<Users />} />
          <Route path="/rooms" element={<Rooms />} />
          <Route path="/sections" element={<Sections />} />
          <Route path="/courses" element={<Courses />} />
          <Route path="/availability" element={<FacultyAvailability />} />
          <Route path="/ta-availability" element={<TAAvailability />} />
          
          {/* Placeholders for future routes */}
          <Route path="/assignments" element={<CourseAssignments />} />
          <Route path="/timetable" element={<Timetable />} />
        </Route>
      </Route>

      {/* Wildcard Route for 404 Not Found */}
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
};
