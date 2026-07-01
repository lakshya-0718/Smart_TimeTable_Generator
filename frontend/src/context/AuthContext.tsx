import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import type { User, LoginResponse } from '../types/auth';
import { authStorage } from '../utils/authStorage';
import apiClient from '../api/client';

interface AuthContextType {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (authData: LoginResponse, userData: User) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(authStorage.getUser());
  const [token, setToken] = useState<string | null>(authStorage.getToken());
  const [isLoading, setIsLoading] = useState(true);

  // Verify backend connectivity by calling /auth/me on mount if token exists
  useEffect(() => {
    const verifySession = async () => {
      if (token) {
        try {
          const response = await apiClient.get<User>('/auth/me');
          setUser(response.data);
          authStorage.setUser(response.data);
        } catch (error) {
          // 401 is handled by interceptor which clears storage and dispatches event
          console.error("Session verification failed", error);
        }
      }
      setIsLoading(false);
    };

    verifySession();
  }, [token]);

  // Listen for unauthorized events from axios interceptor
  useEffect(() => {
    const handleUnauthorized = () => {
      setUser(null);
      setToken(null);
    };

    window.addEventListener('auth:unauthorized', handleUnauthorized);
    return () => window.removeEventListener('auth:unauthorized', handleUnauthorized);
  }, []);

  const login = (authData: LoginResponse, userData: User) => {
    authStorage.setToken(authData.access_token);
    authStorage.setUser(userData);
    setToken(authData.access_token);
    setUser(userData);
  };

  const logout = () => {
    authStorage.clear();
    setToken(null);
    setUser(null);
  };

  const value = {
    user,
    token,
    isAuthenticated: !!token && !!user,
    isLoading,
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
