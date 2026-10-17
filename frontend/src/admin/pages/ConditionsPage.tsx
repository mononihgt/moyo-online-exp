import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import {
  CheckCircle2,
  Copy,
  ImagePlus,
  Lock,
  Plus,
  Save,
  Upload,
} from "lucide-react";
import type {
  ConditionCell,
  ConditionVersion,
  ConditionVisual,
  MediaAsset,
  ReinforcementOverrides,
  TrialParam,
} from "../../shared/types";
import { formatDateTime } from "../../shared/format";
import { adminApi, errorMessage, imageUploadForm } from "../api";
import type {
  ConditionDraftPayload,
  ConditionListResponse,
  ConditionResponse,
  MediaListResponse,
  MediaUploadResponse,
} from "../types";
import {
  EmptyState,
  ErrorNotice,
  Field,
  InlineNotice,
  JsonDetails,
  LoadingBlock,
  Modal,
  PageHeader,
  StatusChip,
  VersionStatusChip,
  formatBytes,
  useUi,
} from "../ui";

type Selection = string | "new" | null;
type PlayerKey = "player1" | "player2";
type ViewMode = PlayerKey | "shared";
type Brush =
  | "select"
  | "owner1"
  | "owner2"
  | "owner0"
  | "color"
  | "background"
  | "soldiers"
  | "reinforcementA"
  | "reinforcementB";

interface ConditionFormState {
  name: string;
  description: string;
  rows: string;
  cols: string;
  cells: ConditionCell[];
  visuals: { player1: ConditionVisual[]; player2: ConditionVisual[] };
  baseAIndex: number;
  baseBIndex: number;
  practiceTrials: string;
  formalTrials: string;
  turnCount: string;
  turnSeconds: string;
  restSeconds: string;
  randomizeFormal: boolean;
  trialParams: TrialParam[];
  metadata: Record<string, unknown>;
}

const HEX_COLOR = /^#[0-9A-Fa-f]{6}$/;
const DEFAULT_VISUAL_COLOR = "#D6DCE4";
const PRESET_IDS = new Set(["ref0", "ref1", "ref2", "ref3", "ref4", "ref5", "asym"]);

function emptyCell(row: number, col: number, owner: 0 | 1 | 2 = 0): ConditionCell {
  return {
    row,
    col,
    initialOwner: owner,
    initialSoldiers: 0,
    reinforcementA: 0,
    reinforcementB: 0,
  };
}

function buildDefaultGrid(rows: number, cols: number): ConditionCell[] {
  const cells: ConditionCell[] = [];
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      cells.push(emptyCell(row, col));
    }
  }
  return cells;
}

function buildDefaultVisuals(rows: number, cols: number): {
  player1: ConditionVisual[];
  player2: ConditionVisual[];
} {
  const total = rows * cols;
  const layer: ConditionVisual[] = Array.from({ length: total }, () => ({
    color: DEFAULT_VISUAL_COLOR,
    backgroundAssetId: null,
  }));
  return {
    player1: layer.map((item) => ({ ...item })),
    player2: layer.map((item) => ({ ...item })),
  };
}

function normalizeTrialParams(
  existing: TrialParam[],
  practiceTrials: number,
  formalTrials: number,
): TrialParam[] {
  const total = practiceTrials + formalTrials;
  const params: TrialParam[] = [];
  for (let index = 0; index < total; index += 1) {
    const isPractice = index < practiceTrials;
    const source = existing[index];
    params.push({
      sourceIndex: index,
      isPractice,
      formalTrial: isPractice ? 0 : index - practiceTrials + 1,
      baseSoldiersA: source?.baseSoldiersA ?? 7,
      baseSoldiersB: source?.baseSoldiersB ?? 7,
      reinforcementOverrides: source?.reinforcementOverrides
        ? {
            player1: source.reinforcementOverrides.player1?.map((entry) => ({ ...entry })),
            player2: source.reinforcementOverrides.player2?.map((entry) => ({ ...entry })),
          }
        : null,
    });
  }
  return params;
}

function newConditionForm(): ConditionFormState {
  const rows = 6;
  const cols = 6;
  const cells = buildDefaultGrid(rows, cols);
  const baseAIndex = 0;
  const baseBIndex = rows * cols - 1;
  cells[baseAIndex] = { ...cells[baseAIndex], initialOwner: 1, initialSoldiers: 10 };
  cells[baseBIndex] = { ...cells[baseBIndex], initialOwner: 2, initialSoldiers: 10 };
  return {
    name: "",
    description: "",
    rows: String(rows),
    cols: String(cols),
    cells,
    visuals: buildDefaultVisuals(rows, cols),
    baseAIndex,
    baseBIndex,
    practiceTrials: "1",
    formalTrials: "6",
    turnCount: "20",
    turnSeconds: "30",
    restSeconds: "60",
    randomizeFormal: true,
    trialParams: normalizeTrialParams([], 1, 6),
    metadata: {},
  };
}

function formFromCondition(condition: ConditionVersion): ConditionFormState {
  return {
    name: condition.name,
    description: condition.description ?? "",
    rows: String(condition.rows),
    cols: String(condition.cols),
    cells: condition.cells.map((cell) => ({ ...cell })),
    visuals: {
      player1: condition.visuals.player1.map((item) => ({ ...item })),
      player2: condition.visuals.player2.map((item) => ({ ...item })),
    },
    baseAIndex: condition.baseAIndex,
    baseBIndex: condition.baseBIndex,
    practiceTrials: String(condition.practiceTrials),
    formalTrials: String(condition.formalTrials),
    turnCount: String(condition.turnCount),
    turnSeconds: String(condition.turnSeconds),
    restSeconds: String(condition.restSeconds),
    randomizeFormal: condition.randomizeFormal,
    trialParams: condition.trialParams.map((param) => ({
      ...param,
      reinforcementOverrides: param.reinforcementOverrides
        ? {
            player1: param.reinforcementOverrides.player1?.map((entry) => ({ ...entry })),
            player2: param.reinforcementOverrides.player2?.map((entry) => ({ ...entry })),
          }
        : null,
    })),
    metadata: JSON.parse(JSON.stringify(condition.metadata ?? {})) as Record<string, unknown>,
  };
}

function resizeGrid(base: ConditionFormState, rows: number, cols: number): ConditionFormState {
  const oldRows = Number(base.rows);
  const oldCols = Number(base.cols);
  const safeOldRows = Number.isInteger(oldRows) && oldRows > 0 ? oldRows : rows;
  const safeOldCols = Number.isInteger(oldCols) && oldCols > 0 ? oldCols : cols;
  const total = rows * cols;
  const cells: ConditionCell[] = [];
  const player1: ConditionVisual[] = [];
  const player2: ConditionVisual[] = [];
  for (let index = 0; index < total; index += 1) {
    const row = Math.floor(index / cols);
    const col = index % cols;
    const oldIndex = row < safeOldRows && col < safeOldCols ? row * safeOldCols + col : -1;
    if (oldIndex >= 0 && base.cells[oldIndex]) {
      cells.push({ ...base.cells[oldIndex], row, col });
    } else {
      cells.push(emptyCell(row, col));
    }
    const oldVisualA = oldIndex >= 0 ? base.visuals.player1[oldIndex] : undefined;
    const oldVisualB = oldIndex >= 0 ? base.visuals.player2[oldIndex] : undefined;
    player1.push(
      oldVisualA
        ? { ...oldVisualA }
        : { color: DEFAULT_VISUAL_COLOR, backgroundAssetId: null },
    );
    player2.push(
      oldVisualB
        ? { ...oldVisualB }
        : { color: DEFAULT_VISUAL_COLOR, backgroundAssetId: null },
    );
  }
  let baseAIndex = base.baseAIndex;
  if (!Number.isInteger(baseAIndex) || baseAIndex < 0 || baseAIndex >= total) {
    baseAIndex = 0;
  }
  let baseBIndex = base.baseBIndex;
  if (
    !Number.isInteger(baseBIndex) ||
    baseBIndex < 0 ||
    baseBIndex >= total ||
    baseBIndex === baseAIndex
  ) {
    baseBIndex = baseAIndex === total - 1 ? 0 : total - 1;
  }
  cells[baseAIndex] = { ...cells[baseAIndex], initialOwner: 1 };
  cells[baseBIndex] = { ...cells[baseBIndex], initialOwner: 2 };
  return {
    ...base,
    rows: String(rows),
    cols: String(cols),
    cells,
    visuals: { player1, player2 },
    baseAIndex,
    baseBIndex,
  };
}

function nonNegativeInt(value: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 0;
  return Math.max(0, Math.round(parsed));
}

function parsePositiveInt(value: string): number | null {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) return null;
  return parsed;
}

function parseNonNegativeInt(value: string): number | null {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) return null;
  return parsed;
}

function presetIdOf(condition: ConditionVersion): string | null {
  const value = condition.metadata?.conditionId;
  return typeof value === "string" &&
    PRESET_IDS.has(value) &&
    condition.name === value
    ? value
    : null;
}

function overrideEntryCount(overrides: ReinforcementOverrides | null, key: PlayerKey): number {
  return overrides?.[key]?.length ?? 0;
}

function parseOverridesText(
  text: string,
  totalCells: number,
): { value: ReinforcementOverrides | null; error: string | null } {
  const trimmed = text.trim();
  if (trimmed === "" || trimmed === "null") return { value: null, error: null };
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return { value: null, error: "不是有效的 JSON" };
  }
  if (parsed === null) return { value: null, error: null };
  if (typeof parsed !== "object" || Array.isArray(parsed)) {
    return { value: null, error: "覆盖值必须是对象或 null" };
  }
  const source = parsed as Record<string, unknown>;
  const result: ReinforcementOverrides = {};
  for (const key of ["player1", "player2"] as const) {
    const entries = source[key];
    if (entries === undefined || entries === null) continue;
    if (!Array.isArray(entries)) {
      return { value: null, error: `${key} 必须是数组` };
    }
    const seen = new Set<number>();
    const normalized: { cellIndex: number; value: number }[] = [];
    for (const entry of entries) {
      if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
        return { value: null, error: `${key} 的条目必须是对象` };
      }
      const record = entry as Record<string, unknown>;
      const cellIndex = record.cellIndex;
      const value = record.value;
      if (!Number.isInteger(cellIndex) || (cellIndex as number) < 0 || (cellIndex as number) >= totalCells) {
        return { value: null, error: `${key}.cellIndex 超出网格范围` };
      }
      if (seen.has(cellIndex as number)) {
        return { value: null, error: `${key} 存在重复 cellIndex` };
      }
      seen.add(cellIndex as number);
      if (!Number.isInteger(value) || (value as number) < 0) {
        return { value: null, error: `${key}.value 必须是非负整数` };
      }
      normalized.push({ cellIndex: cellIndex as number, value: value as number });
    }
    result[key] = normalized;
  }
  return { value: result, error: null };
}

function buildConditionPayload(
  form: ConditionFormState,
  assetIds: Set<string> | null,
): { payload: ConditionDraftPayload | null; errors: string[] } {
  const errors: string[] = [];
  const name = form.name.trim();
  if (!name) errors.push("请填写条件名称");

  const rows = Number(form.rows);
  const cols = Number(form.cols);
  const rowsValid = Number.isInteger(rows) && rows >= 2 && rows <= 20;
  const colsValid = Number.isInteger(cols) && cols >= 2 && cols <= 20;
  if (!rowsValid || !colsValid) {
    errors.push("行数和列数必须是 2 到 20 之间的整数");
  }
  const total = rowsValid && colsValid ? rows * cols : 0;
  if (total > 100) errors.push("网格总格数不能超过 100");

  const practiceTrials = parseNonNegativeInt(form.practiceTrials);
  if (practiceTrials === null) errors.push("练习 Trial 数必须是非负整数");
  const formalTrials = parsePositiveInt(form.formalTrials);
  if (formalTrials === null) errors.push("正式 Trial 数必须是大于 0 的整数");
  const turnCount = parsePositiveInt(form.turnCount);
  if (turnCount === null) errors.push("每 Trial 回合数必须大于 0");
  const turnSeconds = parsePositiveInt(form.turnSeconds);
  if (turnSeconds === null) errors.push("回合秒数必须大于 0");
  const restSeconds = parsePositiveInt(form.restSeconds);
  if (restSeconds === null) errors.push("休息秒数必须大于 0");

  if (total > 0) {
    if (form.cells.length !== total) {
      errors.push(`格子数量必须等于 rows × cols = ${total}`);
    } else {
      form.cells.forEach((cell, index) => {
        if (cell.row !== Math.floor(index / cols) || cell.col !== index % cols) {
          errors.push(`第 ${index + 1} 格的 row/col 与行优先索引不一致`);
        }
        if (![0, 1, 2].includes(cell.initialOwner)) {
          errors.push(`第 ${index + 1} 格的归属必须是 0、1 或 2`);
        }
        for (const [key, value] of [
          ["初始兵力", cell.initialSoldiers],
          ["玩家 1 增援", cell.reinforcementA],
          ["玩家 2 增援", cell.reinforcementB],
        ] as const) {
          if (!Number.isInteger(value) || value < 0) {
            errors.push(`第 ${index + 1} 格的${key}必须是非负整数`);
          }
        }
      });
    }

    for (const [label, layer] of [
      ["玩家 1", form.visuals.player1],
      ["玩家 2", form.visuals.player2],
    ] as const) {
      if (layer.length !== total) {
        errors.push(`${label}的视觉层长度必须等于 ${total}`);
        continue;
      }
      let hasContent = false;
      layer.forEach((visual, index) => {
        if (visual.color !== null && !HEX_COLOR.test(visual.color)) {
          errors.push(`${label}第 ${index + 1} 格的颜色必须是十六进制颜色`);
        }
        if (
          visual.backgroundAssetId !== null &&
          assetIds !== null &&
          !assetIds.has(visual.backgroundAssetId)
        ) {
          errors.push(`${label}第 ${index + 1} 格引用的背景资产不存在`);
        }
        if (visual.color !== null || visual.backgroundAssetId !== null) {
          hasContent = true;
        }
      });
      if (!hasContent) errors.push(`${label}的视觉不能全部为空`);
    }

    if (
      !Number.isInteger(form.baseAIndex) ||
      form.baseAIndex < 0 ||
      form.baseAIndex >= total ||
      !Number.isInteger(form.baseBIndex) ||
      form.baseBIndex < 0 ||
      form.baseBIndex >= total
    ) {
      errors.push("基地索引超出网格范围");
    } else if (form.baseAIndex === form.baseBIndex) {
      errors.push("两个基地不能重合");
    } else {
      if (form.cells[form.baseAIndex]?.initialOwner !== 1) {
        errors.push("基地 A 的初始归属必须是玩家 1");
      }
      if (form.cells[form.baseBIndex]?.initialOwner !== 2) {
        errors.push("基地 B 的初始归属必须是玩家 2");
      }
    }
    const owners = new Set(form.cells.map((cell) => cell.initialOwner));
    if (!owners.has(1) || !owners.has(2)) {
      errors.push("每名玩家至少需要一个初始归属格");
    }
  }

  if (practiceTrials !== null && formalTrials !== null) {
    const expected = practiceTrials + formalTrials;
    if (form.trialParams.length !== expected) {
      errors.push(`Trial 参数数量必须等于 ${expected}`);
    } else {
      form.trialParams.forEach((param, index) => {
        if (param.sourceIndex !== index) {
          errors.push(`Trial 参数 ${index + 1} 的 sourceIndex 必须是 ${index}`);
        }
        const isPractice = index < practiceTrials;
        if (param.isPractice !== isPractice) {
          errors.push(`Trial 参数 ${index + 1} 的练习标记与练习 Trial 数不一致`);
        }
        const expectedFormal = isPractice ? 0 : index - practiceTrials + 1;
        if (param.formalTrial !== expectedFormal) {
          errors.push(`Trial 参数 ${index + 1} 的正式 Trial 编号必须是 ${expectedFormal}`);
        }
        if (!Number.isInteger(param.baseSoldiersA) || param.baseSoldiersA <= 0) {
          errors.push(`Trial 参数 ${index + 1} 的玩家 1 初始兵力必须大于 0`);
        }
        if (!Number.isInteger(param.baseSoldiersB) || param.baseSoldiersB <= 0) {
          errors.push(`Trial 参数 ${index + 1} 的玩家 2 初始兵力必须大于 0`);
        }
        const overrides = param.reinforcementOverrides;
        if (overrides !== null) {
          if (typeof overrides !== "object" || Array.isArray(overrides)) {
            errors.push(`Trial 参数 ${index + 1} 的 reinforcementOverrides 必须是对象或 null`);
          } else {
            for (const key of ["player1", "player2"] as const) {
              const entries = overrides[key];
              if (entries === undefined) continue;
              const seen = new Set<number>();
              entries.forEach((entry) => {
                if (
                  !Number.isInteger(entry.cellIndex) ||
                  entry.cellIndex < 0 ||
                  entry.cellIndex >= total
                ) {
                  errors.push(`Trial 参数 ${index + 1} 的 ${key}.cellIndex 超出网格范围`);
                } else if (seen.has(entry.cellIndex)) {
                  errors.push(`Trial 参数 ${index + 1} 的 ${key} 存在重复 cellIndex`);
                }
                seen.add(entry.cellIndex);
                if (!Number.isInteger(entry.value) || entry.value < 0) {
                  errors.push(`Trial 参数 ${index + 1} 的 ${key}.value 必须是非负整数`);
                }
              });
            }
          }
        }
      });
    }
  }

  if (errors.length > 0) {
    return { payload: null, errors };
  }

  return {
    errors: [],
    payload: {
      name,
      description: form.description.trim() ? form.description.trim() : null,
      rows,
      cols,
      cells: form.cells.map((cell) => ({ ...cell })),
      visuals: {
        player1: form.visuals.player1.map((item) => ({ ...item })),
        player2: form.visuals.player2.map((item) => ({ ...item })),
      },
      baseAIndex: form.baseAIndex,
      baseBIndex: form.baseBIndex,
      practiceTrials: practiceTrials as number,
      formalTrials: formalTrials as number,
      turnCount: turnCount as number,
      turnSeconds: turnSeconds as number,
      restSeconds: restSeconds as number,
      randomizeFormal: form.randomizeFormal,
      trialParams: form.trialParams.map((param) => ({
        ...param,
        reinforcementOverrides: param.reinforcementOverrides
          ? {
              player1: param.reinforcementOverrides.player1?.map((entry) => ({ ...entry })),
              player2: param.reinforcementOverrides.player2?.map((entry) => ({ ...entry })),
            }
          : null,
      })),
      metadata: { ...form.metadata },
    },
  };
}

function ConditionBoard({
  cells,
  visuals,
  baseAIndex,
  baseBIndex,
  selectedIndex,
  assetUrls,
  interactive,
  painting,
  onActivate,
  onPointerEnterCell,
  onPointerStop,
  label,
}: {
  cells: ConditionCell[];
  visuals: ConditionVisual[];
  baseAIndex: number;
  baseBIndex: number;
  selectedIndex: number | null;
  assetUrls: Map<string, string>;
  interactive: boolean;
  painting?: boolean;
  onActivate?: (index: number) => void;
  onPointerEnterCell?: (index: number) => void;
  onPointerStop?: () => void;
  label: string;
}) {
  const cols = Math.max(1, ...cells.map((cell) => cell.col + 1));
  return (
    <div
      className="admin-condition-board"
      style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
      onPointerUp={onPointerStop}
      onPointerLeave={onPointerStop}
      data-testid={interactive ? "condition-grid" : undefined}
      aria-label={label}
    >
      {cells.map((cell, index) => {
        const visual = visuals[index] ?? { color: null, backgroundAssetId: null };
        const assetUrl = visual.backgroundAssetId
          ? assetUrls.get(visual.backgroundAssetId)
          : undefined;
        const baseLabel =
          index === baseAIndex ? "A" : index === baseBIndex ? "B" : null;
        return (
          <div
            key={index}
            role="button"
            tabIndex={interactive ? 0 : -1}
            aria-label={`第 ${cell.row + 1} 行第 ${cell.col + 1} 列`}
            className={`admin-condition-cell${selectedIndex === index ? " selected" : ""}${
              baseLabel === "A" ? " base-a" : baseLabel === "B" ? " base-b" : ""
            }`}
            style={{
              backgroundColor: visual.color ?? "#ffffff",
              backgroundImage: assetUrl ? `url("${assetUrl}")` : undefined,
              backgroundSize: "cover",
              backgroundPosition: "center",
              cursor: interactive ? "crosshair" : "default",
            }}
            onPointerDown={(event: ReactPointerEvent<HTMLDivElement>) => {
              if (!interactive) return;
              event.preventDefault();
              onActivate?.(index);
            }}
            onPointerEnter={() => {
              if (interactive && painting) onPointerEnterCell?.(index);
            }}
            onKeyDown={(event) => {
              if (!interactive) return;
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onActivate?.(index);
              }
            }}
            data-testid={interactive ? `condition-cell-${index}` : undefined}
            title={`第 ${cell.row + 1} 行 / 第 ${cell.col + 1} 列 · 归属 ${cell.initialOwner} · 初始兵力 ${cell.initialSoldiers} · 增援 A${cell.reinforcementA} / B${cell.reinforcementB}`}
          >
            <span className="admin-grid-cell-owner">
              {cell.initialOwner === 0 ? "中立" : `P${cell.initialOwner}`}
            </span>
            {baseLabel ? <span className="admin-grid-cell-base">{baseLabel}</span> : null}
            <div className="admin-grid-cell-content">
              <span
                className={`owner-dot${cell.initialOwner === 2 ? " owner-2" : ""}`}
                style={{
                  background:
                    cell.initialOwner === 1
                      ? "#3498DB"
                      : cell.initialOwner === 2
                        ? "#E74C3C"
                        : "transparent",
                }}
              />
              <span className="admin-cell-soldiers">{cell.initialSoldiers}</span>
            </div>
            <span className="admin-cell-reinforce">
              {cell.reinforcementA > 0 ? `A+${cell.reinforcementA}` : ""}
              {cell.reinforcementA > 0 && cell.reinforcementB > 0 ? " " : ""}
              {cell.reinforcementB > 0 ? `B+${cell.reinforcementB}` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function ConditionsPage() {
  const { notify, confirm } = useUi();
  const [versions, setVersions] = useState<ConditionVersion[]>([]);
  const [selection, setSelection] = useState<Selection>(null);
  const [form, setForm] = useState<ConditionFormState>(() => newConditionForm());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [media, setMedia] = useState<MediaAsset[]>([]);
  const [mediaLoaded, setMediaLoaded] = useState(false);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [view, setView] = useState<ViewMode>("player1");
  const [brush, setBrush] = useState<Brush>("select");
  const [painting, setPainting] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [currentColor, setCurrentColor] = useState("#3498DB");
  const [currentBackground, setCurrentBackground] = useState("");
  const [soldierBrush, setSoldierBrush] = useState("0");
  const [reinforcementABrush, setReinforcementABrush] = useState("0");
  const [reinforcementBBrush, setReinforcementBBrush] = useState("0");
  const [bulkOwner, setBulkOwner] = useState<0 | 1 | 2>(1);
  const [overrideIndex, setOverrideIndex] = useState<number | null>(null);
  const [overrideText, setOverrideText] = useState("");
  const [overrideError, setOverrideError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const selected =
    selection !== "new" && selection !== null
      ? versions.find((version) => version.id === selection) ?? null
      : null;
  const isNew = selection === "new";
  const readOnly = selected !== null && selected.status !== "draft";

  const assetUrls = useMemo(() => {
    const map = new Map<string, string>();
    for (const asset of media) map.set(asset.id, asset.url);
    return map;
  }, [media]);
  const assetIds = useMemo(() => {
    if (!mediaLoaded || mediaError) return null;
    return new Set(media.map((asset) => asset.id));
  }, [media, mediaLoaded, mediaError]);

  const applyVersion = useCallback((version: ConditionVersion | null) => {
    if (version === null) {
      setSelection(null);
      setForm(newConditionForm());
      return;
    }
    setSelection(version.id);
    setForm(formFromCondition(version));
    setSelectedIndex(null);
    setValidationErrors([]);
    setSaveError(null);
  }, []);

  const loadVersions = useCallback(
    async (preferredId?: string) => {
      const response = await adminApi.get<ConditionListResponse>("/conditions");
      setVersions(response.conditions);
      const targetId = preferredId ?? (selection !== "new" ? selection : null);
      if (targetId) {
        const version = response.conditions.find((item) => item.id === targetId);
        applyVersion(version ?? null);
      } else if (selection === null) {
        const preferred =
          response.conditions.find(
            (item) => item.status === "published" && presetIdOf(item) === "ref0",
          ) ??
          response.conditions.find((item) => item.status === "published") ??
          response.conditions[0] ??
          null;
        applyVersion(preferred);
      }
    },
    [selection, applyVersion],
  );

  const loadMedia = useCallback(async () => {
    try {
      const response = await adminApi.get<MediaListResponse>("/media?limit=500");
      setMedia(response.media.filter((asset) => asset.contentType.startsWith("image/")));
      setMediaError(null);
      setMediaLoaded(true);
    } catch (err) {
      setMediaError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const response = await adminApi.get<ConditionListResponse>("/conditions");
        if (cancelled) return;
        setVersions(response.conditions);
        const preferred =
          response.conditions.find(
            (item) => item.status === "published" && presetIdOf(item) === "ref0",
          ) ??
          response.conditions.find((item) => item.status === "published") ??
          response.conditions[0] ??
          null;
        applyVersion(preferred);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    void loadMedia();
    return () => {
      cancelled = true;
    };
    // 首次进入时加载条件版本与素材
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startNew() {
    setSelection("new");
    setForm(newConditionForm());
    setSelectedIndex(null);
    setValidationErrors([]);
    setSaveError(null);
    setBrush("select");
    setView("player1");
  }

  function activeLayers(): PlayerKey[] {
    if (view === "shared") return ["player1", "player2"];
    return [view];
  }

  function boardLayer(): ConditionVisual[] {
    return form.visuals[view === "player2" ? "player2" : "player1"];
  }

  function changeDimension(field: "rows" | "cols", value: string) {
    if (readOnly) return;
    const nextRows = field === "rows" ? value : form.rows;
    const nextCols = field === "cols" ? value : form.cols;
    const rows = Number(nextRows);
    const cols = Number(nextCols);
    if (
      Number.isInteger(rows) &&
      Number.isInteger(cols) &&
      rows >= 2 &&
      rows <= 20 &&
      cols >= 2 &&
      cols <= 20 &&
      rows * cols <= 100
    ) {
      const resized = resizeGrid(form, rows, cols);
      setForm(resized);
      if (selectedIndex !== null && selectedIndex >= rows * cols) {
        setSelectedIndex(null);
      }
    } else {
      setForm({ ...form, [field]: value });
    }
  }

  function isBaseCell(index: number): number | null {
    if (index === form.baseAIndex) return 1;
    if (index === form.baseBIndex) return 2;
    return null;
  }

  function applyBrushAt(index: number) {
    if (readOnly) return;
    setSelectedIndex(index);
    if (brush === "select") return;
    const baseOwner = isBaseCell(index);
    if (brush === "owner1" || brush === "owner2" || brush === "owner0") {
      const owner = brush === "owner1" ? 1 : brush === "owner2" ? 2 : 0;
      if (baseOwner !== null && owner !== baseOwner) {
        return;
      }
      setForm((current) => ({
        ...current,
        cells: current.cells.map((cell, cellIndex) =>
          cellIndex === index ? { ...cell, initialOwner: owner as 0 | 1 | 2 } : cell,
        ),
      }));
      return;
    }
    if (brush === "color") {
      const layers = activeLayers();
      setForm((current) => {
        const visuals = { ...current.visuals };
        for (const key of layers) {
          visuals[key] = current.visuals[key].map((visual, visualIndex) =>
            visualIndex === index ? { ...visual, color: currentColor } : visual,
          );
        }
        return { ...current, visuals };
      });
      return;
    }
    if (brush === "background") {
      const layers = activeLayers();
      const backgroundAssetId = currentBackground || null;
      setForm((current) => {
        const visuals = { ...current.visuals };
        for (const key of layers) {
          visuals[key] = current.visuals[key].map((visual, visualIndex) =>
            visualIndex === index ? { ...visual, backgroundAssetId } : visual,
          );
        }
        return { ...current, visuals };
      });
      return;
    }
    if (brush === "soldiers") {
      const value = nonNegativeInt(soldierBrush);
      setForm((current) => ({
        ...current,
        cells: current.cells.map((cell, cellIndex) =>
          cellIndex === index ? { ...cell, initialSoldiers: value } : cell,
        ),
      }));
      return;
    }
    if (brush === "reinforcementA" || brush === "reinforcementB") {
      const value = nonNegativeInt(
        brush === "reinforcementA" ? reinforcementABrush : reinforcementBBrush,
      );
      setForm((current) => ({
        ...current,
        cells: current.cells.map((cell, cellIndex) =>
          cellIndex === index
            ? {
                ...cell,
                reinforcementA: brush === "reinforcementA" ? value : cell.reinforcementA,
                reinforcementB: brush === "reinforcementB" ? value : cell.reinforcementB,
              }
            : cell,
        ),
      }));
    }
  }

  function bulkFill(mode: "all" | "neutral") {
    if (readOnly) return;
    const changed = form.cells.filter((cell, index) => {
      if (index === form.baseAIndex || index === form.baseBIndex) return false;
      return mode === "all" || cell.initialOwner === 0;
    }).length;
    setForm({
      ...form,
      cells: form.cells.map((cell, index) => {
        if (index === form.baseAIndex || index === form.baseBIndex) return cell;
        if (mode === "neutral" && cell.initialOwner !== 0) return cell;
        return { ...cell, initialOwner: bulkOwner };
      }),
    });
    notify(
      mode === "neutral"
        ? `已把 ${changed} 个中立格填充为归属 ${bulkOwner}`
        : `已将 ${changed} 个非基地格填充为归属 ${bulkOwner}`,
    );
  }

  async function copyVisuals() {
    if (readOnly) return;
    const ok = await confirm({
      title: "复制视觉层",
      message: "确认用玩家 1 的视觉覆盖玩家 2 的视觉？此操作只修改当前草稿。",
      confirmLabel: "覆盖玩家 2",
    });
    if (!ok) return;
    setForm((current) => ({
      ...current,
      visuals: {
        ...current.visuals,
        player2: current.visuals.player1.map((visual) => ({ ...visual })),
      },
    }));
    notify("玩家 1 的视觉已复制到玩家 2");
  }

  function setBaseForSelected(kind: "A" | "B") {
    if (readOnly || selectedIndex === null) return;
    const index = selectedIndex;
    const other = kind === "A" ? form.baseBIndex : form.baseAIndex;
    if (index === other) {
      notify("两个基地不能重合", "error");
      return;
    }
    setForm((current) => ({
      ...current,
      baseAIndex: kind === "A" ? index : current.baseAIndex,
      baseBIndex: kind === "B" ? index : current.baseBIndex,
      cells: current.cells.map((cell, cellIndex) => {
        if (kind === "A" && cellIndex === index) return { ...cell, initialOwner: 1 };
        if (kind === "B" && cellIndex === index) return { ...cell, initialOwner: 2 };
        return cell;
      }),
    }));
    notify(`第 ${index + 1} 格已设为基地 ${kind}`);
  }

  function updateCell(index: number, patch: Partial<ConditionCell>) {
    if (readOnly) return;
    setForm((current) => ({
      ...current,
      cells: current.cells.map((cell, cellIndex) =>
        cellIndex === index ? { ...cell, ...patch } : cell,
      ),
    }));
  }

  function updateVisual(index: number, key: PlayerKey, patch: Partial<ConditionVisual>) {
    if (readOnly) return;
    setForm((current) => ({
      ...current,
      visuals: {
        ...current.visuals,
        [key]: current.visuals[key].map((visual, visualIndex) =>
          visualIndex === index ? { ...visual, ...patch } : visual,
        ),
      },
    }));
  }

  function changeTrialCount(field: "practiceTrials" | "formalTrials", value: string) {
    if (readOnly) return;
    const next = { ...form, [field]: value };
    const practice = Number(next.practiceTrials);
    const formal = Number(next.formalTrials);
    if (
      Number.isInteger(practice) &&
      practice >= 0 &&
      Number.isInteger(formal) &&
      formal >= 1
    ) {
      next.trialParams = normalizeTrialParams(form.trialParams, practice, formal);
    }
    setForm(next);
  }

  function updateTrialParam(index: number, patch: Partial<TrialParam>) {
    if (readOnly) return;
    setForm((current) => ({
      ...current,
      trialParams: current.trialParams.map((param, paramIndex) =>
        paramIndex === index ? { ...param, ...patch } : param,
      ),
    }));
  }

  function openOverrides(index: number) {
    const overrides = form.trialParams[index]?.reinforcementOverrides;
    setOverrideIndex(index);
    setOverrideText(overrides ? JSON.stringify(overrides, null, 2) : "");
    setOverrideError(null);
  }

  function saveOverrides() {
    if (overrideIndex === null) return;
    const result = parseOverridesText(overrideText, form.cells.length);
    if (result.error) {
      setOverrideError(result.error);
      return;
    }
    updateTrialParam(overrideIndex, { reinforcementOverrides: result.value });
    setOverrideIndex(null);
    notify("增援覆盖已更新");
  }

  async function uploadBackground(file: File) {
    setUploading(true);
    setMediaError(null);
    try {
      const response = await adminApi.upload<MediaUploadResponse>(
        "/media",
        imageUploadForm(file, "condition-background"),
      );
      setMedia((current) => [response.asset, ...current]);
      setCurrentBackground(response.asset.id);
      setBrush("background");
      notify(`背景资产 ${response.asset.filename} 已上传，点击格子应用`);
    } catch (err) {
      setMediaError(errorMessage(err));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function persistDraft(showNotice: boolean): Promise<string | null> {
    const result = buildConditionPayload(form, assetIds);
    setValidationErrors(result.errors);
    if (!result.payload) {
      setSaveError(null);
      notify("请先修正条件配置错误", "error");
      return null;
    }
    setSaving(true);
    setSaveError(null);
    try {
      if (isNew || selection === null) {
        const response = await adminApi.post<ConditionResponse>("/conditions", result.payload);
        await loadVersions(response.condition.id);
        if (showNotice) notify(`条件草稿已创建，版本 ${response.condition.version}`);
        return response.condition.id;
      }
      const response = await adminApi.patch<ConditionResponse>(
        `/conditions/${selection}`,
        result.payload,
      );
      await loadVersions(response.condition.id);
      if (showNotice) notify("条件草稿已保存");
      return response.condition.id;
    } catch (err) {
      setSaveError(errorMessage(err));
      notify(errorMessage(err), "error");
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function handleSave() {
    await persistDraft(true);
  }

  async function handlePublish() {
    const check = buildConditionPayload(form, assetIds);
    setValidationErrors(check.errors);
    if (!check.payload) {
      notify("请先修正条件配置错误", "error");
      return;
    }
    const ok = await confirm({
      title: "发布条件版本",
      message:
        "发布后同名已发布的版本会归档。已使用旧版本创建的房间不受影响。发布后本版本不可修改。",
      confirmLabel: "发布",
    });
    if (!ok) return;
    setPublishing(true);
    setSaveError(null);
    try {
      const id = await persistDraft(false);
      if (!id) return;
      await adminApi.post(`/conditions/${id}/publish`);
      await loadVersions(id);
      notify("条件版本已发布");
    } catch (err) {
      setSaveError(errorMessage(err));
      notify(errorMessage(err), "error");
    } finally {
      setPublishing(false);
    }
  }

  function cloneAsNewDraft() {
    const source = form;
    const next: ConditionFormState = {
      ...source,
      name: `${form.name || "条件"}-copy`.slice(0, 120),
      cells: source.cells.map((cell) => ({ ...cell })),
      visuals: {
        player1: source.visuals.player1.map((visual) => ({ ...visual })),
        player2: source.visuals.player2.map((visual) => ({ ...visual })),
      },
      trialParams: source.trialParams.map((param) => ({
        ...param,
        reinforcementOverrides: param.reinforcementOverrides
          ? {
              player1: param.reinforcementOverrides.player1?.map((entry) => ({ ...entry })),
              player2: param.reinforcementOverrides.player2?.map((entry) => ({ ...entry })),
            }
          : null,
      })),
      metadata: JSON.parse(JSON.stringify(source.metadata)) as Record<string, unknown>,
    };
    setSelection("new");
    setForm(next);
    setSelectedIndex(null);
    setValidationErrors([]);
    setSaveError(null);
    notify("已将当前条件配置加载到新草稿");
  }

  const selectedCell = selectedIndex !== null ? form.cells[selectedIndex] : undefined;
  const selectedVisualA =
    selectedIndex !== null ? form.visuals.player1[selectedIndex] : undefined;
  const selectedVisualB =
    selectedIndex !== null ? form.visuals.player2[selectedIndex] : undefined;
  const editorTitle = isNew
    ? "新建条件"
    : selected
      ? `${selected.name} · 第 ${selected.version} 版`
      : "条件设计器";
  const expectedParams =
    parseNonNegativeInt(form.practiceTrials) !== null &&
    parsePositiveInt(form.formalTrials) !== null
      ? (parseNonNegativeInt(form.practiceTrials) as number) +
        (parsePositiveInt(form.formalTrials) as number)
      : null;

  return (
    <div>
      <PageHeader
        title="条件"
        subtitle="设计棋盘、视觉层与 Trial 参数。发布后的条件版本不可修改，可从现有版本复制为新草稿。"
        actions={
          <button
            type="button"
            className="admin-btn admin-btn-primary"
            onClick={startNew}
            data-testid="condition-create"
          >
            <Plus size={16} />
            新建条件
          </button>
        }
      />

      {error ? <ErrorNotice message={error} onRetry={() => void loadVersions()} /> : null}

      {loading ? (
        <LoadingBlock rows={7} label="正在加载条件版本" />
      ) : versions.length === 0 && selection !== "new" ? (
        <EmptyState
          icon={ImagePlus}
          title="暂无条件版本"
          description="新建条件并发布后，才能在创建 Room 时选择。"
          action={
            <button type="button" className="admin-btn admin-btn-primary" onClick={startNew}>
              新建条件
            </button>
          }
        />
      ) : (
        <div className="admin-layout-columns admin-layout-columns-wide">
          <aside className="admin-card admin-sticky-side">
            <h2 className="admin-section-title">版本列表</h2>
            <p className="admin-hint">
              内置条件 ref0-ref5 与 asym 由系统预置，可作为新草稿的起点。
            </p>
            <div className="admin-version-list">
              {versions.map((version) => {
                const presetId = presetIdOf(version);
                return (
                  <button
                    type="button"
                    key={version.id}
                    className={`admin-version-item${selection === version.id ? " active" : ""}`}
                    onClick={() => applyVersion(version)}
                    data-testid={`condition-version-${version.id}`}
                  >
                    <div className="admin-version-item-head">
                      <span>
                        {version.name} · v{version.version}
                      </span>
                      <VersionStatusChip status={version.status} />
                    </div>
                    <div className="admin-chip-list">
                      {presetId ? <StatusChip tone="info">内置 {presetId}</StatusChip> : null}
                      <span className="admin-hint">
                        {version.rows}×{version.cols}
                      </span>
                      <span className="admin-hint">
                        {version.practiceTrials}+{version.formalTrials} Trial
                      </span>
                    </div>
                    <div className="admin-version-item-meta">
                      {version.turnCount} 回合 × {version.turnSeconds} 秒
                    </div>
                    <div className="admin-version-item-meta">
                      发布：{formatDateTime(version.publishedAt)}
                    </div>
                  </button>
                );
              })}
              {isNew ? (
                <div
                  className="admin-version-item active"
                  style={{ cursor: "default" }}
                >
                  <div className="admin-version-item-head">
                    <span>新草稿</span>
                    <StatusChip>未保存</StatusChip>
                  </div>
                  <div className="admin-version-item-meta">保存后生成版本号</div>
                </div>
              ) : null}
            </div>
          </aside>

          <section className="admin-card">
            <div className="admin-questionnaire-editor-head">
              <div>
                <h2 className="admin-section-title" style={{ marginBottom: "4px" }}>
                  {editorTitle}
                </h2>
                <div className="admin-chip-list">
                  {selected ? <VersionStatusChip status={selected.status} /> : null}
                  {readOnly ? <span className="admin-hint">已发布版本只读</span> : null}
                  {!readOnly ? (
                    <span className="admin-hint">
                      当前网格 {form.rows}×{form.cols}
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="admin-btn-row">
                {readOnly ? (
                  <>
                    <span className="admin-hint">
                      <Lock size={13} style={{ verticalAlign: "-2px", marginRight: "4px" }} />
                      已发布版本只读
                    </span>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary"
                      onClick={cloneAsNewDraft}
                      data-testid="condition-copy-preset"
                    >
                      <Copy size={15} />
                      复制为新草稿
                    </button>
                  </>
                ) : (
                  <>
                    {selected ? (
                      <button
                        type="button"
                        className="admin-btn admin-btn-secondary"
                        onClick={cloneAsNewDraft}
                        data-testid="condition-copy-preset"
                      >
                        <Copy size={15} />
                        复制为新草稿
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary"
                      onClick={() => void handleSave()}
                      disabled={saving || publishing}
                      data-testid="condition-save"
                    >
                      <Save size={15} />
                      {saving ? "保存中" : "保存草稿"}
                    </button>
                    <button
                      type="button"
                      className="admin-btn admin-btn-primary"
                      onClick={() => void handlePublish()}
                      disabled={saving || publishing}
                      data-testid="condition-publish"
                    >
                      <CheckCircle2 size={15} />
                      {publishing ? "发布中" : "发布"}
                    </button>
                  </>
                )}
              </div>
            </div>

            {validationErrors.length > 0 ? (
              <InlineNotice tone="error">
                <ul className="admin-validation-list">
                  {validationErrors.map((message, index) => (
                    <li key={`${message}-${index}`}>{message}</li>
                  ))}
                </ul>
              </InlineNotice>
            ) : null}
            {saveError ? <InlineNotice tone="error">{saveError}</InlineNotice> : null}
            {readOnly ? (
              <div className="admin-readonly-banner">
                <Lock size={14} />
                该版本已发布或归档，所有配置只读。复制为新草稿后可继续修改。
              </div>
            ) : null}

            <div className="admin-form-section">
              <h3 className="admin-section-title">基本信息</h3>
              <div className="admin-form-row">
                <Field label="条件名称" htmlFor="condition-name" hint="新建草稿时按条件名称生成版本号。">
                  <input
                    id="condition-name"
                    className="admin-input"
                    value={form.name}
                    onChange={(event) => setForm({ ...form, name: event.target.value })}
                    disabled={readOnly}
                    data-testid="condition-name"
                  />
                </Field>
                <Field label="描述" htmlFor="condition-description">
                  <input
                    id="condition-description"
                    className="admin-input"
                    value={form.description}
                    onChange={(event) => setForm({ ...form, description: event.target.value })}
                    disabled={readOnly}
                    data-testid="condition-description"
                  />
                </Field>
              </div>
              <div className="admin-condition-meta-grid">
                <Field label="行数" htmlFor="condition-rows" hint="2 到 20">
                  <input
                    id="condition-rows"
                    className="admin-input"
                    type="number"
                    min="2"
                    max="20"
                    value={form.rows}
                    onChange={(event) => changeDimension("rows", event.target.value)}
                    disabled={readOnly}
                    data-testid="condition-rows"
                  />
                </Field>
                <Field label="列数" htmlFor="condition-cols" hint="总格数不超过 100">
                  <input
                    id="condition-cols"
                    className="admin-input"
                    type="number"
                    min="2"
                    max="20"
                    value={form.cols}
                    onChange={(event) => changeDimension("cols", event.target.value)}
                    disabled={readOnly}
                    data-testid="condition-cols"
                  />
                </Field>
                <Field label="练习 Trial 数" htmlFor="condition-practice">
                  <input
                    id="condition-practice"
                    className="admin-input"
                    type="number"
                    min="0"
                    step="1"
                    value={form.practiceTrials}
                    onChange={(event) => changeTrialCount("practiceTrials", event.target.value)}
                    disabled={readOnly}
                    data-testid="condition-practice-trials"
                  />
                </Field>
                <Field label="正式 Trial 数" htmlFor="condition-formal">
                  <input
                    id="condition-formal"
                    className="admin-input"
                    type="number"
                    min="1"
                    step="1"
                    value={form.formalTrials}
                    onChange={(event) => changeTrialCount("formalTrials", event.target.value)}
                    disabled={readOnly}
                    data-testid="condition-formal-trials"
                  />
                </Field>
                <Field label="每 Trial 回合数" htmlFor="condition-turns">
                  <input
                    id="condition-turns"
                    className="admin-input"
                    type="number"
                    min="1"
                    step="1"
                    value={form.turnCount}
                    onChange={(event) => setForm({ ...form, turnCount: event.target.value })}
                    disabled={readOnly}
                    data-testid="condition-turn-count"
                  />
                </Field>
                <Field label="回合秒数" htmlFor="condition-turn-seconds">
                  <input
                    id="condition-turn-seconds"
                    className="admin-input"
                    type="number"
                    min="1"
                    step="1"
                    value={form.turnSeconds}
                    onChange={(event) => setForm({ ...form, turnSeconds: event.target.value })}
                    disabled={readOnly}
                    data-testid="condition-turn-seconds"
                  />
                </Field>
                <Field label="休息秒数" htmlFor="condition-rest-seconds">
                  <input
                    id="condition-rest-seconds"
                    className="admin-input"
                    type="number"
                    min="1"
                    step="1"
                    value={form.restSeconds}
                    onChange={(event) => setForm({ ...form, restSeconds: event.target.value })}
                    disabled={readOnly}
                    data-testid="condition-rest-seconds"
                  />
                </Field>
                <Field label="正式 Trial 随机化">
                  <label className="admin-check-item">
                    <input
                      type="checkbox"
                      checked={form.randomizeFormal}
                      onChange={(event) =>
                        setForm({ ...form, randomizeFormal: event.target.checked })
                      }
                      disabled={readOnly}
                      data-testid="condition-randomize"
                    />
                    <span>随机化正式 Trial 顺序</span>
                  </label>
                </Field>
              </div>
              <details className="admin-json-details" style={{ marginTop: "8px" }}>
                <summary>内置元数据（随版本保存）</summary>
                <pre className="payload-json">{JSON.stringify(form.metadata, null, 2)}</pre>
              </details>
            </div>

            <div className="admin-form-section">
              <div className="admin-condition-toolbar">
                <h3>棋盘与视觉</h3>
                <div className="admin-kind-changer">
                  <button
                    type="button"
                    className={`admin-btn admin-btn-secondary admin-btn-sm admin-kind-button${
                      view === "player1" ? " active" : ""
                    }`}
                    onClick={() => setView("player1")}
                  >
                    玩家 1 视图
                  </button>
                  <button
                    type="button"
                    className={`admin-btn admin-btn-secondary admin-btn-sm admin-kind-button${
                      view === "player2" ? " active" : ""
                    }`}
                    onClick={() => setView("player2")}
                  >
                    玩家 2 视图
                  </button>
                  <button
                    type="button"
                    className={`admin-btn admin-btn-secondary admin-btn-sm admin-kind-button${
                      view === "shared" ? " active" : ""
                    }`}
                    onClick={() => setView("shared")}
                  >
                    共享视图
                  </button>
                </div>
              </div>
              <p className="admin-hint">
                共享视图下颜色和背景笔刷会同时应用到玩家 1 和玩家 2 的视觉层；归属、兵力与增援修改的是共享棋盘。
              </p>

              <div className="admin-owner-tools">
                <span className="admin-label" style={{ marginBottom: 0 }}>
                  笔刷
                </span>
                <button
                  type="button"
                  className={`admin-btn admin-btn-sm ${
                    brush === "select" ? "admin-btn-primary" : "admin-btn-secondary"
                  }`}
                  onClick={() => setBrush("select")}
                >
                  查看
                </button>
                <button
                  type="button"
                  className={`admin-btn admin-btn-sm ${
                    brush === "owner1" ? "admin-btn-primary" : "admin-btn-secondary"
                  }`}
                  onClick={() => setBrush("owner1")}
                  data-testid="condition-owner-1"
                >
                  归属玩家 1
                </button>
                <button
                  type="button"
                  className={`admin-btn admin-btn-sm ${
                    brush === "owner2" ? "admin-btn-primary" : "admin-btn-secondary"
                  }`}
                  onClick={() => setBrush("owner2")}
                  data-testid="condition-owner-2"
                >
                  归属玩家 2
                </button>
                <button
                  type="button"
                  className={`admin-btn admin-btn-sm ${
                    brush === "owner0" ? "admin-btn-primary" : "admin-btn-secondary"
                  }`}
                  onClick={() => setBrush("owner0")}
                  data-testid="condition-owner-0"
                >
                  中立
                </button>
                <button
                  type="button"
                  className={`admin-btn admin-btn-sm ${
                    brush === "color" ? "admin-btn-primary" : "admin-btn-secondary"
                  }`}
                  onClick={() => setBrush("color")}
                >
                  颜色
                </button>
                <button
                  type="button"
                  className={`admin-btn admin-btn-sm ${
                    brush === "background" ? "admin-btn-primary" : "admin-btn-secondary"
                  }`}
                  onClick={() => setBrush("background")}
                >
                  背景
                </button>
                <button
                  type="button"
                  className={`admin-btn admin-btn-sm ${
                    brush === "soldiers" ? "admin-btn-primary" : "admin-btn-secondary"
                  }`}
                  onClick={() => setBrush("soldiers")}
                >
                  初始兵力
                </button>
                <button
                  type="button"
                  className={`admin-btn admin-btn-sm ${
                    brush === "reinforcementA" ? "admin-btn-primary" : "admin-btn-secondary"
                  }`}
                  onClick={() => setBrush("reinforcementA")}
                >
                  增援 A
                </button>
                <button
                  type="button"
                  className={`admin-btn admin-btn-sm ${
                    brush === "reinforcementB" ? "admin-btn-primary" : "admin-btn-secondary"
                  }`}
                  onClick={() => setBrush("reinforcementB")}
                >
                  增援 B
                </button>
              </div>

              <div className="admin-owner-tools">
                <input
                  className="admin-color-input"
                  type="color"
                  value={currentColor}
                  onChange={(event) => {
                    setCurrentColor(event.target.value);
                    setBrush("color");
                  }}
                  aria-label="视觉颜色"
                  disabled={readOnly}
                  data-testid="condition-color"
                />
                <select
                  className="admin-select"
                  value={currentBackground}
                  onChange={(event) => {
                    setCurrentBackground(event.target.value);
                    setBrush("background");
                  }}
                  disabled={readOnly}
                  aria-label="背景资产"
                  data-testid="condition-background"
                  style={{ maxWidth: "240px" }}
                >
                  <option value="">无背景资产</option>
                  {media.map((asset) => (
                    <option key={asset.id} value={asset.id}>
                      {asset.filename}
                    </option>
                  ))}
                </select>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  hidden
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) void uploadBackground(file);
                  }}
                />
                <button
                  type="button"
                  className="admin-btn admin-btn-secondary admin-btn-sm"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={readOnly || uploading}
                  data-testid="condition-upload-background"
                >
                  <Upload size={14} />
                  {uploading ? "上传中" : "上传背景"}
                </button>
                <span className="admin-hint">初始兵力</span>
                <input
                  className="admin-input"
                  type="number"
                  min="0"
                  step="1"
                  value={soldierBrush}
                  onChange={(event) => setSoldierBrush(event.target.value)}
                  style={{ maxWidth: "96px" }}
                  disabled={readOnly}
                  aria-label="初始兵力笔刷值"
                />
                <span className="admin-hint">增援 A</span>
                <input
                  className="admin-input"
                  type="number"
                  min="0"
                  step="1"
                  value={reinforcementABrush}
                  onChange={(event) => setReinforcementABrush(event.target.value)}
                  style={{ maxWidth: "90px" }}
                  disabled={readOnly}
                  aria-label="增援 A 笔刷值"
                />
                <span className="admin-hint">增援 B</span>
                <input
                  className="admin-input"
                  type="number"
                  min="0"
                  step="1"
                  value={reinforcementBBrush}
                  onChange={(event) => setReinforcementBBrush(event.target.value)}
                  style={{ maxWidth: "90px" }}
                  disabled={readOnly}
                  aria-label="增援 B 笔刷值"
                />
              </div>
              {mediaError ? <InlineNotice tone="error">{mediaError}</InlineNotice> : null}

              <div className="admin-condition-designer">
                <div>
                  <ConditionBoard
                    cells={form.cells}
                    visuals={boardLayer()}
                    baseAIndex={form.baseAIndex}
                    baseBIndex={form.baseBIndex}
                    selectedIndex={selectedIndex}
                    assetUrls={assetUrls}
                    interactive={!readOnly}
                    painting={painting}
                    onActivate={(index) => {
                      setPainting(true);
                      applyBrushAt(index);
                    }}
                    onPointerEnterCell={applyBrushAt}
                    onPointerStop={() => setPainting(false)}
                    label={`${view === "shared" ? "共享" : view === "player2" ? "玩家 2" : "玩家 1"}棋盘编辑器`}
                  />
                  <div className="admin-owner-tools" style={{ marginTop: "12px" }}>
                    <span className="admin-label" style={{ marginBottom: 0 }}>
                      批量归属
                    </span>
                    <select
                      className="admin-select"
                      value={bulkOwner}
                      onChange={(event) =>
                        setBulkOwner(Number(event.target.value) === 2 ? 2 : Number(event.target.value) === 0 ? 0 : 1)
                      }
                      disabled={readOnly}
                      aria-label="批量归属目标"
                      style={{ maxWidth: "130px" }}
                    >
                      <option value={0}>中立</option>
                      <option value={1}>玩家 1</option>
                      <option value={2}>玩家 2</option>
                    </select>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary admin-btn-sm"
                      onClick={() => bulkFill("all")}
                      disabled={readOnly}
                    >
                      全部非基地格
                    </button>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary admin-btn-sm"
                      onClick={() => bulkFill("neutral")}
                      disabled={readOnly}
                    >
                      仅中立格
                    </button>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary admin-btn-sm"
                      onClick={() => void copyVisuals()}
                      disabled={readOnly}
                      data-testid="condition-copy-visuals"
                    >
                      <Copy size={13} />
                      复制玩家 1 视觉到玩家 2
                    </button>
                  </div>
                  <p className="admin-hint">
                    拖动笔刷可连续修改。基地格 A/B 始终保留给对应玩家，批量归属会跳过基地格。
                  </p>
                </div>

                <div className="admin-condition-inspector">
                  <h3 className="admin-section-title" style={{ fontSize: "1rem" }}>
                    格子检查器
                  </h3>
                  {selectedCell === undefined || selectedIndex === null ? (
                    <p className="admin-hint">点击棋盘上的格子查看并编辑详细属性。</p>
                  ) : (
                    <>
                      <div className="admin-hint" style={{ marginBottom: "10px" }}>
                        第 {selectedCell.row + 1} 行 / 第 {selectedCell.col + 1} 列 · 索引 {selectedIndex}
                      </div>
                      <div className="admin-form-row">
                        <Field label="初始归属" htmlFor="cell-owner">
                          <select
                            id="cell-owner"
                            className="admin-select"
                            value={selectedCell.initialOwner}
                            onChange={(event) =>
                              updateCell(selectedIndex, {
                                initialOwner: Number(event.target.value) as 0 | 1 | 2,
                              })
                            }
                            disabled={readOnly}
                          >
                            <option value={0}>中立</option>
                            <option value={1}>玩家 1</option>
                            <option value={2}>玩家 2</option>
                          </select>
                        </Field>
                        <Field label="初始兵力" htmlFor="cell-soldiers">
                          <input
                            id="cell-soldiers"
                            className="admin-input"
                            type="number"
                            min="0"
                            step="1"
                            value={selectedCell.initialSoldiers}
                            onChange={(event) =>
                              updateCell(selectedIndex, {
                                initialSoldiers: nonNegativeInt(event.target.value),
                              })
                            }
                            disabled={readOnly}
                          />
                        </Field>
                      </div>
                      <div className="admin-form-row">
                        <Field label="增援 A" htmlFor="cell-reinforcement-a">
                          <input
                            id="cell-reinforcement-a"
                            className="admin-input"
                            type="number"
                            min="0"
                            step="1"
                            value={selectedCell.reinforcementA}
                            onChange={(event) =>
                              updateCell(selectedIndex, {
                                reinforcementA: nonNegativeInt(event.target.value),
                              })
                            }
                            disabled={readOnly}
                          />
                        </Field>
                        <Field label="增援 B" htmlFor="cell-reinforcement-b">
                          <input
                            id="cell-reinforcement-b"
                            className="admin-input"
                            type="number"
                            min="0"
                            step="1"
                            value={selectedCell.reinforcementB}
                            onChange={(event) =>
                              updateCell(selectedIndex, {
                                reinforcementB: nonNegativeInt(event.target.value),
                              })
                            }
                            disabled={readOnly}
                          />
                        </Field>
                      </div>
                      <div className="admin-btn-row" style={{ marginBottom: "12px" }}>
                        <button
                          type="button"
                          className="admin-btn admin-btn-secondary admin-btn-sm"
                          onClick={() => setBaseForSelected("A")}
                          disabled={readOnly}
                        >
                          设为基地 A
                        </button>
                        <button
                          type="button"
                          className="admin-btn admin-btn-secondary admin-btn-sm"
                          onClick={() => setBaseForSelected("B")}
                          disabled={readOnly}
                        >
                          设为基地 B
                        </button>
                      </div>
                      <div className="admin-form-section">
                        <h4 className="admin-section-title" style={{ fontSize: "0.9375rem" }}>
                          玩家 1 视觉
                        </h4>
                        <div className="admin-inline-actions">
                          <input
                            className="admin-color-input"
                            type="color"
                            value={selectedVisualA?.color ?? "#ffffff"}
                            onChange={(event) =>
                              updateVisual(selectedIndex, "player1", { color: event.target.value })
                            }
                            disabled={readOnly}
                            aria-label="玩家 1 格子颜色"
                          />
                          <button
                            type="button"
                            className="admin-btn admin-btn-ghost admin-btn-sm"
                            onClick={() => updateVisual(selectedIndex, "player1", { color: null })}
                            disabled={readOnly}
                          >
                            清除颜色
                          </button>
                        </div>
                        <Field label="背景资产" htmlFor="cell-bg-p1">
                          <select
                            id="cell-bg-p1"
                            className="admin-select"
                            value={selectedVisualA?.backgroundAssetId ?? ""}
                            onChange={(event) =>
                              updateVisual(selectedIndex, "player1", {
                                backgroundAssetId: event.target.value || null,
                              })
                            }
                            disabled={readOnly}
                          >
                            <option value="">无背景</option>
                            {media.map((asset) => (
                              <option key={asset.id} value={asset.id}>
                                {asset.filename}
                              </option>
                            ))}
                          </select>
                        </Field>
                        {selectedVisualA?.backgroundAssetId ? (
                          <div className="admin-hint admin-mono" style={{ wordBreak: "break-all" }}>
                            {selectedVisualA.backgroundAssetId}
                          </div>
                        ) : null}
                      </div>
                      <div className="admin-form-section">
                        <h4 className="admin-section-title" style={{ fontSize: "0.9375rem" }}>
                          玩家 2 视觉
                        </h4>
                        <div className="admin-inline-actions">
                          <input
                            className="admin-color-input"
                            type="color"
                            value={selectedVisualB?.color ?? "#ffffff"}
                            onChange={(event) =>
                              updateVisual(selectedIndex, "player2", { color: event.target.value })
                            }
                            disabled={readOnly}
                            aria-label="玩家 2 格子颜色"
                          />
                          <button
                            type="button"
                            className="admin-btn admin-btn-ghost admin-btn-sm"
                            onClick={() => updateVisual(selectedIndex, "player2", { color: null })}
                            disabled={readOnly}
                          >
                            清除颜色
                          </button>
                        </div>
                        <Field label="背景资产" htmlFor="cell-bg-p2">
                          <select
                            id="cell-bg-p2"
                            className="admin-select"
                            value={selectedVisualB?.backgroundAssetId ?? ""}
                            onChange={(event) =>
                              updateVisual(selectedIndex, "player2", {
                                backgroundAssetId: event.target.value || null,
                              })
                            }
                            disabled={readOnly}
                          >
                            <option value="">无背景</option>
                            {media.map((asset) => (
                              <option key={asset.id} value={asset.id}>
                                {asset.filename}
                              </option>
                            ))}
                          </select>
                        </Field>
                        {selectedVisualB?.backgroundAssetId ? (
                          <div className="admin-hint admin-mono" style={{ wordBreak: "break-all" }}>
                            {selectedVisualB.backgroundAssetId}
                          </div>
                        ) : null}
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>

            <div className="admin-form-section">
              <div className="admin-condition-toolbar">
                <h3>双人预览</h3>
                <span className="admin-hint">按当前网格、归属与视觉层渲染</span>
              </div>
              <div className="admin-preview-board-wrap">
                <div className="admin-preview-board">
                  <h4>玩家 1</h4>
                  <ConditionBoard
                    cells={form.cells}
                    visuals={form.visuals.player1}
                    baseAIndex={form.baseAIndex}
                    baseBIndex={form.baseBIndex}
                    selectedIndex={null}
                    assetUrls={assetUrls}
                    interactive={false}
                    label="玩家 1 预览"
                  />
                </div>
                <div className="admin-preview-board">
                  <h4>玩家 2</h4>
                  <ConditionBoard
                    cells={form.cells}
                    visuals={form.visuals.player2}
                    baseAIndex={form.baseAIndex}
                    baseBIndex={form.baseBIndex}
                    selectedIndex={null}
                    assetUrls={assetUrls}
                    interactive={false}
                    label="玩家 2 预览"
                  />
                </div>
              </div>
            </div>

            <div className="admin-form-section">
              <div className="admin-condition-toolbar">
                <h3>Trial 参数</h3>
                <span className="admin-hint">
                  {expectedParams === null
                    ? "Trial 数无效"
                    : `应有 ${expectedParams} 行，当前 ${form.trialParams.length} 行`}
                </span>
              </div>
              <div className="admin-table-wrap">
                <table className="admin-table admin-compact-table admin-trial-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>类型</th>
                      <th>正式 Trial</th>
                      <th>玩家 1 初始兵力</th>
                      <th>玩家 2 初始兵力</th>
                      <th>增援覆盖</th>
                    </tr>
                  </thead>
                  <tbody>
                    {form.trialParams.map((param, index) => (
                      <tr key={param.sourceIndex}>
                        <td className="admin-mono">{index + 1}</td>
                        <td>{param.isPractice ? "练习" : "正式"}</td>
                        <td>{param.formalTrial === 0 ? "—" : param.formalTrial}</td>
                        <td>
                          <input
                            className="admin-input"
                            type="number"
                            min="1"
                            step="1"
                            value={param.baseSoldiersA}
                            onChange={(event) =>
                              updateTrialParam(index, {
                                baseSoldiersA: nonNegativeInt(event.target.value),
                              })
                            }
                            disabled={readOnly}
                            aria-label={`Trial ${index + 1} 玩家 1 初始兵力`}
                            data-testid={`condition-trial-a-${index}`}
                          />
                        </td>
                        <td>
                          <input
                            className="admin-input"
                            type="number"
                            min="1"
                            step="1"
                            value={param.baseSoldiersB}
                            onChange={(event) =>
                              updateTrialParam(index, {
                                baseSoldiersB: nonNegativeInt(event.target.value),
                              })
                            }
                            disabled={readOnly}
                            aria-label={`Trial ${index + 1} 玩家 2 初始兵力`}
                            data-testid={`condition-trial-b-${index}`}
                          />
                        </td>
                        <td>
                          <button
                            type="button"
                            className="admin-btn admin-btn-secondary admin-btn-sm"
                            onClick={() => openOverrides(index)}
                            disabled={readOnly}
                            data-testid={`condition-overrides-${index}`}
                          >
                            {param.reinforcementOverrides
                              ? `A ${overrideEntryCount(param.reinforcementOverrides, "player1")} / B ${overrideEntryCount(param.reinforcementOverrides, "player2")}`
                              : "无覆盖"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="admin-hint">
                修改练习或正式 Trial 数会自动重建参数行，保留已有行数值。增援覆盖按格子索引设置，留空或 null 表示不使用覆盖。
              </p>
            </div>
          </section>
        </div>
      )}

      {overrideIndex !== null ? (
        <Modal
          title={`Trial ${overrideIndex + 1} 增援覆盖`}
          onClose={() => setOverrideIndex(null)}
          wide
          footer={
            <>
              <button
                type="button"
                className="admin-btn admin-btn-secondary"
                onClick={() => {
                  setOverrideText("");
                  setOverrideError(null);
                }}
              >
                清空
              </button>
              <button
                type="button"
                className="admin-btn admin-btn-secondary"
                onClick={() => setOverrideIndex(null)}
              >
                取消
              </button>
              <button
                type="button"
                className="admin-btn admin-btn-primary"
                onClick={saveOverrides}
                data-testid="condition-overrides-save"
              >
                保存覆盖
              </button>
            </>
          }
        >
          <p className="admin-hint">
            填入 JSON 对象，例如 {"{\"player1\": [{\"cellIndex\": 0, \"value\": 8}], \"player2\": []}"}。
            留空或填写 null 表示无覆盖。
          </p>
          <textarea
            className="admin-textarea"
            value={overrideText}
            onChange={(event) => setOverrideText(event.target.value)}
            aria-label="增援覆盖 JSON"
            data-testid="condition-overrides-json"
            style={{ minHeight: "220px", fontFamily: "var(--font-mono)" }}
          />
          {overrideError ? <InlineNotice tone="error">{overrideError}</InlineNotice> : null}
        </Modal>
      ) : null}
    </div>
  );
}
