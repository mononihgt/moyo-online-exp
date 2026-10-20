import { useCallback, useEffect, useState } from "react";
import type {
  InstructionVersion,
  MapGroupVersion,
  QuestionnaireVersion,
  RoomSummary,
  VersionStatus,
} from "../shared/types";
import { formatMoney } from "../shared/format";
import { adminApi, errorMessage } from "./api";
import type {
  InstructionListResponse,
  MapGroupListResponse,
  QuestionnaireListResponse,
  RoomDraftPayload,
} from "./types";
import {
  Field,
  LoadingBlock,
  fromShanghaiInput,
  toShanghaiInput,
} from "./ui";

export interface RoomOptions {
  mapGroups: MapGroupVersion[];
  instructions: InstructionVersion[];
  questionnaires: QuestionnaireVersion[];
}

export interface RoomFormState {
  internalLabel: string;
  startsAt: string;
  mapGroupVersionId: string;
  instructionVersionP1Id: string;
  instructionVersionP2Id: string;
  questionnaireVersionId: string;
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
    mapGroups: [],
    instructions: [],
    questionnaires: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [mapGroups, instructions, questionnaires] = await Promise.all([
        adminApi.get<MapGroupListResponse>("/map-groups"),
        adminApi.get<InstructionListResponse>("/instructions"),
        adminApi.get<QuestionnaireListResponse>("/questionnaires"),
      ]);
      setOptions({
        mapGroups: mapGroups.mapGroups.filter((item) => item.status !== "draft"),
        instructions: instructions.instructions.filter((item) => item.status !== "draft"),
        questionnaires: questionnaires.questionnaires.filter((item) => item.status !== "draft"),
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

function archivedSuffix(status: VersionStatus): string {
  return status === "archived" ? "（已归档）" : "";
}

export function defaultStartInput(): string {
  const date = new Date(Date.now() + 60 * 60 * 1000);
  date.setSeconds(0, 0);
  return toShanghaiInput(date.toISOString());
}

export function mapGroupVersionIdOf(group: MapGroupVersion): string {
  return group.versionId;
}

export function instructionsForGroup(
  options: RoomOptions,
  mapGroupVersionId: string,
  role: 1 | 2,
): InstructionVersion[] {
  const group = options.mapGroups.find(
    (item) => item.versionId === mapGroupVersionId || item.id === mapGroupVersionId,
  );
  if (!group) return [];
  return options.instructions.filter(
    (item) => item.role === role && item.mapGroupPrefix === group.name,
  );
}

export function defaultRoomForm(options: RoomOptions): RoomFormState {
  const mapGroup = options.mapGroups[0];
  const mapGroupVersionId = mapGroup ? mapGroupVersionIdOf(mapGroup) : "";
  return {
    internalLabel: "",
    startsAt: defaultStartInput(),
    mapGroupVersionId,
    instructionVersionP1Id: instructionsForGroup(options, mapGroupVersionId, 1)[0]?.versionId ?? "",
    instructionVersionP2Id: instructionsForGroup(options, mapGroupVersionId, 2)[0]?.versionId ?? "",
    questionnaireVersionId: options.questionnaires[0]?.versionId ?? "",
    waitMinutes: "10",
    reconnectMinutes: "10",
  };
}

export function roomFormFromSummary(room: RoomSummary): RoomFormState {
  return {
    internalLabel: room.internalLabel,
    startsAt: toShanghaiInput(room.startsAt),
    mapGroupVersionId: room.mapGroup.versionId,
    instructionVersionP1Id: room.instructions.player1.id,
    instructionVersionP2Id: room.instructions.player2.id,
    questionnaireVersionId: room.questionnaire.id,
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

  if (!form.mapGroupVersionId) errors.mapGroupVersionId = "请选择地图组";
  if (!form.instructionVersionP1Id) errors.instructionVersionP1Id = "请选择玩家 1 指导语";
  if (!form.instructionVersionP2Id) errors.instructionVersionP2Id = "请选择玩家 2 指导语";
  if (!form.questionnaireVersionId) errors.questionnaireVersionId = "请选择问卷版本";

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
      mapGroupVersionId: form.mapGroupVersionId,
      instructionVersionP1Id: form.instructionVersionP1Id,
      instructionVersionP2Id: form.instructionVersionP2Id,
      questionnaireVersionId: form.questionnaireVersionId,
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

  const selectedGroup = options.mapGroups.find(
    (item) => item.versionId === form.mapGroupVersionId || item.id === form.mapGroupVersionId,
  );
  const p1Options = selectedGroup ? instructionsForGroup(options, form.mapGroupVersionId, 1) : [];
  const p2Options = selectedGroup ? instructionsForGroup(options, form.mapGroupVersionId, 2) : [];

  function changeMapGroup(nextId: string) {
    const group = options.mapGroups.find(
      (item) => item.versionId === nextId || item.id === nextId,
    );
    const prefix = group?.name ?? "";
    const validForGroup = (instructionId: string, role: 1 | 2) =>
      options.instructions.some(
        (item) =>
          item.versionId === instructionId && item.role === role && item.mapGroupPrefix === prefix,
      );
    const nextP1 = validForGroup(form.instructionVersionP1Id, 1)
      ? form.instructionVersionP1Id
      : options.instructions.find(
          (item) => item.role === 1 && item.mapGroupPrefix === prefix,
        )?.versionId ?? "";
    const nextP2 = validForGroup(form.instructionVersionP2Id, 2)
      ? form.instructionVersionP2Id
      : options.instructions.find(
          (item) => item.role === 2 && item.mapGroupPrefix === prefix,
        )?.versionId ?? "";
    onChange({
      ...form,
      mapGroupVersionId: nextId,
      instructionVersionP1Id: nextP1,
      instructionVersionP2Id: nextP2,
    });
  }

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
          hint={
            lockStartsAt
              ? "非草稿房间不可修改开始时间。"
              : "开始时间之后不能修改房间配置。"
          }
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
      <div className="admin-form-row">
        <Field
          label="地图组"
          htmlFor="room-map-group"
          error={errors.mapGroupVersionId}
          hint={selectedGroup ? `容量固定为 2；地图组尺寸 ${selectedGroup.rows} × ${selectedGroup.cols}` : undefined}
        >
          <select
            id="room-map-group"
            className="admin-select"
            value={form.mapGroupVersionId}
            onChange={(event) => changeMapGroup(event.target.value)}
            disabled={disabled}
            data-testid="room-form-map-group"
          >
            <option value="">请选择</option>
            {options.mapGroups.map((group) => (
              <option key={group.versionId} value={group.versionId}>
                {group.name} v{group.version}（{group.mode === "both" ? "Both" : "A/B"}）
                {archivedSuffix(group.status)}
              </option>
            ))}
          </select>
        </Field>
        <div className="admin-field">
          <span className="admin-label">付款参数（继承自地图组）</span>
          {selectedGroup ? (
            <div className="admin-hint" style={{ lineHeight: 1.7 }}>
              基础费 {formatMoney(selectedGroup.payment.basePayCents)} · 绩效单价{" "}
              {formatMoney(selectedGroup.payment.performanceRateCents)} / 士兵 · 绩效保底{" "}
              {formatMoney(selectedGroup.payment.performanceFloorCents)} · 绩效上限{" "}
              {formatMoney(selectedGroup.payment.performanceCapCents)} · 到场费{" "}
              {formatMoney(selectedGroup.payment.showupPayCents)}
            </div>
          ) : (
            <div className="admin-hint">选择地图组后显示继承的付款参数。</div>
          )}
        </div>
      </div>
      <div className="admin-form-row admin-form-row-3">
        <Field
          label="玩家 1 指导语"
          htmlFor="room-instruction-p1"
          error={errors.instructionVersionP1Id}
          hint={selectedGroup && p1Options.length === 0 ? "该地图组前缀下暂无可用指导语。" : undefined}
        >
          <select
            id="room-instruction-p1"
            className="admin-select"
            value={form.instructionVersionP1Id}
            onChange={(event) => set("instructionVersionP1Id", event.target.value)}
            disabled={disabled || !selectedGroup}
            data-testid="room-form-instruction-p1"
          >
            <option value="">请选择</option>
            {p1Options.map((instruction) => (
              <option key={instruction.versionId} value={instruction.versionId}>
                {instruction.name} v{instruction.version}
                {archivedSuffix(instruction.status)}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="玩家 2 指导语"
          htmlFor="room-instruction-p2"
          error={errors.instructionVersionP2Id}
          hint={selectedGroup && p2Options.length === 0 ? "该地图组前缀下暂无可用指导语。" : undefined}
        >
          <select
            id="room-instruction-p2"
            className="admin-select"
            value={form.instructionVersionP2Id}
            onChange={(event) => set("instructionVersionP2Id", event.target.value)}
            disabled={disabled || !selectedGroup}
            data-testid="room-form-instruction-p2"
          >
            <option value="">请选择</option>
            {p2Options.map((instruction) => (
              <option key={instruction.versionId} value={instruction.versionId}>
                {instruction.name} v{instruction.version}
                {archivedSuffix(instruction.status)}
              </option>
            ))}
          </select>
        </Field>
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
              <option key={questionnaire.versionId} value={questionnaire.versionId}>
                {questionnaire.name} v{questionnaire.version}
                {archivedSuffix(questionnaire.status)}
              </option>
            ))}
          </select>
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
      {options.mapGroups.length === 0 ? (
        <p className="admin-hint">暂无可用地图组。请先在地图组页面创建并发布版本。</p>
      ) : null}
      {options.instructions.length === 0 ? (
        <p className="admin-hint">暂无可用指导语。请先在指导语页面创建并发布版本。</p>
      ) : null}
      {options.questionnaires.length === 0 ? (
        <p className="admin-hint">暂无可用问卷。请先在问卷页面创建并发布版本。</p>
      ) : null}
      <p className="admin-hint" style={{ margin: 0 }}>
        付款参数与容量继承自所选地图组。开始时间按 Asia/Shanghai 解释。
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
