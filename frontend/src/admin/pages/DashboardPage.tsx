import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Archive,
  CalendarClock,
  ClipboardList,
  Plus,
  Upload,
  Wallet,
} from "lucide-react";
import { adminApi, errorMessage } from "../api";
import type { DashboardData } from "../types";
import {
  EmptyState,
  ErrorNotice,
  LoadingBlock,
  PageHeader,
  RoomStatusChip,
  StatusChip,
} from "../ui";
import { formatDateTime } from "../../shared/format";

function countOf(counts: Record<string, number>, ...keys: string[]): number {
  return keys.reduce((total, key) => total + (counts[key] ?? 0), 0);
}

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await adminApi.get<DashboardData>("/dashboard");
      setData(response);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = data?.roomCounts ?? {};

  return (
    <div>
      <PageHeader
        title="仪表盘"
        subtitle="查看房间、问卷与付款的当前状态。"
        actions={
          <div className="admin-quick-links">
            <Link className="admin-btn admin-btn-primary" to="/admin/rooms?create=1">
              <Plus size={16} />
              创建 Room
            </Link>
            <Link className="admin-btn admin-btn-secondary" to="/admin/participants">
              <Upload size={16} />
              导入名单
            </Link>
            <Link className="admin-btn admin-btn-secondary" to="/admin/payments">
              <Wallet size={16} />
              查看付款
            </Link>
          </div>
        }
      />

      {error ? <ErrorNotice message={error} onRetry={() => void load()} /> : null}

      {loading ? (
        <LoadingBlock rows={6} />
      ) : data ? (
        <div className="admin-stack">
          <div className="admin-grid admin-grid-4">
            <div className="admin-stat">
              <div className="admin-stat-label">即将开始</div>
              <div className="admin-stat-value">{data.upcomingCount}</div>
              <div className="admin-hint">可报名与已满且未开始的房间</div>
            </div>
            <div className="admin-stat">
              <div className="admin-stat-label">进行中</div>
              <div className="admin-stat-value">
                {countOf(counts, "waiting", "instructions", "playing")}
              </div>
              <div className="admin-hint">等待、指导语与对局阶段</div>
            </div>
            <div className="admin-stat">
              <div className="admin-stat-label">待处理问卷</div>
              <div className="admin-stat-value">{data.pendingQuestionnaireRooms}</div>
              <div className="admin-hint">问卷阶段的房间数</div>
            </div>
            <div className="admin-stat">
              <div className="admin-stat-label">待付款</div>
              <div className="admin-stat-value">{data.pendingPayments}</div>
              <div className="admin-hint">尚未标记已支付的记录</div>
            </div>
          </div>

          <div className="admin-card admin-card-flat">
            <div className="admin-stat-row">
              <h2 className="admin-section-title" style={{ marginBottom: 0 }}>
                房间状态分布
              </h2>
              <div className="admin-chip-list">
                <StatusChip>草稿 {counts.draft ?? 0}</StatusChip>
                <StatusChip tone="info">可报名 {counts.open ?? 0}</StatusChip>
                <StatusChip tone="warning">已满 {counts.full ?? 0}</StatusChip>
                <StatusChip tone="warning">等待 {counts.waiting ?? 0}</StatusChip>
                <StatusChip tone="info">指导语 {counts.instructions ?? 0}</StatusChip>
                <StatusChip tone="info">对局 {counts.playing ?? 0}</StatusChip>
                <StatusChip tone="warning">问卷 {counts.questionnaire ?? 0}</StatusChip>
                <StatusChip>归档 {counts.archived ?? 0}</StatusChip>
              </div>
            </div>
          </div>

          <div className="admin-card">
            <div className="admin-stat-row" style={{ marginBottom: "16px" }}>
              <h2 className="admin-section-title" style={{ marginBottom: 0 }}>
                <CalendarClock size={18} style={{ verticalAlign: "-3px", marginRight: "6px" }} />
                即将开始
              </h2>
              <Link to="/admin/rooms" className="admin-btn admin-btn-secondary admin-btn-sm">
                全部房间
              </Link>
            </div>
            {data.upcomingRooms.length === 0 ? (
              <EmptyState
                icon={CalendarClock}
                title="暂无即将开始的房间"
                description="创建并发布 Room 后，可报名房间会显示在这里。"
                action={
                  <Link className="admin-btn admin-btn-primary" to="/admin/rooms?create=1">
                    创建 Room
                  </Link>
                }
              />
            ) : (
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>内部名称</th>
                      <th>开始时间</th>
                      <th>地图组</th>
                      <th>状态</th>
                      <th>报名</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.upcomingRooms.map((room) => (
                      <tr key={room.id}>
                        <td>{room.internalLabel}</td>
                        <td>{formatDateTime(room.startsAt)}</td>
                        <td>
                          {room.mapGroup.name} v{room.mapGroup.version}
                        </td>
                        <td>
                          <RoomStatusChip status={room.status} />
                        </td>
                        <td>
                          {room.bookedCount}/{room.capacity}
                        </td>
                        <td>
                          <Link className="admin-row-link" to={`/admin/rooms/${room.id}`}>
                            查看
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="admin-card">
            <div className="admin-stat-row" style={{ marginBottom: "16px" }}>
              <h2 className="admin-section-title" style={{ marginBottom: 0 }}>
                <AlertTriangle size={18} style={{ verticalAlign: "-3px", marginRight: "6px" }} />
                需要关注
              </h2>
              <span className="admin-hint">等待、指导语、对局与问卷阶段的房间</span>
            </div>
            {data.attentionRooms.length === 0 ? (
              <EmptyState
                icon={ClipboardList}
                title="暂无需要关注的房间"
                description="处于等待、指导语、对局或问卷阶段的房间会显示在这里。"
              />
            ) : (
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>内部名称</th>
                      <th>开始时间</th>
                      <th>状态</th>
                      <th>报名</th>
                      <th>等待窗口</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.attentionRooms.map((room) => (
                      <tr key={room.id}>
                        <td>{room.internalLabel}</td>
                        <td>{formatDateTime(room.startsAt)}</td>
                        <td>
                          <RoomStatusChip status={room.status} />
                        </td>
                        <td>
                          {room.bookedCount}/{room.capacity}
                        </td>
                        <td>{Math.round(room.waitWindowSeconds / 60)} 分钟</td>
                        <td>
                          <Link className="admin-row-link" to={`/admin/rooms/${room.id}`}>
                            处理
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="admin-card admin-card-flat">
            <div className="admin-stat-row">
              <div>
                <h2 className="admin-section-title" style={{ marginBottom: "4px" }}>
                  归档房间
                </h2>
                <p className="admin-hint" style={{ margin: 0 }}>
                  归档后免费保留运行数据，可随时在数据页导出。
                </p>
              </div>
              <div className="admin-inline-actions">
                <StatusChip>
                  <Archive size={13} style={{ marginRight: "4px" }} />
                  {counts.archived ?? 0} 个已归档
                </StatusChip>
                <Link className="admin-btn admin-btn-secondary admin-btn-sm" to="/admin/rooms?section=archived">
                  查看归档
                </Link>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
