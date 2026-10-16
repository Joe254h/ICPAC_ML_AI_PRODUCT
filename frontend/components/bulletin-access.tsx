"use client";

import { useState } from "react";
import { Card } from "@/components/ui";
import {
  getBulletinOperatorKey,
  setBulletinOperatorKey,
  request,
} from "@/services/api";

export default function BulletinAccess() {
  const [key, setKey] = useState(getBulletinOperatorKey);
  const [status, setStatus] = useState("");
  return (
    <Card>
      <label className="field">
        Staff access key
        <input
          type="password"
          autoComplete="off"
          value={key}
          onChange={(e) => {
            setKey(e.target.value);
          }}
        />
      </label>
      <button
        type="button"
        onClick={async () => {
          try {
            const user = await request<{ name: string; roles: string[] }>(
              "/access/me",
              {
                headers: { Authorization: `Bearer ${key}` },
              },
            );
            setBulletinOperatorKey(key);
            setStatus(`Connected as ${user.name} (${user.roles.join(", ")})`);
            window.dispatchEvent(new Event("staff-access"));
          } catch (error) {
            setStatus((error as Error).message);
          }
        }}
      >
        Connect
      </button>
      <button
        type="button"
        onClick={() => {
          setKey("");
          setBulletinOperatorKey("");
          setStatus("Disconnected");
          window.dispatchEvent(new Event("staff-access"));
        }}
      >
        Disconnect
      </button>
      <p role="status">{status}</p>
      <p className="muted">
        Enter your personal key and connect to use the assistant or staff
        actions. It stays in this tab until you reload or close it. Each
        person's conversations are private to their key. Reviewers can also use
        their personal email link.
      </p>
    </Card>
  );
}
