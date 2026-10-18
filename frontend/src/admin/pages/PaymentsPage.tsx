import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, Search, Wallet } from "lucide-react";
import type { PaymentAdmin, PaymentStatus } from "../../shared/types";
import { formatDateTime, formatMoney } from "../../shared/format";
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

type StatusFilter = "" | PaymentStatus;

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
  const [payments, setPayments] = useState<PaymentAdmin[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [overrideTarget, setOverrideTarget] = useState<PaymentAdmin | null>(null);
  const [overrideAmount, setOverrideAmount] = useState("");
  const [overrideNote, setOverrideNote] = useState("");
  const [overrideError, setOverrideError] = useState<string | null>(null);
  const [submittingOverride, setSubmittingOverride] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set("status", statusFilter);
      params.set("limit", "300");
      const response = await adminApi.get<PaymentsResponse>(`/payments?${params.toString()}`);
      setPayments(response.payments);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

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

  async function handleExport() {
    setExporting(true);
    try {
      const date = new Date().toISOString().slice(0, 10).replace(/-/g, "");
      await adminDownload("/payments/export.csv", `payments-${date}.csv`);
      notify("付款 CSV 已导出");
    } catch (err) {
      notify(errorMessage(err), "error");
    } finally {
      setExporting(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="付款"
        subtitle="核对参与者付款金额，覆盖金额必须填写备注。付款名单 CSV 仅包含完成实验者与技术中止到场费记录。"
        actions={
          <button
            type="button"
            className="admin-btn admin-btn-primary"
            onClick={() => void handleExport()}
            disabled={exporting}
            data-testid="payment-export"
          >
            <Download size={16} />
            {exporting ? "导出中" : "导出 CSV"}
          </button>
        }
      />

      {error ? <ErrorNotice message={error} onRetry={() => void load()} /> : null}

      <div className="admin-toolbar">
        <select
          className="admin-select"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
          aria-label="按付款状态筛选"
          style={{ maxWidth: "180px" }}
          data-testid="payment-status-filter"
        >
          <option value="">全部状态</option>
          <option value="pending">待支付</option>
          <option value="paid">已支付</option>
        </select>
        <div className="admin-inline-form" style={{ margin: 0 }}>
          <Field label="搜索" htmlFor="payment-search">
            <div className="admin-input-with-icon">
              <Search size={15} aria-hidden="true" />
              <input
                id="payment-search"
                className="admin-input"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="姓名、手机号、分析代码或备注"
                data-testid="payment-search"
              />
            </div>
          </Field>
        </div>
        <span className="admin-hint">
          当前列表 {visiblePayments.length} 条，待支付 {pendingSummary.count} 条 ·{" "}
          {formatMoney(pendingSummary.amount)}
        </span>
      </div>

      {loading ? (
        <LoadingBlock rows={7} label="正在加载付款记录" />
      ) : payments.length === 0 ? (
        <EmptyState
          icon={Wallet}
          title="暂无付款记录"
          description={
            statusFilter
              ? "当前筛选条件下没有付款记录。"
              : "房间结束并计算付款后，记录会显示在这里。"
          }
        />
      ) : visiblePayments.length === 0 ? (
        <EmptyState
          icon={Search}
          title="没有匹配的付款记录"
          description="修改搜索关键词或状态筛选后重试。"
        />
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
                  <th>覆盖</th>
                  <th>合计</th>
                  <th>状态</th>
                  <th>计算时间</th>
                  <th>支付截止</th>
                  <th>支付时间</th>
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
                      <div>{payment.name}</div>
                      <div className="admin-hint">{payment.phoneMasked}</div>
                    </td>
                    <td>
                      <div>{payment.roomStartsAt ? formatDateTime(payment.roomStartsAt) : "—"}</div>
                      {payment.roomId ? (
                        <div className="admin-hint admin-mono">{payment.roomId}</div>
                      ) : null}
                    </td>
                    <td className="admin-mono">{payment.analysisCode ?? "—"}</td>
                    <td>
                      <div className="admin-hint">
                        基础 {formatMoney(payment.basePayCents)}
                      </div>
                      <div className="admin-hint">
                        绩效 {formatMoney(payment.performancePayCents)}
                      </div>
                      <div className="admin-hint">
                        到场 {formatMoney(payment.showupPayCents)}
                      </div>
                    </td>
                    <td>
                      {payment.overrideAmountCents === null ? (
                        <span className="admin-hint">—</span>
                      ) : (
                        formatMoney(payment.overrideAmountCents)
                      )}
                    </td>
                    <td className="admin-total">{formatMoney(payment.totalCents)}</td>
                    <td>
                      <PaymentStatusChip status={payment.status} />
                    </td>
                    <td>{formatDateTime(payment.computedAt)}</td>
                    <td>{formatDateTime(payment.deadlineAt)}</td>
                    <td>{payment.paidAt ? formatDateTime(payment.paidAt) : "—"}</td>
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
          <p className="admin-hint">
            金额覆盖会直接决定合计金额；清除覆盖后按基础、绩效和到场费重新计算。更新状态会保留现有覆盖金额与备注。
          </p>
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
