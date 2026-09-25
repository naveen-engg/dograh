"use client";

import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Filter,
  History,
  Info,
  Loader2,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
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

interface AuditLog {
  id: number;
  actor_user_id: number;
  actor_email: string | null;
  target_organization_id: number | null;
  target_user_id: number | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  method: string | null;
  path: string | null;
  ip_address: string | null;
  user_agent: string | null;
  extra_metadata: Record<string, unknown>;
  created_at: string;
}

const ACTION_BADGES: Record<string, { label: string; color: string }> = {
  blocked_write_attempt: {
    label: "Blocked Mutation",
    color: "bg-red-500/20 text-red-300 border-red-500/40",
  },
  impersonate_start: {
    label: "Impersonate Start",
    color: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  },
  impersonate_end: {
    label: "Impersonate End",
    color: "bg-zinc-500/20 text-zinc-300 border-zinc-500/40",
  },
  config_override: {
    label: "Role Override",
    color: "bg-purple-500/20 text-purple-300 border-purple-500/40",
  },
  read_resource: {
    label: "Diagnostic Read",
    color: "bg-blue-500/20 text-blue-300 border-blue-500/40",
  },
};

export default function AuditLogsPage() {
  const { getAccessToken } = useAuth();
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [actionFilter, setActionFilter] = useState<string>("all");

  const fetchLogs = async (currentPage = 1, currentFilter = actionFilter) => {
    setLoading(true);
    try {
      const token = await getAccessToken();
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const params = new URLSearchParams({
        page: String(currentPage),
        limit: "25",
      });

      if (currentFilter && currentFilter !== "all") {
        params.append("action", currentFilter);
      }

      const res = await fetch(`${backendUrl}/api/v1/superuser/audit-logs?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!res.ok) {
        throw new Error(`Failed to load audit logs: ${res.statusText}`);
      }

      const data = await res.json();
      setLogs(data.audit_logs);
      setTotalPages(data.total_pages || 1);
      setTotalCount(data.total_count || 0);
      setPage(data.page || 1);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error fetching audit logs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs(page, actionFilter);
  }, [page, actionFilter]);

  return (
    <div className="container mx-auto space-y-6 px-4 py-8 max-w-7xl">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <History className="h-6 w-6 text-primary" /> Security & Support Audit Logs
          </h1>
          <p className="text-sm text-muted-foreground">
            Complete, immutable trail of administrative impersonations, role changes, and blocked mutations.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Select
            value={actionFilter}
            onValueChange={(val) => {
              setActionFilter(val);
              setPage(1);
            }}
          >
            <SelectTrigger className="h-8 w-[180px] text-xs">
              <SelectValue placeholder="Filter by action" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Actions</SelectItem>
              <SelectItem value="blocked_write_attempt">Blocked Mutations</SelectItem>
              <SelectItem value="impersonate_start">Impersonations</SelectItem>
              <SelectItem value="config_override">Role Changes</SelectItem>
              <SelectItem value="read_resource">Diagnostic Reads</SelectItem>
            </SelectContent>
          </Select>

          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchLogs(page, actionFilter)}
            disabled={loading}
            className="gap-2"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      <Card className="border-border/60 bg-card/60 backdrop-blur-md">
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-semibold flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-primary" /> Audit Records ({totalCount})
            </div>
            <div className="text-xs font-normal text-muted-foreground">
              Page {page} of {totalPages}
            </div>
          </CardTitle>
          <CardDescription>
            Every cross-tenant inspection and impersonated session is immutably timestamped.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4">
          {loading ? (
            <div className="flex h-48 items-center justify-center">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : logs.length === 0 ? (
            <div className="flex h-32 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
              <ShieldCheck className="h-8 w-8 text-emerald-400/60" />
              No audit logs matching this filter.
            </div>
          ) : (
            <div className="rounded-md border border-border/40 overflow-hidden">
              <Table>
                <TableHeader className="bg-muted/40">
                  <TableRow>
                    <TableHead className="w-[170px]">Timestamp</TableHead>
                    <TableHead>Actor</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>Target Org</TableHead>
                    <TableHead>Resource / Path</TableHead>
                    <TableHead>Client IP</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {logs.map((log) => {
                    const badgeInfo = ACTION_BADGES[log.action] || {
                      label: log.action,
                      color: "bg-muted text-muted-foreground border-border",
                    };

                    return (
                      <TableRow key={log.id} className="hover:bg-muted/30">
                        <TableCell className="text-xs font-mono text-muted-foreground">
                          {formatDateTime(log.created_at)}
                        </TableCell>
                        <TableCell>
                          <div className="text-xs font-medium text-foreground">
                            {log.actor_email || `User #${log.actor_user_id}`}
                          </div>
                          <div className="text-[10px] font-mono text-muted-foreground">
                            ID: {log.actor_user_id}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={`text-[11px] font-medium ${badgeInfo.color}`}
                          >
                            {badgeInfo.label}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {log.target_organization_id ? `Org #${log.target_organization_id}` : "Global"}
                        </TableCell>
                        <TableCell className="text-xs">
                          {log.method && (
                            <span className="font-mono font-semibold text-[11px] text-primary mr-1.5">
                              {log.method}
                            </span>
                          )}
                          <span className="font-mono text-muted-foreground truncate max-w-[200px] inline-block align-bottom">
                            {log.path || log.resource_type || "—"}
                          </span>
                        </TableCell>
                        <TableCell className="text-xs font-mono text-muted-foreground">
                          {log.ip_address || "—"}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-end gap-2 pt-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1 || loading}
                className="h-8 gap-1 text-xs"
              >
                <ChevronLeft className="h-4 w-4" /> Previous
              </Button>
              <span className="text-xs text-muted-foreground px-2">
                {page} / {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages || loading}
                className="h-8 gap-1 text-xs"
              >
                Next <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
