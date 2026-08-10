import { ROLES } from "../constants/roles";
import { useAuthStore } from "../stores/authStore";

export const usePermissions = () => {
  const role = useAuthStore((state) => state.role);

  const isSuperAdmin = role === ROLES.SUPER_ADMIN;
  const isAdmin = role === ROLES.ADMIN;
  const canReviewNews = isSuperAdmin || isAdmin;

  return {
    canManageAccounts: isSuperAdmin,
    canViewLogs: isSuperAdmin,
    canExport: canReviewNews,
    canReviewNews,
  };
};
