import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Archive,
  CalendarClock,
  Plus,
  Users,
  Wallet,
} from "lucide-react";
import { adminApi, errorMessage } from "../api";
import type { DashboardData } from "../types";
import {
  CardHeader,
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
        actions={
          <div className="admin-quick-links">
            <Link className="admin-btn admin-btn-primary" to="/admin/rooms?create=1">
              <Plus size={16} />
              创建 Room
            </Link>
            <Link className="admin-btn admin-btn-secondary" to="/admin/participants">
              <Users size={16} />
              被试名单
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
            </div>
            <div className="admin-stat">
              <div className="admin-stat-label">进行中</div>
              <div className="admin-stat-value">
                {countOf(counts, "waiting", "instructions", "playing")}
              </div>
            </div>
            <div className="admin-stat">
              <div className="admin-stat-label">待处理问卷</div>
              <div className="admin-stat-value">{data.pendingQuestionnaireRooms}</div>
            </div>
            <div className="admin-stat">
              <div className="admin-stat-label">待付款</div>
              <div className="admin-stat-value">{data.pendingPayments}</div>
            </div>
          </div>

          <div className="admin-card admin-card-flat">
            <CardHeader
              title="技术中止待问卷"
              meta={
                <>
                  <StatusChip tone="warning">
                    {data.pendingShowupQuestionnaireCount} 个房间
                  </StatusChip>
                  <span>到场者提交问卷后生成到场费</span>
                </>
              }
            />
            {data.pendingShowupQuestionnaireRooms.length === 0 ? (
              <p className="admin-empty-line">暂无技术中止待问卷</p>
            ) : (
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>内部名称</th>
                      <th>开始时间</th>
                      <th>报名</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.pendingShowupQuestionnaireRooms.map((room) => (
                      <tr key={room.id}>
                        <td>{room.internalLabel}</td>
                        <td>{formatDateTime(room.startsAt)}</td>
                        <td>
                          {room.bookedCount}/{room.capacity}
                        </td>
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
            <CardHeader
              title="房间状态"
              meta={
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
              }
              actions={
                <Link className="admin-btn admin-btn-secondary admin-btn-sm" to="/admin/rooms?section=archived">
                  <Archive size={14} />
                  查看归档
                </Link>
              }
            />
          </div>

          <div className="admin-card">
            <CardHeader
              title="即将开始"
              actions={
                <Link to="/admin/rooms" className="admin-btn admin-btn-secondary admin-btn-sm">
                  全部房间
                </Link>
              }
            />
            {data.upcomingRooms.length === 0 ? (
              <EmptyState
                icon={CalendarClock}
                compact
                title="暂无即将开始的房间"
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
            <CardHeader
              title="需要关注"
              meta={<span>等待、指导语、对局与问卷阶段</span>}
            />
            {data.attentionRooms.length === 0 ? (
              <p className="admin-empty-line">暂无需要关注的房间</p>
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

        </div>
      ) : null}
    </div>
  );
}
