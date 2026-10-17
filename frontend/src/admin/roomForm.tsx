import { useCallback, useEffect, useState } from "react";
import type {
  ConditionVersion,
  InstructionVersion,
  QuestionnaireVersion,
  RoomSummary,
} from "../shared/types";
import { adminApi, errorMessage } from "./api";
import type { ConditionListResponse, InstructionListResponse, QuestionnaireListResponse, RoomDraftPayload } from "./types";
import {
  Field,
  LoadingBlock,
  centsFromYuan,
  fromShanghaiInput,
  toShanghaiInput,
  yuanFromCents,
} from "./ui";

export interface RoomOptions {
  conditions: ConditionVersion[];
  instructions: InstructionVersion[];
  questionnaires: QuestionnaireVersion[];
}

export interface RoomFormState {
  internalLabel: string;
  startsAt: string;
  conditionVersionId: string;
  instructionVersionP1Id: string;
  instructionVersionP2Id: string;
  questionnaireVersionId: string;
  basePay: string;
  performanceRate: string;
  showupPay: string;
  waitMinutes: string;
  reconnectMinutes: string;
}

export interface RoomPayloadResult {
  payload: RoomDraftPayload | null;
  errors: Record<string, string>;
}

export function usePublishedOptions(): {
  options: RoomOptions;
  loading: boolean;
  error: string | null;
} {
  const [options, setOptions] = useState<RoomOptions>({
    conditions: [],
    instructions: [],
    questionnaires: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [conditions, instructions, questionnaires] = await Promise.all([
        adminApi.get<ConditionListResponse>("/conditions"),
        adminApi.get<InstructionListResponse>("/instructions"),
        adminApi.get<QuestionnaireListResponse>("/questionnaires"),
      ]);
      setOptions({
        conditions: conditions.conditions.filter((item) => item.status === "published"),
        instructions: instructions.instructions.filter((item) => item.status === "published"),
        questionnaires: questionnaires.questionnaires.filter((item) => item.status === "published"),
      });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return { options, loading, error };
}

export function defaultStartInput(): string {
  const date = new Date(Date.now() + 60 * 60 * 1000);
  date.setSeconds(0, 0);
  return toShanghaiInput(date.toISOString());
}

export function defaultRoomForm(options: RoomOptions): RoomFormState {
  const instructionP1 = options.instructions.find((item) => item.role === 1);
  const instructionP2 = options.instructions.find((item) => item.role === 2);
  return {
    internalLabel: "",
    startsAt: defaultStartInput(),
    conditionVersionId: options.conditions[0]?.id ?? "",
    instructionVersionP1Id: instructionP1?.id ?? "",
    instructionVersionP2Id: instructionP2?.id ?? "",
    questionnaireVersionId: options.questionnaires[0]?.id ?? "",
    basePay: "40.00",
    performanceRate: "0.00",
    showupPay: "10.00",
    waitMinutes: "15",
    reconnectMinutes: "10",
  };
}

export function roomFormFromSummary(room: RoomSummary): RoomFormState {
  return {
    internalLabel: room.internalLabel,
    startsAt: toShanghaiInput(room.startsAt),
    conditionVersionId: room.condition.id,
    instructionVersionP1Id: room.instructions.player1.id,
    instructionVersionP2Id: room.instructions.player2.id,
    questionnaireVersionId: room.questionnaire.id,
    basePay: yuanFromCents(room.basePayCents),
    performanceRate: yuanFromCents(room.performanceRateCents),
    showupPay: yuanFromCents(room.showupPayCents),
    waitMinutes: String(Math.round(room.waitWindowSeconds / 60)),
    reconnectMinutes: String(Math.round(room.reconnectWindowSeconds / 60)),
  };
}

export function buildRoomPayload(form: RoomFormState): RoomPayloadResult {
  const errors: Record<string, string> = {};
  const internalLabel = form.internalLabel.trim();
  if (!internalLabel) errors.internalLabel = "请填写内部名称";

  let startsAt = "";
  if (!form.startsAt) {
    errors.startsAt = "请选择开始时间";
  } else {
    try {
      startsAt = fromShanghaiInput(form.startsAt);
      if (Number.isNaN(new Date(startsAt).getTime())) throw new Error("invalid");
    } catch {
      errors.startsAt = "开始时间格式不正确";
    }
  }
  if (!form.conditionVersionId) errors.conditionVersionId = "请选择条件版本";
  if (!form.instructionVersionP1Id) errors.instructionVersionP1Id = "请选择玩家 1 指导语";
  if (!form.instructionVersionP2Id) errors.instructionVersionP2Id = "请选择玩家 2 指导语";
  if (!form.questionnaireVersionId) errors.questionnaireVersionId = "请选择问卷版本";

  const basePay = centsFromYuan(form.basePay);
  if (basePay === null) errors.basePay = "基础费必须是非负金额";
  const performanceRate = centsFromYuan(form.performanceRate);
  if (performanceRate === null) errors.performanceRate = "绩效单价必须是非负金额";
  const showupPay = centsFromYuan(form.showupPay);
  if (showupPay === null) errors.showupPay = "到场费必须是非负金额";

  const waitMinutes = Number(form.waitMinutes);
  if (!Number.isFinite(waitMinutes) || waitMinutes <= 0) {
    errors.waitMinutes = "等待窗口必须大于 0 分钟";
  }
  const reconnectMinutes = Number(form.reconnectMinutes);
  if (!Number.isFinite(reconnectMinutes) || reconnectMinutes <= 0) {
    errors.reconnectMinutes = "重连窗口必须大于 0 分钟";
  }

  if (Object.keys(errors).length > 0) {
    return { payload: null, errors };
  }

  return {
    errors,
    payload: {
      internalLabel,
      startsAt,
      conditionVersionId: form.conditionVersionId,
      instructionVersionP1Id: form.instructionVersionP1Id,
      instructionVersionP2Id: form.instructionVersionP2Id,
      questionnaireVersionId: form.questionnaireVersionId,
      basePayCents: basePay as number,
      performanceRateCents: performanceRate as number,
      showupPayCents: showupPay as number,
      waitWindowSeconds: Math.round(waitMinutes * 60),
      reconnectWindowSeconds: Math.round(reconnectMinutes * 60),
    },
  };
}

export function RoomConfigFields({
  form,
  errors,
  options,
  onChange,
  lockStartsAt = false,
  disabled = false,
}: {
  form: RoomFormState;
  errors: Record<string, string>;
  options: RoomOptions;
  onChange: (next: RoomFormState) => void;
  lockStartsAt?: boolean;
  disabled?: boolean;
}) {
  const set = <K extends keyof RoomFormState>(key: K, value: RoomFormState[K]) => {
    onChange({ ...form, [key]: value });
  };

  if (options.conditions.length === 0 && options.instructions.length === 0 && options.questionnaires.length === 0) {
    return (
      <div className="admin-hint">
        尚无可选版本。请先在条件、指导语和问卷页面创建并发布版本。
      </div>
    );
  }

  const p1Options = options.instructions.filter((item) => item.role === 1);
  const p2Options = options.instructions.filter((item) => item.role === 2);

  return (
    <div>
      <div className="admin-form-row">
        <Field label="内部名称" htmlFor="room-internal-label" error={errors.internalLabel}>
          <input
            id="room-internal-label"
            className="admin-input"
            value={form.internalLabel}
            onChange={(event) => set("internalLabel", event.target.value)}
            disabled={disabled}
            placeholder="例如：10 月 20 日 第一场"
            data-testid="room-form-label"
          />
        </Field>
        <Field
          label="开始时间（Asia/Shanghai）"
          htmlFor="room-starts-at"
          error={errors.startsAt}
          hint={lockStartsAt ? "房间已进入等待阶段，开始时间已锁定。" : undefined}
        >
          <input
            id="room-starts-at"
            className="admin-input"
            type="datetime-local"
            value={form.startsAt}
            onChange={(event) => set("startsAt", event.target.value)}
            disabled={disabled || lockStartsAt}
            data-testid="room-form-starts-at"
          />
        </Field>
      </div>
      <div className="admin-form-row admin-form-row-3">
        <Field label="条件版本" htmlFor="room-condition" error={errors.conditionVersionId}>
          <select
            id="room-condition"
            className="admin-select"
            value={form.conditionVersionId}
            onChange={(event) => set("conditionVersionId", event.target.value)}
            disabled={disabled}
            data-testid="room-form-condition"
          >
            <option value="">请选择</option>
            {options.conditions.map((condition) => (
              <option key={condition.id} value={condition.id}>
                {condition.name} v{condition.version}
              </option>
            ))}
          </select>
        </Field>
        <Field label="玩家 1 指导语" htmlFor="room-instruction-p1" error={errors.instructionVersionP1Id}>
          <select
            id="room-instruction-p1"
            className="admin-select"
            value={form.instructionVersionP1Id}
            onChange={(event) => set("instructionVersionP1Id", event.target.value)}
            disabled={disabled}
            data-testid="room-form-instruction-p1"
          >
            <option value="">请选择</option>
            {p1Options.map((instruction) => (
              <option key={instruction.id} value={instruction.id}>
                {instruction.name} v{instruction.version}
              </option>
            ))}
          </select>
        </Field>
        <Field label="玩家 2 指导语" htmlFor="room-instruction-p2" error={errors.instructionVersionP2Id}>
          <select
            id="room-instruction-p2"
            className="admin-select"
            value={form.instructionVersionP2Id}
            onChange={(event) => set("instructionVersionP2Id", event.target.value)}
            disabled={disabled}
            data-testid="room-form-instruction-p2"
          >
            <option value="">请选择</option>
            {p2Options.map((instruction) => (
              <option key={instruction.id} value={instruction.id}>
                {instruction.name} v{instruction.version}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label="问卷版本" htmlFor="room-questionnaire" error={errors.questionnaireVersionId}>
        <select
          id="room-questionnaire"
          className="admin-select"
          value={form.questionnaireVersionId}
          onChange={(event) => set("questionnaireVersionId", event.target.value)}
          disabled={disabled}
          data-testid="room-form-questionnaire"
        >
          <option value="">请选择</option>
          {options.questionnaires.map((questionnaire) => (
            <option key={questionnaire.id} value={questionnaire.id}>
              {questionnaire.name} v{questionnaire.version}
            </option>
          ))}
        </select>
      </Field>
      <div className="admin-form-row admin-form-row-3">
        <Field label="基础费（元）" htmlFor="room-base-pay" error={errors.basePay}>
          <input
            id="room-base-pay"
            className="admin-input"
            type="number"
            min="0"
            step="0.01"
            value={form.basePay}
            onChange={(event) => set("basePay", event.target.value)}
            disabled={disabled}
            data-testid="room-form-base-pay"
          />
        </Field>
        <Field label="绩效单价（元）" htmlFor="room-performance-rate" error={errors.performanceRate}>
          <input
            id="room-performance-rate"
            className="admin-input"
            type="number"
            min="0"
            step="0.01"
            value={form.performanceRate}
            onChange={(event) => set("performanceRate", event.target.value)}
            disabled={disabled}
            data-testid="room-form-performance-rate"
          />
        </Field>
        <Field label="到场费（元）" htmlFor="room-showup-pay" error={errors.showupPay}>
          <input
            id="room-showup-pay"
            className="admin-input"
            type="number"
            min="0"
            step="0.01"
            value={form.showupPay}
            onChange={(event) => set("showupPay", event.target.value)}
            disabled={disabled}
            data-testid="room-form-showup-pay"
          />
        </Field>
      </div>
      <div className="admin-form-row">
        <Field label="等待窗口（分钟）" htmlFor="room-wait" error={errors.waitMinutes}>
          <input
            id="room-wait"
            className="admin-input"
            type="number"
            min="1"
            step="1"
            value={form.waitMinutes}
            onChange={(event) => set("waitMinutes", event.target.value)}
            disabled={disabled}
            data-testid="room-form-wait"
          />
        </Field>
        <Field label="重连窗口（分钟）" htmlFor="room-reconnect" error={errors.reconnectMinutes}>
          <input
            id="room-reconnect"
            className="admin-input"
            type="number"
            min="1"
            step="1"
            value={form.reconnectMinutes}
            onChange={(event) => set("reconnectMinutes", event.target.value)}
            disabled={disabled}
            data-testid="room-form-reconnect"
          />
        </Field>
      </div>
      <p className="admin-hint" style={{ margin: 0 }}>
        金额以元输入，保存时转换为整数分。开始时间按 Asia/Shanghai 解释。
      </p>
    </div>
  );
}

export function OptionsLoading({ error }: { error: string | null }) {
  if (error) {
    return <div className="admin-error">版本选项加载失败：{error}</div>;
  }
  return <LoadingBlock rows={2} label="正在加载版本选项" />;
}
