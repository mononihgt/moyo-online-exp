import { useCallback, useEffect, useMemo, useState } from "react";
import { ScrollText, Search } from "lucide-react";
import type { AuditEntry } from "../../shared/types";
import { formatDateTime } from "../../shared/format";
import { adminApi, errorMessage } from "../api";
import type { AuditResponse } from "../types";
import {
  EmptyState,
  ErrorNotice,
  Field,
  JsonDetails,
  LoadingBlock,
  PageHeader,
  Pagination,
} from "../ui";

const PAGE_SIZE = 100;

export function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (nextOffset: number) => {
    setLoading(true);
    setError(null);
    try {
      const response = await adminApi.get<AuditResponse>(
        `/audit?limit=${PAGE_SIZE}&offset=${nextOffset}`,
      );
      setEntries(response.entries);
      setTotal(response.total);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(offset);
  }, [load, offset]);

  const visibleEntries = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return entries;
    return entries.filter((entry) => {
      const haystack = [
        entry.action,
        entry.targetType ?? "",
        entry.targetId ?? "",
        entry.adminUserId ?? "",
        entry.payload ? JSON.stringify(entry.payload) : "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [entries, search]);

  return (
    <div>
      <PageHeader
        title="审计日志"
        subtitle="管理操作按时间倒序记录。页面每页加载 100 条，展开条目可查看完整 JSON 载荷。"
      />

      {error ? <ErrorNotice message={error} onRetry={() => void load(offset)} /> : null}

      <div className="admin-toolbar">
        <div className="admin-inline-form" style={{ margin: 0 }}>
          <Field label="搜索当前页" htmlFor="audit-search">
            <div className="admin-input-with-icon">
              <Search size={15} aria-hidden="true" />
              <input
                id="audit-search"
                className="admin-input"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="动作、对象、管理员或 JSON 内容"
                data-testid="audit-search"
              />
            </div>
          </Field>
        </div>
        <span className="admin-hint">
          共 {total} 条，当前页 {entries.length} 条
        </span>
      </div>

      {loading ? (
        <LoadingBlock rows={8} label="正在加载审计日志" />
      ) : total === 0 ? (
        <EmptyState
          icon={ScrollText}
          title="暂无审计日志"
          description="管理端的创建、更新、发布、审核和导出操作会记录在这里。"
        />
      ) : visibleEntries.length === 0 ? (
        <EmptyState
          icon={Search}
          title="当前页没有匹配记录"
          description="调整关键词，或翻页查找其他记录。"
        />
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>动作</th>
                <th>对象类型</th>
                <th>对象 id</th>
                <th>管理员 id</th>
                <th>载荷</th>
              </tr>
            </thead>
            <tbody>
              {visibleEntries.map((entry) => (
                <tr key={entry.id}>
                  <td style={{ whiteSpace: "nowrap" }}>{formatDateTime(entry.createdAt)}</td>
                  <td>
                    <span className="admin-event-type">{entry.action}</span>
                  </td>
                  <td>{entry.targetType ?? "—"}</td>
                  <td className="admin-mono">{entry.targetId ?? "—"}</td>
                  <td className="admin-mono">{entry.adminUserId ?? "—"}</td>
                  <td className="admin-url-cell">
                    {entry.payload === null ? (
                      <span className="admin-hint">—</span>
                    ) : (
                      <JsonDetails value={entry.payload} label="展开 JSON" />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!loading && total > 0 ? (
        <Pagination
          total={total}
          offset={offset}
          limit={PAGE_SIZE}
          onChange={(nextOffset) => setOffset(Math.max(0, nextOffset))}
        />
      ) : null}
    </div>
  );
}
