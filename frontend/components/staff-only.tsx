"use client";
/**
 * Controls that need a named staff key (running and resetting forecasts, models): shown to
 * staff signed in with their key, an administrator for ``admin``. Others see a "Staff
 * access" button that opens the sign-in, or nothing with ``quiet``.
 */
import { KeyRound } from "lucide-react";
import { openStaffAccess } from "@/components/bulletin-access";
import { Button } from "@/components/ui";
import { useStaff } from "@/services/staff";

export default function StaffOnly({
  children,
  admin = false,
  quiet = false,
  label = "Staff access",
}: {
  children: React.ReactNode;
  admin?: boolean;
  quiet?: boolean;
  label?: string;
}) {
  const access = useStaff();
  if (admin ? access.admin : access.staff) return <>{children}</>;
  if (quiet) return null;
  return (
    <Button
      variant="outline"
      onClick={openStaffAccess}
      title={
        admin
          ? "An administrator's staff key is needed"
          : "A staff access key is needed"
      }
    >
      <KeyRound size={16} aria-hidden /> {label}
    </Button>
  );
}
