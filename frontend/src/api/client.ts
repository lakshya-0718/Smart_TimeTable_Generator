import axios from 'axios';
import { authStorage } from '../utils/authStorage';

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to attach JWT token
apiClient.interceptors.request.use(
  (config) => {
    const token = authStorage.getToken();
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor to handle global errors like 401
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      // Clear storage so the context knows the user is unauthenticated
      // Navigation is handled by AuthContext/ProtectedRoute listening to state changes
      // We don't import window.location or navigate here to keep Axios pure
      authStorage.clear();
      
      // Dispatch a custom event so AuthContext can listen for unauthorized responses
      window.dispatchEvent(new Event('auth:unauthorized'));
    }
    return Promise.reject(error);
  }
);

export default apiClient;
