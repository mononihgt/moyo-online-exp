import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Download, ListChecks, Search, Wallet } from "lucide-react";
import type { PaymentAdmin, PaymentStatus } from "../../shared/types";
import { formatDateTime, formatMoney, formatShanghaiDate } from "../../shared/format";
import { adminApi, adminDownload, errorMessage } from "../api";
import type { PaymentsResponse } from "../types";
import {
  EmptyState,
  ErrorNotice,
  Field,
  InlineNotice,
  LoadingBlock,
  Modal,
  PageHeader,
  PaymentStatusChip,
  centsFromYuan,
  useUi,
  yuanFromCents,
} from "../ui";
import { paymentSourceLabel } from "../labels";
import "../admin-payments.css";

type StatusFilter = "" | PaymentStatus;
type ExportKind = "payment" | "reimbursement";

interface DateRange {
  from: string;
  to: string;
}

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function defaultDateRange(): DateRange {
  const now = Date.now();
  return {
    from: formatShanghaiDate(new Date(now - 6 * 86400_000)),
    to: formatShanghaiDate(new Date(now)),
  };
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

function paymentActionPayload(
  payment: PaymentAdmin,
  status: PaymentStatus,
): Record<string, unknown> {
  return {
    status,
    overrideAmountCents: payment.overrideAmountCents,
    adminNote: payment.note,
  };
}

export function PaymentsPage() {
  const { notify, confirm } = useUi();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [range, setRange] = useState<DateRange>(() => readDateRange(searchParams));
  const [payments, setPayments] = useState<PaymentAdmin[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<ExportKind | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [overrideTarget, setOverrideTarget] = useState<PaymentAdmin | null>(null);
  const [overrideAmount, setOverrideAmount] = useState("");
  const [overrideNote, setOverrideNote] = useState("");
  const [overrideError, setOverrideError] = useState<string | null>(null);
  const [submittingOverride, setSubmittingOverride] = useState(false);

  const load = useCallback(async () => {
    if (!statusFilter || rangeErrorFor(range) !== null) {
      setPayments([]);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        status: statusFilter,
        from: range.from,
        to: range.to,
        limit: "300",
      });
      const response = await adminApi.get<PaymentsResponse>(`/payments?${params.toString()}`);
      setPayments(response.payments);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [statusFilter, range.from, range.to]);

  useEffect(() => {
    void load();
  }, [load]);

  const visiblePayments = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return payments;
    return payments.filter((payment) => {
      const haystack = [
        payment.name,
        payment.phoneMasked,
        payment.analysisCode ?? "",
        payment.roomId ?? "",
        payment.note ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [payments, search]);

  const pendingSummary = useMemo(() => {
    const pending = payments.filter((payment) => payment.status === "pending");
    return {
      count: pending.length,
      amount: pending.reduce((total, payment) => total + payment.totalCents, 0),
    };
  }, [payments]);

  function openOverride(payment: PaymentAdmin) {
    setOverrideTarget(payment);
    setOverrideAmount(yuanFromCents(payment.overrideAmountCents));
    setOverrideNote(payment.note ?? "");
    setOverrideError(null);
  }

  function closeOverride() {
    if (submittingOverride) return;
    setOverrideTarget(null);
    setOverrideError(null);
  }

  async function submitOverride() {
    if (!overrideTarget?.id) return;
    const amountCents = overrideAmount.trim() === "" ? null : centsFromYuan(overrideAmount);
    if (overrideAmount.trim() !== "" && amountCents === null) {
      setOverrideError("覆盖金额必须是非负金额");
      return;
    }
    if (amountCents !== null && !overrideNote.trim()) {
      setOverrideError("设置覆盖金额时必须填写备注");
      return;
    }
    const ok = await confirm({
      title: amountCents === null ? "清除金额覆盖" : "覆盖付款金额",
      message: [
        `参与者：${overrideTarget.name}（${overrideTarget.phoneMasked}）`,
        amountCents === null
          ? `清除覆盖后合计恢复为自动金额 ${formatMoney(
              overrideTarget.basePayCents +
                overrideTarget.performancePayCents +
                overrideTarget.showupPayCents,
            )}。`
          : `确认将合计金额覆盖为 ${formatMoney(amountCents)}？`,
        overrideNote.trim() ? `备注：${overrideNote.trim()}` : "",
        "该操作会写入审计日志。",
      ]
        .filter(Boolean)
        .join("\n"),
      confirmLabel: amountCents === null ? "清除覆盖" : "覆盖金额",
      danger: true,
    });
    if (!ok) return;
    setSubmittingOverride(true);
    setOverrideError(null);
    try {
      await adminApi.patch(`/payments/${overrideTarget.id}`, {
        overrideAmountCents: amountCents,
        adminNote: overrideNote.trim() ? overrideNote.trim() : null,
      });
      notify(amountCents === null ? "已清除金额覆盖" : "付款金额覆盖已保存");
      setOverrideTarget(null);
      await load();
    } catch (err) {
      setOverrideError(errorMessage(err));
    } finally {
      setSubmittingOverride(false);
    }
  }

  async function changeStatus(payment: PaymentAdmin, status: PaymentStatus) {
    if (!payment.id) {
      notify("该付款记录缺少 id，无法更新", "error");
      return;
    }
    const paid = status === "paid";
    const ok = await confirm({
      title: paid ? "标记为已支付" : "改回待支付",
      message: [
        `参与者：${payment.name}（${payment.phoneMasked}）`,
        `金额：${formatMoney(payment.totalCents)}`,
        paid
          ? "确认后记录支付时间，并写入审计日志。"
          : "确认后清除支付时间，金额与覆盖保持不变。",
      ].join("\n"),
      confirmLabel: paid ? "标记已支付" : "改回待支付",
      danger: !paid,
    });
    if (!ok) return;
    setBusyId(payment.id);
    try {
      await adminApi.patch(
        `/payments/${payment.id}`,
        paymentActionPayload(payment, status),
      );
      notify(paid ? "付款已标记为已支付" : "付款已改回待支付");
      await load();
    } catch (err) {
      notify(errorMessage(err), "error");
    } finally {
      setBusyId(null);
    }
  }

  const dateRangeError = rangeErrorFor(range);
  const listEnabled = statusFilter !== "" && dateRangeError === null;

  function updateRange(part: "from" | "to", value: string) {
    setRange((current) => ({ ...current, [part]: value }));
  }

  async function handleExport(kind: ExportKind) {
    if (dateRangeError) {
      notify(dateRangeError, "error");
      return;
    }
    setExporting(kind);
    try {
      const params = new URLSearchParams({ from: range.from, to: range.to });
      const path =
        kind === "payment"
          ? "/payments/export-payment-list.csv"
          : "/payments/export-reimbursement-list.csv";
      const prefix = kind === "payment" ? "payment-list" : "reimbursement-list";
      await adminDownload(
        `${path}?${params.toString()}`,
        `${prefix}-${range.from}-${range.to}.csv`,
      );
      notify(kind === "payment" ? "支付名单已导出" : "报销清单已导出");
    } catch (err) {
      notify(errorMessage(err), "error");
    } finally {
      setExporting(null);
    }
  }

  function openBulkPayments() {
    if (dateRangeError) {
      notify(dateRangeError, "error");
      return;
    }
    const params = new URLSearchParams({ from: range.from, to: range.to });
    navigate(`/admin/payments/bulk?${params.toString()}`);
  }

  return (
    <div>
      <PageHeader
        title="付款"
        actions={
          <>
            <button
              type="button"
              className="admin-btn admin-btn-secondary"
              onClick={openBulkPayments}
              disabled={dateRangeError !== null}
              data-testid="payment-bulk-entry"
            >
              <ListChecks size={16} />
              批量付款
            </button>
            <button
              type="button"
              className="admin-btn admin-btn-secondary"
              onClick={() => void handleExport("payment")}
              disabled={exporting !== null || dateRangeError !== null}
              data-testid="payment-export-list"
            >
              <Download size={16} />
              {exporting === "payment" ? "导出中" : "导出支付名单"}
            </button>
            <button
              type="button"
              className="admin-btn admin-btn-primary"
              onClick={() => void handleExport("reimbursement")}
              disabled={exporting !== null || dateRangeError !== null}
              data-testid="payment-export-reimbursement"
            >
              <Download size={16} />
              {exporting === "reimbursement" ? "导出中" : "导出报销清单"}
            </button>
          </>
        }
      />

      <div className="admin-filter-bar">
        <Field label="开始日期" htmlFor="payment-range-from" className="admin-filter-sm">
          <input
            id="payment-range-from"
            className="admin-input"
            type="date"
            value={range.from}
            onChange={(event) => updateRange("from", event.target.value)}
            data-testid="payment-range-from"
          />
        </Field>
        <Field label="结束日期" htmlFor="payment-range-to" className="admin-filter-sm">
          <input
            id="payment-range-to"
            className="admin-input"
            type="date"
            value={range.to}
            onChange={(event) => updateRange("to", event.target.value)}
            data-testid="payment-range-to"
          />
        </Field>
        <Field
          label="状态"
          htmlFor="payment-status-filter"
          className="admin-filter-sm"
          hideLabel
        >
          <select
            id="payment-status-filter"
            className="admin-select"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
            data-testid="payment-status-filter"
          >
            <option value="" disabled>
              选择状态
            </option>
            <option value="pending">待支付</option>
            <option value="paid">已支付</option>
          </select>
        </Field>
        <div className="admin-input-with-icon admin-filter-grow">
          <Search size={15} aria-hidden="true" />
          <input
            id="payment-search"
            className="admin-input"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="姓名、手机号、分析代码或备注"
            aria-label="搜索付款记录"
            disabled={!listEnabled}
            data-testid="payment-search"
          />
        </div>
        <div className="admin-filter-note">
          <span className="admin-hint">
            {!statusFilter
              ? "选择状态后显示日期区间内的付款记录。"
              : dateRangeError
                ? "请先修正日期范围。"
                : loading
                  ? "正在加载付款记录…"
                  : `当前列表 ${visiblePayments.length} 条，待支付 ${pendingSummary.count} 条 · ${formatMoney(
                      pendingSummary.amount,
                    )}`}
          </span>
          <span className="admin-hint">北京时间，含首尾两天。</span>
          {dateRangeError ? <span className="admin-error">{dateRangeError}</span> : null}
        </div>
      </div>

      {error && listEnabled ? (
        <ErrorNotice message={error} onRetry={() => void load()} />
      ) : null}

      {!listEnabled ? null : loading ? (
        <LoadingBlock rows={7} label="正在加载付款记录" />
      ) : payments.length === 0 ? (
        <EmptyState
          icon={Wallet}
          compact
          title="暂无付款记录"
          description="当前状态在所选日期区间内没有记录。"
        />
      ) : visiblePayments.length === 0 ? (
        <EmptyState icon={Search} compact title="没有匹配的付款记录" />
      ) : (
        <>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>参与者</th>
                  <th>房间</th>
                  <th>分析代码</th>
                  <th>明细</th>
                  <th className="admin-num">金额</th>
                  <th>状态</th>
                  <th>时间</th>
                  <th>备注</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {visiblePayments.map((payment, index) => (
                  <tr
                    key={payment.id ?? `${payment.participantId}-${payment.roomId}-${index}`}
                    data-testid={payment.id ? `payment-row-${payment.id}` : undefined}
                  >
                    <td>
                      <div className="admin-cell-stack">
                        <span>{payment.name}</span>
                        <span className="admin-cell-sub">{payment.phoneMasked}</span>
                        {(payment.source ?? "computed") !== "computed" ? (
                          <span className="admin-cell-sub">
                            {paymentSourceLabel(payment.source)}
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td>
                      <div className="admin-cell-stack">
                        <span>
                          {payment.roomStartsAt ? formatDateTime(payment.roomStartsAt) : "—"}
                        </span>
                        {payment.roomId ? (
                          <span className="admin-cell-sub admin-mono">{payment.roomId}</span>
                        ) : null}
                      </div>
                    </td>
                    <td className="admin-mono">{payment.analysisCode ?? "—"}</td>
                    <td>
                      <div className="admin-cell-stack admin-amount">
                        <span className="admin-cell-sub">基础 {formatMoney(payment.basePayCents)}</span>
                        <span className="admin-cell-sub">
                          绩效 {formatMoney(payment.performancePayCents)}
                        </span>
                        <span className="admin-cell-sub">
                          到场 {formatMoney(payment.showupPayCents)}
                        </span>
                      </div>
                    </td>
                    <td className="admin-amount">
                      <div className="admin-cell-stack">
                        <span className="admin-cell-sub">
                          覆盖{" "}
                          {payment.overrideAmountCents === null
                            ? "—"
                            : formatMoney(payment.overrideAmountCents)}
                        </span>
                        <span className="admin-total">{formatMoney(payment.totalCents)}</span>
                      </div>
                    </td>
                    <td>
                      <PaymentStatusChip status={payment.status} />
                    </td>
                    <td>
                      <div className="admin-cell-stack">
                        <span className="admin-cell-sub">
                          计算 {formatDateTime(payment.computedAt)}
                        </span>
                        <span className="admin-cell-sub">
                          截止 {formatDateTime(payment.deadlineAt)}
                        </span>
                        <span className="admin-cell-sub">
                          支付 {payment.paidAt ? formatDateTime(payment.paidAt) : "—"}
                        </span>
                      </div>
                    </td>
                    <td className="admin-url-cell">{payment.note || "—"}</td>
                    <td className="admin-actions-cell">
                      <button
                        type="button"
                        className="admin-btn admin-btn-secondary admin-btn-sm"
                        onClick={() => openOverride(payment)}
                        disabled={!payment.id || busyId === payment.id}
                        data-testid={payment.id ? `payment-override-${payment.id}` : undefined}
                      >
                        金额覆盖
                      </button>
                      {payment.status === "pending" ? (
                        <button
                          type="button"
                          className="admin-btn admin-btn-primary admin-btn-sm"
                          onClick={() => void changeStatus(payment, "paid")}
                          disabled={!payment.id || busyId === payment.id}
                          data-testid={payment.id ? `payment-mark-paid-${payment.id}` : undefined}
                        >
                          {busyId === payment.id ? "处理中" : "标记已支付"}
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="admin-btn admin-btn-secondary admin-btn-sm"
                          onClick={() => void changeStatus(payment, "pending")}
                          disabled={!payment.id || busyId === payment.id}
                          data-testid={payment.id ? `payment-mark-pending-${payment.id}` : undefined}
                        >
                          {busyId === payment.id ? "处理中" : "改回待支付"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {overrideTarget ? (
        <Modal
          title={`金额覆盖 · ${overrideTarget.name}`}
          onClose={closeOverride}
          footer={
            <>
              <button
                type="button"
                className="admin-btn admin-btn-secondary"
                onClick={closeOverride}
                disabled={submittingOverride}
              >
                取消
              </button>
              <button
                type="button"
                className="admin-btn admin-btn-primary"
                onClick={() => void submitOverride()}
                disabled={submittingOverride}
                data-testid="payment-override-save"
              >
                {submittingOverride ? "保存中" : "保存覆盖"}
              </button>
            </>
          }
        >
          <dl className="admin-detail-list" style={{ marginBottom: "16px" }}>
            <div>
              <dt>当前合计</dt>
              <dd>{formatMoney(overrideTarget.totalCents)}</dd>
            </div>
            <div>
              <dt>基础 + 绩效 + 到场</dt>
              <dd>
                {formatMoney(overrideTarget.basePayCents)} +{" "}
                {formatMoney(overrideTarget.performancePayCents)} +{" "}
                {formatMoney(overrideTarget.showupPayCents)}
              </dd>
            </div>
            <div>
              <dt>参与记录</dt>
              <dd>{overrideTarget.analysisCode ?? "无分析代码"}</dd>
            </div>
          </dl>
          <Field
            label="覆盖金额（元）"
            htmlFor="payment-override-amount"
            hint="留空表示清除覆盖，恢复按明细自动计算的合计。"
          >
            <input
              id="payment-override-amount"
              className="admin-input"
              type="number"
              min="0"
              step="0.01"
              value={overrideAmount}
              onChange={(event) => setOverrideAmount(event.target.value)}
              data-testid="payment-override-amount"
            />
          </Field>
          <Field
            label="备注"
            htmlFor="payment-override-note"
            hint="设置覆盖金额时必填，会记录在付款数据和审计日志中。"
          >
            <textarea
              id="payment-override-note"
              className="admin-textarea"
              value={overrideNote}
              onChange={(event) => setOverrideNote(event.target.value)}
              style={{ minHeight: "96px" }}
              data-testid="payment-override-note"
            />
          </Field>
          {overrideAmount.trim() !== "" ? (
            <InlineNotice tone="info">
              保存后合计将变为{" "}
              {centsFromYuan(overrideAmount) === null
                ? "—"
                : formatMoney(centsFromYuan(overrideAmount) as number)}
              ，直到覆盖被清除。
            </InlineNotice>
          ) : null}
          {overrideError ? <InlineNotice tone="error">{overrideError}</InlineNotice> : null}
        </Modal>
      ) : null}
    </div>
  );
}
