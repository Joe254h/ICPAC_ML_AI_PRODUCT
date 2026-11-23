"use client";
/** Whether this visitor can use staff actions, as the service answers it. */
import { useApp } from "@/components/shell";
import type { StaffUser } from "@/services/api";
import { useApi } from "@/services/hooks";

export function useStaff(): {
  /** The visitor's own actions will be accepted (signed in, or the service is public):
   * the Copilot, bulletin drafts and review, verifying finished weeks. */
  signedIn: boolean;
  /** The service asks for a staff key that this visitor has not given. */
  needsSignIn: boolean;
  /** A named staff member signed in with their key: the weekly cycle, downloads, forecast
   * runs, the archive and models need one, also on the public evaluation site. */
  staff: boolean;
  /** An administrator: models, the audit log and the Copilot's answer marks. */
  admin: boolean;
  user?: StaffUser;
} {
  const { health } = useApp();
  const mode = health.data?.access_mode;
  const me = useApi<StaffUser>(mode ? "/access/me" : null);
  const named = Boolean(me.data && !me.data.name.startsWith("visitor:"));
  // Open access: every visitor may run forecasts and manage models, no key asked for.
  const open = mode === "public" && Boolean(health.data?.open_access);
  return {
    signedIn: mode === "public" || Boolean(me.data),
    needsSignIn: mode === "staff" && (me.status === 401 || me.status === 403),
    staff: named || open,
    admin: (named && Boolean(me.data?.roles.includes("admin"))) || open,
    user: named ? me.data : undefined,
  };
}
