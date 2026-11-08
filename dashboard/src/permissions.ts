// UI mirror of backend/app/core/permissions.py. The server is the authority: this only
// hides or disables controls that would be refused anyway.
import type { Role } from "./api/types";

const rank: Record<Role, number> = { reader: 0, writer: 1, admin: 2, owner: 3 };

const minRole: Record<string, Role> = {
  "flag.create": "writer",
  "flag.update": "writer",
  "flag.archive": "admin",
  "config.update": "writer",
  "environment.create": "admin",
  "environment.update": "admin",
  "keys.read": "admin",
  "keys.rotate": "admin",
  "members.manage": "admin",
  "project.create": "admin",
};

export function can(role: Role | undefined, action: string, protectedEnv = false): boolean {
  if (!role || !(action in minRole)) return false;
  let required = minRole[action];
  if (protectedEnv && action === "config.update") required = "admin";
  return rank[role] >= rank[required];
}
