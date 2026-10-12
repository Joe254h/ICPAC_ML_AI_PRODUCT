"use client";

import { useState } from "react";
import { Card } from "@/components/ui";
import { getBulletinOperatorKey, setBulletinOperatorKey } from "@/services/api";

export default function BulletinAccess() {
  const [key, setKey] = useState(getBulletinOperatorKey);
  return (
    <Card>
      <label className="field">
        Bulletin operator access key
        <input
          type="password"
          autoComplete="off"
          value={key}
          onChange={(e) => {
            setKey(e.target.value);
            setBulletinOperatorKey(e.target.value);
          }}
        />
      </label>
      <p className="muted">
        Operators need their access key to create drafts or make manual
        decisions. It stays in this tab until you reload or close it. Reviewers
        can use their personal email link instead.
      </p>
    </Card>
  );
}
