import { Navigate } from 'react-router-dom';
import useAuthStore from '../store/authStore';
import { accountHome } from '../services/navigationService.js';

export default function RoleBasedDashboard() {
  const { user } = useAuthStore();
  return <Navigate to={user ? accountHome(user) : '/login'} replace />;
}
