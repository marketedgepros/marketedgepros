import { useState, useRef } from 'react';
import Swal from 'sweetalert2';
import { useToast } from '../../contexts/ToastContext';
import useAuthStore from '../../store/authStore';
import { profileAPI } from '../../services/api';
import {
  User, Mail, Phone, Lock, Shield, CheckCircle,
  AlertCircle, Camera, Trash2, Upload
} from 'lucide-react';

export default function Profile() {
  const { user, updateUser } = useAuthStore();
  const toast = useToast();
  const [activeTab, setActiveTab] = useState('personal');
  const fileInputRef = useRef(null);
  
  // Personal Info
  const [personalData, setPersonalData] = useState({
    first_name: user?.first_name || '',
    last_name: user?.last_name || '',
    phone: user?.phone || '',
  });
  const [isUpdatingPersonal, setIsUpdatingPersonal] = useState(false);
  
  // Password
  const [passwordData, setPasswordData] = useState({
    current_password: '',
    new_password: '',
    confirm_password: '',
  });
  const [isUpdatingPassword, setIsUpdatingPassword] = useState(false);
  
  // Avatar
  const [isUploadingAvatar, setIsUploadingAvatar] = useState(false);

  const handleAvatarClick = () => {
    fileInputRef.current?.click();
  };

  const handleAvatarChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Validate file
    if (!file.type.startsWith('image/')) {
      toast.warning('Please select an image file');
      return;
    }

    if (file.size > 5 * 1024 * 1024) {
      toast.warning('File size must be less than 5MB');
      return;
    }

    try {
      setIsUploadingAvatar(true);
      const response = await profileAPI.uploadAvatar(file);
      updateUser({ avatar_url: response.data.avatar_url });
      toast.success('Profile picture updated successfully!');
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to upload avatar');
    } finally {
      setIsUploadingAvatar(false);
    }
  };

  const handleDeleteAvatar = async () => {
    const result = await Swal.fire({
      title: 'Delete Profile Picture?',
      text: 'Are you sure you want to delete your profile picture?',
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#ef4444',
      cancelButtonColor: '#6b7280',
      confirmButtonText: 'Yes, delete it',
      cancelButtonText: 'Cancel'
    });
    
    if (!result.isConfirmed) return;

    try {
      setIsUploadingAvatar(true);
      await profileAPI.deleteAvatar();
      updateUser({ avatar_url: null });
      toast.success('Profile picture deleted successfully!');
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to delete avatar');
    } finally {
      setIsUploadingAvatar(false);
    }
  };

  const handlePersonalUpdate = async (e) => {
    e.preventDefault();
    try {
      setIsUpdatingPersonal(true);
      const response = await profileAPI.updateProfile(personalData);
      updateUser(response.data.user);
      toast.success('Profile updated successfully!');
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to update profile');
    } finally {
      setIsUpdatingPersonal(false);
    }
  };

  const handlePasswordUpdate = async (e) => {
    e.preventDefault();

    if (passwordData.new_password !== passwordData.confirm_password) {
      toast.error('New passwords do not match');
      return;
    }

    if (passwordData.new_password.length < 8) {
      toast.warning('Password must be at least 8 characters');
      return;
    }

    try {
      setIsUpdatingPassword(true);
      await profileAPI.changePassword({
        current_password: passwordData.current_password,
        new_password: passwordData.new_password,
      });
      toast.success('Password changed successfully!');
      setPasswordData({
        current_password: '',
        new_password: '',
        confirm_password: '',
      });
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to change password');
    } finally {
      setIsUpdatingPassword(false);
    }
  };

  return (
    <>
      <div className="min-h-screen bg-slate-900">
        {/* Header */}
        <div className="bg-slate-800/50 backdrop-blur-sm border-b border-white/10">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
            <h1 className="text-3xl font-bold text-white">Profile Settings</h1>
            <p className="text-gray-400 mt-2">Manage your account settings and preferences</p>
          </div>
        </div>

        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {/* Avatar Section */}
          <div className="bg-slate-800/50 backdrop-blur-sm border border-white/10 rounded-lg shadow-md mb-6 p-6">
            <h2 className="text-lg font-bold text-white mb-4">Profile Picture</h2>
            <div className="flex items-center gap-6">
              <div className="relative">
                <div className="w-24 h-24 rounded-full bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center text-white text-2xl font-bold overflow-hidden">
                  {user?.avatar_url ? (
                    <img 
                      src={user.avatar_url} 
                      alt="Profile" 
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <span>{user?.first_name?.[0]}{user?.last_name?.[0]}</span>
                  )}
                </div>
                {isUploadingAvatar && (
                  <div className="absolute inset-0 bg-black bg-opacity-50 rounded-full flex items-center justify-center">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white"></div>
                  </div>
                )}
              </div>
              
              <div className="flex-1">
                <div className="flex gap-3">
                  <button
                    onClick={handleAvatarClick}
                    disabled={isUploadingAvatar}
                    className="px-4 py-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-lg font-medium transition-all duration-200 flex items-center gap-2 disabled:opacity-50 shadow-lg shadow-blue-500/20"
                  >
                    <Upload className="w-4 h-4" />
                    Upload New Photo
                  </button>
                  {user?.avatar_url && (
                    <button
                      onClick={handleDeleteAvatar}
                      disabled={isUploadingAvatar}
                      className="px-4 py-2 bg-slate-700/50 hover:bg-red-500/20 text-gray-300 hover:text-red-400 rounded-lg font-medium transition-all duration-200 flex items-center gap-2 disabled:opacity-50 border border-white/10"
                    >
                      <Trash2 className="w-4 h-4" />
                      Delete
                    </button>
                  )}
                </div>
                <p className="text-sm text-gray-400 mt-2">
                  JPG, PNG or GIF. Max size 5MB.
                </p>
              </div>
              
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={handleAvatarChange}
                className="hidden"
              />
            </div>
          </div>

          {/* Tabs */}
          <div className="bg-slate-800/50 backdrop-blur-sm border border-white/10 rounded-lg shadow-md mb-6">
            <div className="border-b border-white/10">
              <nav className="flex -mb-px">
                <button
                  onClick={() => setActiveTab('personal')}
                  className={`px-6 py-4 text-sm font-medium border-b-2 transition-all ${
                    activeTab === 'personal'
                      ? 'border-blue-500 text-blue-400'
                      : 'border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-600'
                  }`}
                >
                  <User className="w-4 h-4 inline mr-2" />
                  Personal Information
                </button>
                <button
                  onClick={() => setActiveTab('security')}
                  className={`px-6 py-4 text-sm font-medium border-b-2 transition-all ${
                    activeTab === 'security'
                      ? 'border-blue-500 text-blue-400'
                      : 'border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-600'
                  }`}
                >
                  <Lock className="w-4 h-4 inline mr-2" />
                  Security
                </button>
              </nav>
            </div>

            <div className="p-6">
              {activeTab === 'personal' && (
                <form onSubmit={handlePersonalUpdate} className="space-y-6">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                      <label className="block text-sm font-medium text-gray-300 mb-2">
                        First Name
                      </label>
                      <input
                        type="text"
                        value={personalData.first_name}
                        onChange={(e) => setPersonalData({ ...personalData, first_name: e.target.value })}
                        className="w-full px-4 py-2 bg-slate-700/50 border border-white/10 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                        required
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-300 mb-2">
                        Last Name
                      </label>
                      <input
                        type="text"
                        value={personalData.last_name}
                        onChange={(e) => setPersonalData({ ...personalData, last_name: e.target.value })}
                        className="w-full px-4 py-2 bg-slate-700/50 border border-white/10 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                        required
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      Email Address
                    </label>
                    <input
                      type="email"
                      value={user?.email}
                      disabled
                      className="w-full px-4 py-2 bg-slate-700/30 border border-white/10 rounded-lg text-gray-400 cursor-not-allowed"
                    />
                    <p className="text-sm text-gray-500 mt-1">
                      Email cannot be changed. Contact support if needed.
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      Phone Number
                    </label>
                    <input
                      type="tel"
                      value={personalData.phone}
                      onChange={(e) => setPersonalData({ ...personalData, phone: e.target.value })}
                      className="w-full px-4 py-2 bg-slate-700/50 border border-white/10 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                      placeholder="+1234567890"
                    />
                  </div>

                  <div className="flex justify-end">
                    <button
                      type="submit"
                      disabled={isUpdatingPersonal}
                      className="px-6 py-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-lg font-medium transition-all duration-200 disabled:opacity-50 shadow-lg shadow-blue-500/20"
                    >
                      {isUpdatingPersonal ? 'Saving...' : 'Save Changes'}
                    </button>
                  </div>
                </form>
              )}

              {activeTab === 'security' && (
                <form onSubmit={handlePasswordUpdate} className="space-y-6">
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      Current Password
                    </label>
                    <input
                      type="password"
                      value={passwordData.current_password}
                      onChange={(e) => setPasswordData({ ...passwordData, current_password: e.target.value })}
                      className="w-full px-4 py-2 bg-slate-700/50 border border-white/10 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                      required
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      New Password
                    </label>
                    <input
                      type="password"
                      value={passwordData.new_password}
                      onChange={(e) => setPasswordData({ ...passwordData, new_password: e.target.value })}
                      className="w-full px-4 py-2 bg-slate-700/50 border border-white/10 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                      required
                      minLength={8}
                    />
                    <p className="text-sm text-gray-500 mt-1">
                      Must be at least 8 characters
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      Confirm New Password
                    </label>
                    <input
                      type="password"
                      value={passwordData.confirm_password}
                      onChange={(e) => setPasswordData({ ...passwordData, confirm_password: e.target.value })}
                      className="w-full px-4 py-2 bg-slate-700/50 border border-white/10 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                      required
                    />
                  </div>

                  <div className="flex justify-end">
                    <button
                      type="submit"
                      disabled={isUpdatingPassword}
                      className="px-6 py-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-lg font-medium transition-all duration-200 disabled:opacity-50 shadow-lg shadow-blue-500/20"
                    >
                      {isUpdatingPassword ? 'Changing...' : 'Change Password'}
                    </button>
                  </div>
                </form>
              )}
            </div>
          </div>

          {/* Account Status */}
          <div className="bg-slate-800/50 backdrop-blur-sm border border-white/10 rounded-lg shadow-md p-6">
            <h2 className="text-lg font-bold text-white mb-4">Account Status</h2>
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 bg-slate-700/30 rounded-lg border border-white/5">
                <div className="flex items-center gap-3">
                  {user?.is_verified ? (
                    <CheckCircle className="w-5 h-5 text-green-400" />
                  ) : (
                    <AlertCircle className="w-5 h-5 text-yellow-400" />
                  )}
                  <div>
                    <p className="font-medium text-white">Email Verification</p>
                    <p className="text-sm text-gray-400">
                      {user?.is_verified ? 'Verified' : 'Not verified'}
                    </p>
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-between p-3 bg-slate-700/30 rounded-lg border border-white/5">
                <div className="flex items-center gap-3">
                  {user?.kyc_status === 'approved' ? (
                    <CheckCircle className="w-5 h-5 text-green-400" />
                  ) : (
                    <AlertCircle className="w-5 h-5 text-yellow-400" />
                  )}
                  <div>
                    <p className="font-medium text-white">KYC Verification</p>
                    <p className="text-sm text-gray-400 capitalize">
                      {user?.kyc_status?.replace('_', ' ') || 'Not submitted'}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}