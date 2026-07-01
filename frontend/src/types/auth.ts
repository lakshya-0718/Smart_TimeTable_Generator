export interface User {
  id: string;
  email: string;
  full_name: string;
  role: 'ADMIN' | 'FACULTY' | 'TA';
  is_active: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface ApiError {
  detail: string | Array<{ loc: string[]; msg: string; type: string }>;
}
