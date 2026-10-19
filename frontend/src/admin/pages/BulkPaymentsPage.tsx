import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowLeft, ListChecks, RefreshCw, Wallet } from "lucide-react";
import type { BulkPaymentRecord } from "../../shared/types";
import { formatDateTime } from "../../shared/format";
import { adminApi, errorMessage } from "../api";
import type { BulkMarkPaidResponse, BulkPaymentsResponse } from "../types";
import { ARCHIVE_REASON_LABELS } from "../labels";
import {
  EmptyState,
  ErrorNotice,
  Field,
  InlineNotice,
  LoadingBlock,
  PageHeader,
  PaymentStatusChip,
  useUi,
} from "../ui";
import "../admin-payments.css";

interface DateRange {
  from: string;
  to: string;
}

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function formatDateValue(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function defaultDateRange(): DateRange {
  const to = new Date();
  const from = new Date(to);
  from.setDate(from.getDate() - 6);
  return { from: formatDateValue(from), to: formatDateValue(to) };
}

function readDateRange(params: URLSearchParams): DateRange {
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  if (DATE_PATTERN.test(from) && DATE_PATTERN.test(to) && from <= to) {
    return { from, to };
  }
  return defaultDateRange();
}

function rangeErrorFor(range: DateRange): string | null {
  if (!range.from || !range.to) return "请选择开始日期和结束日期";
  if (range.from > range.to) return "开始日期不能晚于结束日期";
  return null;
}

function formatYuanAmount(cents: number): string {
  const yuan = cents / 100;
  return Number.isInteger(yuan) ? `¥${yuan}` : `¥${yuan.toFixed(2)}`;
}

export function BulkPaymentsPage() {
  const { notify, confirm } = useUi();
  const [searchParams, setSearchParams] = useSearchParams();
  const [draftRange, setDraftRange] = useState<DateRange>(() => readDateRange(searchParams));
  const [appliedRange, setAppliedRange] = useState<DateRange>(draftRange);
  const [payments, setPayments] = useState<BulkPaymentRecord[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [reloadNonce, setReloadNonce] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [marking, setMarking] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        from: appliedRange.from,
        to: appliedRange.to,
      });
      const response = await adminApi.get<BulkPaymentsResponse>(
        `/payments/bulk?${params.toString()}`,
      );
      setPayments(response.payments);
      setSelectedIds(
        new Set(
          response.payments
            .filter((payment) => payment.status === "pending")
            .map((payment) => payment.paymentId),
        ),
      );
    } catch (err) {
      setError(errorMessage(err));
      setPayments([]);
      setSelectedIds(new Set());
    } finally {
      setLoading(false);
    }
  }, [appliedRange.from, appliedRange.to, reloadNonce]);

  useEffect(() => {
    void load();
  }, [load]);

  const draftRangeError = rangeErrorFor(draftRange);
  const rangeDirty =
    draftRange.from !== appliedRange.from || draftRange.to !== appliedRange.to;

  const selectablePayments = useMemo(
    () => payments.filter((payment) => payment.status === "pending"),
    [payments],
  );
  const selectedPayments = useMemo(
    () => selectablePayments.filter((payment) => selectedIds.has(payment.paymentId)),
    [selectablePayments, selectedIds],
  );
  const selectedTotalCents = useMemo(
    () => selectedPayments.reduce((total, payment) => total + payment.totalCents, 0),
    [selectedPayments],
  );
  const selectedAll =
    selectablePayments.length > 0 && selectedPayments.length === selectablePayments.length;
  const selectedSome = selectedPayments.length > 0 && !selectedAll;

  function updateRange(part: "from" | "to", value: string) {
    setDraftRange((current) => ({ ...current, [part]: value }));
  }

  function applyRange() {
    if (draftRangeError) return;
    setAppliedRange({ ...draftRange });
    setSearchParams({ from: draftRange.from, to: draftRange.to }, { replace: true });
    setReloadNonce((value) => value + 1);
  }

  function togglePayment(paymentId: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(paymentId)) {
        next.delete(paymentId);
      } else {
        next.add(paymentId);
      }
      return next;
    });
  }

  function selectAll() {
    setSelectedIds(new Set(selectablePayments.map((payment) => payment.paymentId)));
  }

  function invertSelection() {
    setSelectedIds(
      new Set(
        selectablePayments
          .filter((payment) => !selectedIds.has(payment.paymentId))
          .map((payment) => payment.paymentId),
      ),
    );
  }

  async function markSelectedPaid() {
    if (selectedPayments.length === 0 || marking) return;
    const ok = await confirm({
      title: "批量标记已支付",
      message: [
        `将选中的 ${selectedPayments.length} 笔付款标记为已支付，合计 ${formatYuanAmount(
          selectedTotalCents,
        )}。`,
        "服务端只更新待支付记录，已支付记录会被跳过并统计。",
        "该操作会写入审计日志。",
      ].join("\n"),
      confirmLabel: "标记已支付",
    });
    if (!ok) return;
    setMarking(true);
    try {
      const response = await adminApi.post<BulkMarkPaidResponse>(
        "/payments/bulk-mark-paid",
        { paymentIds: selectedPayments.map((payment) => payment.paymentId) },
      );
      notify(
        `已标记 ${response.updated} 笔付款为已支付，跳过 ${response.skipped} 笔已支付记录`,
      );
      await load();
    } catch (err) {
      notify(errorMessage(err), "error");
    } finally {
      setMarking(false);
    }
  }

  const backTo = `/admin/payments?${new URLSearchParams({
    from: appliedRange.from,
    to: appliedRange.to,
  }).toString()}`;

  return (
    <div>
      <PageHeader
        title="批量付款"
        subtitle="按房间开始日期查看区间内全部付款记录，默认勾选待支付记录。技术中止到场费与已支付记录同样展示。"
        actions={
          <>
            <Link className="admin-btn admin-btn-secondary" to={backTo}>
              <ArrowLeft size={16} />
              返回付款列表
            </Link>
            <button
              type="button"
              className="admin-btn admin-btn-primary"
              onClick={() => void markSelectedPaid()}
              disabled={
                selectedPayments.length === 0 || marking || rangeDirty || loading
              }
              data-testid="bulk-mark-paid"
            >
              <ListChecks size={16} />
              {marking
                ? "处理中"
                : `批量标记已支付${selectedPayments.length > 0 ? `（${selectedPayments.length}）` : ""}`}
            </button>
          </>
        }
      />

      <InlineNotice tone="warning">
        该页面包含完整被试手机号，访问与操作会写入审计日志。请勿在公共环境中展示或截图。
      </InlineNotice>

      <div className="admin-bulk-range">
        <Field label="开始日期" htmlFor="bulk-range-from">
          <input
            id="bulk-range-from"
            className="admin-input"
            type="date"
            value={draftRange.from}
            onChange={(event) => updateRange("from", event.target.value)}
            data-testid="bulk-range-from"
          />
        </Field>
        <Field label="结束日期" htmlFor="bulk-range-to">
          <input
            id="bulk-range-to"
            className="admin-input"
            type="date"
            value={draftRange.to}
            onChange={(event) => updateRange("to", event.target.value)}
            data-testid="bulk-range-to"
          />
        </Field>
        <div className="admin-bulk-range-actions">
          <button
            type="button"
            className="admin-btn admin-btn-secondary"
            onClick={applyRange}
            disabled={draftRangeError !== null || loading}
            data-testid="bulk-refresh"
          >
            <RefreshCw size={16} className={loading ? "admin-spin" : undefined} />
            刷新
          </button>
        </div>
        <div className="admin-bulk-range-note">
          <span className="admin-hint">
            日期按北京时间自然日计算，包含首尾两天。
            {rangeDirty ? " 日期已修改，点击刷新应用。" : ""}
          </span>
          {draftRangeError ? <span className="admin-error">{draftRangeError}</span> : null}
        </div>
      </div>

      {error ? <ErrorNotice message={error} onRetry={() => void load()} /> : null}

      {!loading && payments.length > 0 ? (
        <div className="admin-bulk-summary" data-testid="bulk-summary">
          <div className="admin-bulk-summary-item">
            <span className="admin-hint">区间记录</span>
            <strong>{payments.length} 笔</strong>
          </div>
          <div className="admin-bulk-summary-item">
            <span className="admin-hint">待支付</span>
            <strong>{selectablePayments.length} 笔</strong>
          </div>
          <div className="admin-bulk-summary-item admin-bulk-summary-selected">
            <span className="admin-hint">已选</span>
            <strong>{selectedPayments.length} 笔</strong>
          </div>
          <div className="admin-bulk-summary-item admin-bulk-summary-selected">
            <span className="admin-hint">已选合计</span>
            <strong data-testid="bulk-selected-total">
              {formatYuanAmount(selectedTotalCents)}
            </strong>
          </div>
          <div className="admin-bulk-summary-actions">
            <button
              type="button"
              className="admin-btn admin-btn-secondary admin-btn-sm"
              onClick={selectAll}
              disabled={selectablePayments.length === 0}
              data-testid="bulk-select-all-button"
            >
              全选
            </button>
            <button
              type="button"
              className="admin-btn admin-btn-secondary admin-btn-sm"
              onClick={invertSelection}
              disabled={selectablePayments.length === 0}
              data-testid="bulk-invert-selection"
            >
              反选
            </button>
          </div>
        </div>
      ) : null}

      {loading ? (
        <LoadingBlock rows={8} label="正在加载区间付款记录" />
      ) : error ? null : payments.length === 0 ? (
        <EmptyState
          icon={Wallet}
          title="该日期区间没有付款记录"
          description="调整日期范围后点击刷新。"
        />
      ) : (
        <>
          <div className="admin-table-wrap">
            <table className="admin-table admin-bulk-table">
              <thead>
                <tr>
                  <th className="admin-bulk-check-head">
                    <input
                      type="checkbox"
                      aria-label="全选待支付记录"
                      checked={selectedAll}
                      ref={(node) => {
                        if (node) node.indeterminate = selectedSome;
                      }}
                      onChange={(event) => {
                        if (event.target.checked) {
                          selectAll();
                        } else {
                          setSelectedIds(new Set());
                        }
                      }}
                      disabled={selectablePayments.length === 0}
                      data-testid="bulk-select-all"
                    />
                  </th>
                  <th>姓名</th>
                  <th>支付宝手机号</th>
                  <th>参与日期</th>
                  <th>金额</th>
                  <th>状态</th>
                  <th>支付时间</th>
                </tr>
              </thead>
              <tbody>
                {payments.map((payment) => {
                  const selectable = payment.status === "pending";
                  return (
                    <tr
                      key={payment.paymentId}
                      data-testid={`bulk-payment-row-${payment.paymentId}`}
                    >
                      <td className="admin-bulk-check-cell">
                        <input
                          type="checkbox"
                          aria-label={`选择 ${payment.name} 的付款`}
                          checked={selectable && selectedIds.has(payment.paymentId)}
                          disabled={!selectable}
                          onChange={() => togglePayment(payment.paymentId)}
                          data-testid={`bulk-payment-checkbox-${payment.paymentId}`}
                        />
                      </td>
                      <td>{payment.name}</td>
                      <td className="admin-mono admin-bulk-phone">{payment.phone}</td>
                      <td>
                        <div>{formatDateTime(payment.roomStartsAt)}</div>
                        <div className="admin-hint">
                          {payment.archiveReason
                            ? ARCHIVE_REASON_LABELS[payment.archiveReason]
                            : "—"}
                        </div>
                      </td>
                      <td className="admin-total">{formatYuanAmount(payment.totalCents)}</td>
                      <td>
                        <PaymentStatusChip status={payment.status} />
                      </td>
                      <td>{payment.paidAt ? formatDateTime(payment.paidAt) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="admin-hint">
            已支付记录的复选框不可用；批量操作只提交勾选的待支付记录，服务端会跳过并统计已支付记录。
          </p>
        </>
      )}
    </div>
  );
}
