import {
  HomeIcon,
  CalendarDaysIcon,
  UsersIcon,
  BuildingOfficeIcon,
  UserGroupIcon,
  BookOpenIcon,
  ClipboardDocumentCheckIcon,
  ClockIcon,
  TableCellsIcon
} from '@heroicons/react/24/outline';

export const sidebarNavigation = [
  { name: 'Dashboard', href: '/dashboard', icon: HomeIcon },
  { name: 'Semesters', href: '/semesters', icon: CalendarDaysIcon },
  { name: 'Users', href: '/users', icon: UsersIcon },
  { name: 'Rooms', href: '/rooms', icon: BuildingOfficeIcon },
  { name: 'Sections', href: '/sections', icon: UserGroupIcon },
  { name: 'Courses', href: '/courses', icon: BookOpenIcon },
  { name: 'Assignments', href: '/assignments', icon: ClipboardDocumentCheckIcon },
  { name: 'Faculty Availability', href: '/availability', icon: ClockIcon },
  { name: 'TA Availability', href: '/ta-availability', icon: ClockIcon },
  { name: 'Timetable', href: '/timetable', icon: TableCellsIcon },
];
