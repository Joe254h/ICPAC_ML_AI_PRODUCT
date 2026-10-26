"use client";
/** Whether this visitor can use staff actions, as the service answers it. */
import { useApp } from "@/components/shell";
import type { StaffUser } from "@/services/api";
import { useApi } from "@/services/hooks";

export function useStaff(): {
  /** Staff actions will be accepted (signed in, or the service is public). */
  signedIn: boolean;
  /** The service asks for a staff key that this visitor has not given. */
  needsSignIn: boolean;
  user?: StaffUser;
} {
  const { health } = useApp();
  const mode = health.data?.access_mode;
  const me = useApi<StaffUser>(mode === "staff" ? "/access/me" : null);
  return {
    signedIn: mode === "public" || Boolean(me.data),
    needsSignIn: mode === "staff" && (me.status === 401 || me.status === 403),
    user: me.data,
  };
}
