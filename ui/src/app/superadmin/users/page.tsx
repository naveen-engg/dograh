"use client";

import { Check, Loader2, RefreshCw, Shield, UserCheck, Users } from "lucide-react";
import React, { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/dateTime";
import { impersonateAsSuperadmin } from "@/lib/utils";

interface PlatformUser {
  id: number;
  email: string | null;
  provider_id: string;
  role: string;
  is_superuser: boolean;
  selected_organization_id: number | null;
  created_at: string;
}

const ROLE_COLORS: Record<string, string> = {
  super_admin: "bg-red-500/15 text-red-400 border-red-500/30",
  support_engineer: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  tenant_admin: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  tenant_user: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
};

export default function UsersManagementPage() {
  const { getAccessToken, user: currentUser } = useAuth();
  const [users, setUsers] = useState<PlatformUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [impersonatingId, setImpersonatingId] = useState<number | null>(null);

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const token = await getAccessToken();
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const res = await fetch(`${backendUrl}/api/v1/superuser/users`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!res.ok) {
        throw new Error(`Failed to load users: ${res.statusText}`);
      }

      const data = await res.json();
      setUsers(data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error fetching platform users");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const handleRoleChange = async (userId: number, newRole: string) => {
    setUpdatingId(userId);
    try {
      const token = await getAccessToken();
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const res = await fetch(`${backendUrl}/api/v1/superuser/users/${userId}/role`, {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ role: newRole }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to update role");
      }

      toast.success("User role updated successfully");
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, role: newRole } : u))
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update role");
    } finally {
      setUpdatingId(null);
    }
  };

  const handleImpersonate = async (targetUser: PlatformUser) => {
    if (!targetUser.email && !targetUser.provider_id) return;
    setImpersonatingId(targetUser.id);
    try {
      const token = await getAccessToken();
      await impersonateAsSuperadmin({
        accessToken: token,
        userId: targetUser.id,
        email: targetUser.email || undefined,
        redirectPath: "/overview",
        openInNewTab: false,
      });
      if (typeof window !== "undefined") {
        localStorage.setItem("dograh_impersonating", "true");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to start impersonation");
    } finally {
      setImpersonatingId(null);
    }
  };

  return (
    <div className="container mx-auto space-y-6 px-4 py-8 max-w-7xl">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Users className="h-6 w-6 text-primary" /> Platform Users & RBAC
          </h1>
          <p className="text-sm text-muted-foreground">
            Manage multi-tenant accounts, assign 3-tier hierarchical roles, and launch audited impersonation sessions.
          </p>
        </div>

        <Button
          variant="outline"
          size="sm"
          onClick={fetchUsers}
          disabled={loading}
          className="gap-2 self-start sm:self-auto"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh Users
        </Button>
      </div>

      <Card className="border-border/60 bg-card/60 backdrop-blur-md">
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-semibold flex items-center gap-2">
            <Shield className="h-4 w-4 text-emerald-400" /> All Registered Accounts ({users.length})
          </CardTitle>
          <CardDescription>
            Super Admins hold complete control. Support Engineers have read-only diagnostic impersonation access.
          </CardDescription>
        </CardHeader>

        <CardContent>
          {loading ? (
            <div className="flex h-48 items-center justify-center">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : users.length === 0 ? (
            <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
              No platform users registered yet.
            </div>
          ) : (
            <div className="rounded-md border border-border/40 overflow-hidden">
              <Table>
                <TableHeader className="bg-muted/40">
                  <TableRow>
                    <TableHead className="w-[80px]">ID</TableHead>
                    <TableHead>Email / User</TableHead>
                    <TableHead>Current Role</TableHead>
                    <TableHead>Org ID</TableHead>
                    <TableHead>Joined</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((u) => {
                    const isSelf = currentUser?.id === String(u.id);
                    return (
                      <TableRow key={u.id} className="hover:bg-muted/30">
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          #{u.id}
                        </TableCell>
                        <TableCell>
                          <div className="font-medium text-foreground">{u.email || "No email"}</div>
                          <div className="text-[11px] font-mono text-muted-foreground truncate max-w-[200px]">
                            {u.provider_id}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={`text-[11px] font-medium uppercase ${
                              ROLE_COLORS[u.role] || ROLE_COLORS.tenant_user
                            }`}
                          >
                            {u.role.replace("_", " ")}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {u.selected_organization_id ? `Org #${u.selected_organization_id}` : "None"}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {formatDateTime(u.created_at)}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-2">
                            <Select
                              value={u.role}
                              onValueChange={(val) => handleRoleChange(u.id, val)}
                              disabled={updatingId === u.id || isSelf}
                            >
                              <SelectTrigger className="h-8 w-[150px] text-xs">
                                <SelectValue placeholder="Select role" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="super_admin">Super Admin</SelectItem>
                                <SelectItem value="support_engineer">Support Engineer</SelectItem>
                                <SelectItem value="tenant_admin">Tenant Admin</SelectItem>
                                <SelectItem value="tenant_user">Tenant User</SelectItem>
                              </SelectContent>
                            </Select>

                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => handleImpersonate(u)}
                              disabled={impersonatingId === u.id || isSelf}
                              className="h-8 gap-1.5 text-xs text-amber-300 border-amber-500/30 hover:bg-amber-950/40 hover:text-amber-200"
                              title="Start audited impersonation session"
                            >
                              {impersonatingId === u.id ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <UserCheck className="h-3.5 w-3.5" />
                              )}
                              Impersonate
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
