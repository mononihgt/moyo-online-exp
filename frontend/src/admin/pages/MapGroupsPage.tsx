import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, MouseEvent } from "react";
import {
  CheckCircle2,
  Lock,
  Map as MapIcon,
  Plus,
  Save,
  Upload,
  X,
} from "lucide-react";
import type {
  MapGroupMode,
  MapGroupVersion,
  MapSlot,
  TroopProfile,
  TroopProfileVersion,
} from "../../shared/types";
import { formatDateTime } from "../../shared/format";
import { BoardCanvas } from "../../shared/board/BoardCanvas";
import { TrialInfoBadge } from "../../shared/board/TrialInfoBadge";
import { adminApi, errorMessage, imageUploadForm } from "../api";
import type {
  MapGroupDraftPayload,
  MapGroupListResponse,
  MapGroupResponse,
  MediaUploadResponse,
  TroopProfileListResponse,
} from "../types";
import {
  EmptyState,
  ErrorNotice,
  Field,
  InlineNotice,
  LoadingBlock,
  PageHeader,
  StatusChip,
  VersionStatusChip,
  centsFromYuan,
  useUi,
  yuanFromCents,
} from "../ui";
import { MAP_GROUP_MODE_LABELS, MAP_SLOT_LABELS } from "../labels";

type Selection = string | "new" | null;
type SlotCells = Record<MapSlot, (string | null)[]>;
type SlotColors = Record<MapSlot, (string | null)[]>;
type SlotFlags = Record<MapSlot, boolean[]>;

interface FactorRow {
  key: string;
  value: string;
}

interface MapGroupFormState {
  mode: MapGroupMode;
  rowsText: string;
  colsText: string;
  gridRows: number;
  gridCols: number;
  description: string;
  factorLevel: string;
  factors: FactorRow[];
  cells: SlotCells;
  colors: SlotColors;
  landmarks: SlotFlags;
  activeSlot: MapSlot;
  spawnA: number;
  spawnB: number;
  troopProfileVersionId: string;
  formalTrials: number;
  practiceTurnCap: string;
  practiceTurnSeconds: string;
  formalTurnCap: string;
  formalTurnSeconds: string;
  restSeconds: string;
  randomizeFormal: boolean;
  basePayYuan: string;
  performanceRateYuan: string;
  performanceFloorYuan: string;
  performanceCapYuan: string;
  showupPayYuan: string;
}

interface ProfileEntry {
  profile: TroopProfile;
  version: TroopProfileVersion;
}

const DEFAULT_ROWS = 7;
const DEFAULT_COLS = 7;
const DEFAULT_PAYMENT = {
  basePayCents: 1000,
  performanceRateCents: 1,
  performanceFloorCents: 3500,
  performanceCapCents: 5500,
  showupPayCents: 1000,
};

function emptyCells(total: number): (string | null)[] {
  return Array.from({ length: total }, () => null);
}

function emptySlotCells(total: number): SlotCells {
  return {
    Both: emptyCells(total),
    A: emptyCells(total),
    B: emptyCells(total),
  };
}

function emptyFlags(total: number): boolean[] {
  return Array.from({ length: total }, () => false);
}

function emptySlotFlags(total: number): SlotFlags {
  return {
    Both: emptyFlags(total),
    A: emptyFlags(total),
    B: emptyFlags(total),
  };
}

function normalizeFlags(source: number[] | undefined, total: number): boolean[] {
  const result = emptyFlags(total);
  if (!source) return result;
  for (const index of source) {
    if (Number.isInteger(index) && index >= 0 && index < total) {
      result[index] = true;
    }
  }
  return result;
}

function resizeFlags(
  source: boolean[],
  oldRows: number,
  oldCols: number,
  rows: number,
  cols: number,
): boolean[] {
  const result = emptyFlags(rows * cols);
  if (oldRows <= 0 || oldCols <= 0) return result;
  for (let row = 0; row < Math.min(rows, oldRows); row += 1) {
    for (let col = 0; col < Math.min(cols, oldCols); col += 1) {
      result[row * cols + col] = source[row * oldCols + col] ?? false;
    }
  }
  return result;
}

function normalizeCells(source: (string | null)[] | undefined, total: number): (string | null)[] {
  const result = emptyCells(total);
  if (!source) return result;
  for (let index = 0; index < Math.min(source.length, total); index += 1) {
    result[index] = source[index] ?? null;
  }
  return result;
}

function resizeCells(
  source: (string | null)[],
  oldRows: number,
  oldCols: number,
  rows: number,
  cols: number,
): (string | null)[] {
  const result = emptyCells(rows * cols);
  if (oldRows <= 0 || oldCols <= 0) return result;
  for (let row = 0; row < Math.min(rows, oldRows); row += 1) {
    for (let col = 0; col < Math.min(cols, oldCols); col += 1) {
      result[row * cols + col] = source[row * oldCols + col] ?? null;
    }
  }
  return result;
}

function remapCellIndex(
  index: number,
  oldRows: number,
  oldCols: number,
  rows: number,
  cols: number,
): number | null {
  if (
    !Number.isInteger(index) ||
    oldRows <= 0 ||
    oldCols <= 0 ||
    index < 0 ||
    index >= oldRows * oldCols
  ) {
    return null;
  }
  const row = Math.floor(index / oldCols);
  const col = index % oldCols;
  if (row >= rows || col >= cols) return null;
  return row * cols + col;
}

function parseDimension(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed) || parsed < 2) return null;
  return parsed;
}

function parsePositiveInteger(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed) || parsed < 1) return null;
  return parsed;
}

function parsePositiveCents(value: string): number | null {
  const cents = centsFromYuan(value);
  if (cents === null || cents <= 0) return null;
  return cents;
}

function parseNonNegativeCents(value: string): number | null {
  const cents = centsFromYuan(value);
  if (cents === null || cents < 0) return null;
  return cents;
}

function newFormState(profileVersionId: string, formalTrials: number): MapGroupFormState {
  const total = DEFAULT_ROWS * DEFAULT_COLS;
  return {
    mode: "both",
    rowsText: String(DEFAULT_ROWS),
    colsText: String(DEFAULT_COLS),
    gridRows: DEFAULT_ROWS,
    gridCols: DEFAULT_COLS,
    description: "",
    factorLevel: "",
    factors: [],
    cells: emptySlotCells(total),
    colors: emptySlotCells(total),
    landmarks: emptySlotFlags(total),
    activeSlot: "Both",
    spawnA: 0,
    spawnB: total - 1,
    troopProfileVersionId: profileVersionId,
    formalTrials,
    practiceTurnCap: "20",
    practiceTurnSeconds: "60",
    formalTurnCap: "20",
    formalTurnSeconds: "30",
    restSeconds: "60",
    randomizeFormal: true,
    basePayYuan: yuanFromCents(DEFAULT_PAYMENT.basePayCents),
    performanceRateYuan: yuanFromCents(DEFAULT_PAYMENT.performanceRateCents),
    performanceFloorYuan: yuanFromCents(DEFAULT_PAYMENT.performanceFloorCents),
    performanceCapYuan: yuanFromCents(DEFAULT_PAYMENT.performanceCapCents),
    showupPayYuan: yuanFromCents(DEFAULT_PAYMENT.showupPayCents),
  };
}

function formFromVersion(version: MapGroupVersion): MapGroupFormState {
  const total = version.rows * version.cols;
  const cells = emptySlotCells(total);
  const colors = emptySlotCells(total);
  const landmarks = emptySlotFlags(total);
  for (const map of version.maps) {
    cells[map.slot] = normalizeCells(map.cells, total);
    colors[map.slot] = normalizeCells(map.colors, total);
    landmarks[map.slot] = normalizeFlags(map.landmarkCells, total);
  }
  const firstMap = version.maps[0];
  return {
    mode: version.mode,
    rowsText: String(version.rows),
    colsText: String(version.cols),
    gridRows: version.rows,
    gridCols: version.cols,
    description: firstMap?.description ?? "",
    factorLevel: firstMap?.factorLevel ?? "",
    factors: Object.entries(version.factors ?? {}).map(([key, value]) => ({ key, value })),
    cells,
    colors,
    landmarks,
    activeSlot: version.mode === "both" ? "Both" : "A",
    spawnA: version.spawns.A,
    spawnB: version.spawns.B,
    troopProfileVersionId: version.profile.versionId,
    formalTrials: version.formalTrials,
    practiceTurnCap: String(version.practiceTurnCap),
    practiceTurnSeconds: String(version.practiceTurnSeconds),
    formalTurnCap: String(version.formalTurnCap),
    formalTurnSeconds: String(version.formalTurnSeconds),
    restSeconds: String(version.restSeconds),
    randomizeFormal: version.randomizeFormal,
    basePayYuan: yuanFromCents(version.payment.basePayCents),
    performanceRateYuan: yuanFromCents(version.payment.performanceRateCents),
    performanceFloorYuan: yuanFromCents(version.payment.performanceFloorCents),
    performanceCapYuan: yuanFromCents(version.payment.performanceCapCents),
    showupPayYuan: yuanFromCents(version.payment.showupPayCents),
  };
}

function preferredProfileEntry(profiles: TroopProfile[]): ProfileEntry | null {
  const entries = profiles.flatMap((profile) =>
    profile.versions.map((version) => ({ profile, version })),
  );
  return (
    entries.find((entry) => entry.profile.builtIn && entry.version.status === "published") ??
    entries.find((entry) => entry.version.status === "published") ??
    null
  );
}

function cellPosition(index: number, cols: number): string {
  return `第 ${Math.floor(index / cols) + 1} 行第 ${(index % cols) + 1} 列`;
}

export function MapGroupsPage() {
  const { notify, confirm } = useUi();
  const [versions, setVersions] = useState<MapGroupVersion[]>([]);
  const [profiles, setProfiles] = useState<TroopProfile[]>([]);
  const [selection, setSelection] = useState<Selection>(null);
  const [form, setForm] = useState<MapGroupFormState>(() => newFormState("", 0));
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(() => new Set());
  const [batchColor, setBatchColor] = useState("#FFFFFF");
  const [previewRow, setPreviewRow] = useState(1);
  const [loading, setLoading] = useState(true);
  const [reloadNonce, setReloadNonce] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadTarget, setUploadTarget] = useState<{
    slot: MapSlot;
    indices: number[];
    session: number;
  } | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const editSessionRef = useRef(0);
  const formRef = useRef(form);
  const selectionAnchorRef = useRef<number | null>(null);

  useEffect(() => {
    formRef.current = form;
  }, [form]);

  const selectedVersion =
    selection !== "new" && selection !== null
      ? versions.find((version) => version.id === selection) ?? null
      : null;
  const isNew = selection === "new";
  const readOnly = selectedVersion !== null && selectedVersion.status !== "draft";

  const profileEntries = useMemo(
    () =>
      profiles.flatMap((profile) =>
        profile.versions.map((version) => ({ profile, version })),
      ),
    [profiles],
  );
  const selectedProfileEntry =
    profileEntries.find((entry) => entry.version.id === form.troopProfileVersionId) ?? null;
  const selectedProfileRows =
    selectedProfileEntry?.version.rows ??
    (selectedVersion?.profile.versionId === form.troopProfileVersionId
      ? selectedVersion.profile.rows
      : []);
  const profileOptions = useMemo(() => {
    const entries = profileEntries.filter(
      (entry) =>
        entry.version.status === "published" ||
        entry.version.id === form.troopProfileVersionId,
    );
    return [...entries].sort((left, right) => {
      if (left.profile.builtIn !== right.profile.builtIn) {
        return left.profile.builtIn ? -1 : 1;
      }
      if (left.profile.name !== right.profile.name) {
        return left.profile.name.localeCompare(right.profile.name, "zh-CN");
      }
      return right.version.version - left.version.version;
    });
  }, [profileEntries, form.troopProfileVersionId]);

  const applyVersion = useCallback((version: MapGroupVersion) => {
    editSessionRef.current += 1;
    setSelection(version.id);
    setForm(formFromVersion(version));
    setSelectedIndices(new Set());
    selectionAnchorRef.current = null;
    setPreviewRow(version.profile.rows.length > 1 ? 1 : 0);
    setValidationErrors([]);
    setSaveError(null);
    setImageError(null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [mapResponse, profileResponse] = await Promise.all([
          adminApi.get<MapGroupListResponse>("/map-groups"),
          adminApi.get<TroopProfileListResponse>("/troop-profiles"),
        ]);
        if (cancelled) return;
        setVersions(mapResponse.mapGroups);
        setProfiles(profileResponse.profiles);
        const preferred =
          mapResponse.mapGroups.find((version) => version.status === "published") ??
          mapResponse.mapGroups[0] ??
          null;
        if (preferred) {
          applyVersion(preferred);
        } else {
          const entry = preferredProfileEntry(profileResponse.profiles);
          setForm(newFormState(entry?.version.id ?? "", entry?.version.formalTrials ?? 0));
          setPreviewRow(entry && entry.version.rows.length > 1 ? 1 : 0);
        }
        setError(null);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [applyVersion, reloadNonce]);

  const reload = useCallback(
    async (preferredId?: string) => {
      const [mapResponse, profileResponse] = await Promise.all([
        adminApi.get<MapGroupListResponse>("/map-groups"),
        adminApi.get<TroopProfileListResponse>("/troop-profiles"),
      ]);
      setVersions(mapResponse.mapGroups);
      setProfiles(profileResponse.profiles);
      if (preferredId) {
        const target = mapResponse.mapGroups.find((version) => version.id === preferredId);
        if (target) applyVersion(target);
      }
    },
    [applyVersion],
  );

  const totalCells = form.gridRows * form.gridCols;
  const activeCells = form.cells[form.activeSlot] ?? emptyCells(totalCells);
  const activeColors = form.colors[form.activeSlot] ?? emptyCells(totalCells);
  const activeLandmarks = form.landmarks[form.activeSlot] ?? emptyFlags(totalCells);
  const effectiveSelectedIndices = [...selectedIndices]
    .filter((index) => index >= 0 && index < totalCells)
    .sort((left, right) => left - right);
  const effectiveSelectedSet = new Set(effectiveSelectedIndices);
  const singleSelectedIndex =
    effectiveSelectedIndices.length === 1 ? effectiveSelectedIndices[0] : null;
  const boardVisuals = useMemo(
    () =>
      activeCells.map((assetId, index) => ({
        color: activeColors[index] ?? null,
        backgroundAssetId: assetId,
      })),
    [activeCells, activeColors],
  );

  const parsedRows = parseDimension(form.rowsText);
  const parsedCols = parseDimension(form.colsText);
  const dimensionsValid =
    parsedRows !== null &&
    parsedCols !== null &&
    parsedRows * parsedCols <= 100;
  const totalFromInput =
    parsedRows !== null && parsedCols !== null ? parsedRows * parsedCols : null;
  const dimensionsError =
    parsedRows === null || parsedCols === null
      ? "行数和列数必须是大于等于 2 的整数"
      : parsedRows * parsedCols > 100
        ? "网格总格数不能超过 100"
        : null;

  const description = form.description.trim();
  const factorLevel = form.factorLevel.trim();
  const descriptionError = !description
    ? "内容描述不能为空"
    : description.includes("-")
      ? "内容描述不能包含连字符"
      : null;
  const factorLevelError = !factorLevel
    ? "因素水平不能为空"
    : factorLevel.includes("-")
      ? "因素水平不能包含连字符"
      : null;
  const sizeToken = dimensionsValid ? `${parsedRows}*${parsedCols}` : "rows*cols";
  const namePrefix = `${description || "内容描述"}-${sizeToken}-${factorLevel || "因素水平"}`;
  const nameInvalid = descriptionError !== null || factorLevelError !== null || !dimensionsValid;
  const mapSlots: MapSlot[] = form.mode === "both" ? ["Both"] : ["A", "B"];

  const profileFormalTrials =
    selectedProfileEntry?.version.formalTrials ??
    (selectedVersion?.profile.versionId === form.troopProfileVersionId
      ? Math.max(0, selectedVersion.profile.rows.length - 1)
      : null);
  const formalTrialsMismatch =
    profileFormalTrials !== null && form.formalTrials !== profileFormalTrials;

  const previewRowIndex =
    selectedProfileRows.length === 0
      ? -1
      : Math.min(Math.max(previewRow, 0), selectedProfileRows.length - 1);
  const previewRowValues =
    previewRowIndex >= 0 ? selectedProfileRows[previewRowIndex] : null;

  const boardCellSize = Math.max(
    14,
    Math.min(60, Math.floor(700 / Math.max(form.gridRows, form.gridCols))),
  );
  const boardWidth = form.gridCols * boardCellSize;
  const boardHeight = form.gridRows * boardCellSize;

  function patchForm(patch: Partial<MapGroupFormState>) {
    setForm((current) => ({ ...current, ...patch }));
  }

  function clearSelection() {
    setSelectedIndices(new Set());
    selectionAnchorRef.current = null;
  }

  function switchSlot(slot: MapSlot) {
    if (form.activeSlot === slot) return;
    patchForm({ activeSlot: slot });
    clearSelection();
  }

  function toggleCellSelection(index: number, event: MouseEvent<HTMLButtonElement>) {
    if (event.shiftKey) {
      setSelectedIndices((current) => {
        const anchor = selectionAnchorRef.current ?? index;
        const start = Math.min(anchor, index);
        const end = Math.max(anchor, index);
        const next = new Set(current);
        for (let cell = start; cell <= end; cell += 1) next.add(cell);
        return next;
      });
      return;
    }
    if (event.metaKey || event.ctrlKey) {
      setSelectedIndices((current) => {
        const next = new Set(current);
        if (next.has(index)) next.delete(index);
        else next.add(index);
        return next;
      });
      selectionAnchorRef.current = index;
      return;
    }
    selectionAnchorRef.current = index;
    setSelectedIndices(new Set([index]));
  }

  function selectAllCells() {
    const next = new Set<number>();
    for (let index = 0; index < totalCells; index += 1) next.add(index);
    setSelectedIndices(next);
    selectionAnchorRef.current = totalCells > 0 ? totalCells - 1 : null;
  }

  function addFactorRow() {
    if (readOnly) return;
    setForm((current) => ({
      ...current,
      factors: [...current.factors, { key: "", value: "" }],
    }));
  }

  function updateFactorRow(index: number, field: "key" | "value", value: string) {
    if (readOnly) return;
    setForm((current) => ({
      ...current,
      factors: current.factors.map((row, rowIndex) =>
        rowIndex === index ? { ...row, [field]: value } : row,
      ),
    }));
  }

  function removeFactorRow(index: number) {
    if (readOnly) return;
    setForm((current) => ({
      ...current,
      factors: current.factors.filter((_, rowIndex) => rowIndex !== index),
    }));
  }

  function setSelectedLandmark(landmark: boolean) {
    if (readOnly || effectiveSelectedIndices.length === 0) return;
    const slot = form.activeSlot;
    const selected = new Set(effectiveSelectedIndices);
    setForm((current) => ({
      ...current,
      landmarks: {
        ...current.landmarks,
        [slot]: current.landmarks[slot].map((value, index) =>
          selected.has(index) ? landmark : value,
        ),
      },
    }));
    notify(
      landmark
        ? `已将 ${selected.size} 个格子标记为地标`
        : `已取消 ${selected.size} 个格子的地标标记`,
    );
  }

  function changeMode(mode: MapGroupMode) {
    if (readOnly) return;
    editSessionRef.current += 1;
    setForm((current) => ({
      ...current,
      mode,
      activeSlot:
        mode === "both"
          ? "Both"
          : current.activeSlot === "Both"
            ? "A"
            : current.activeSlot,
    }));
    clearSelection();
  }

  function changeDimension(field: "rows" | "cols", value: string) {
    if (readOnly) return;
    setForm((current) => {
      const rowsText = field === "rows" ? value : current.rowsText;
      const colsText = field === "cols" ? value : current.colsText;
      const rows = parseDimension(rowsText);
      const cols = parseDimension(colsText);
      const textPatch =
        field === "rows" ? { rowsText: value } : { colsText: value };
      if (rows === null || cols === null || rows * cols > 100) {
        return { ...current, ...textPatch };
      }
      if (rows === current.gridRows && cols === current.gridCols) {
        return { ...current, ...textPatch };
      }
      const total = rows * cols;
      const cells: SlotCells = {
        Both: resizeCells(
          current.cells.Both,
          current.gridRows,
          current.gridCols,
          rows,
          cols,
        ),
        A: resizeCells(current.cells.A, current.gridRows, current.gridCols, rows, cols),
        B: resizeCells(current.cells.B, current.gridRows, current.gridCols, rows, cols),
      };
      const colors: SlotColors = {
        Both: resizeCells(
          current.colors.Both,
          current.gridRows,
          current.gridCols,
          rows,
          cols,
        ),
        A: resizeCells(current.colors.A, current.gridRows, current.gridCols, rows, cols),
        B: resizeCells(current.colors.B, current.gridRows, current.gridCols, rows, cols),
      };
      const landmarks: SlotFlags = {
        Both: resizeFlags(
          current.landmarks.Both,
          current.gridRows,
          current.gridCols,
          rows,
          cols,
        ),
        A: resizeFlags(current.landmarks.A, current.gridRows, current.gridCols, rows, cols),
        B: resizeFlags(current.landmarks.B, current.gridRows, current.gridCols, rows, cols),
      };
      let spawnA = remapCellIndex(
        current.spawnA,
        current.gridRows,
        current.gridCols,
        rows,
        cols,
      );
      let spawnB = remapCellIndex(
        current.spawnB,
        current.gridRows,
        current.gridCols,
        rows,
        cols,
      );
      if (spawnA === null) spawnA = 0;
      if (spawnB === null) spawnB = total - 1;
      if (spawnA === spawnB) spawnB = spawnA === total - 1 ? 0 : total - 1;
      return {
        ...current,
        ...textPatch,
        gridRows: rows,
        gridCols: cols,
        cells,
        colors,
        landmarks,
        spawnA,
        spawnB,
      };
    });
    const rows = parseDimension(field === "rows" ? value : form.rowsText);
    const cols = parseDimension(field === "cols" ? value : form.colsText);
    if (
      rows !== null &&
      cols !== null &&
      rows * cols <= 100 &&
      (rows !== form.gridRows || cols !== form.gridCols)
    ) {
      editSessionRef.current += 1;
      setSelectedIndices((current) => {
        const next = new Set<number>();
        for (const index of current) {
          const remapped = remapCellIndex(
            index,
            form.gridRows,
            form.gridCols,
            rows,
            cols,
          );
          if (remapped !== null) next.add(remapped);
        }
        return next;
      });
      const anchor = selectionAnchorRef.current;
      selectionAnchorRef.current =
        anchor === null
          ? null
          : remapCellIndex(anchor, form.gridRows, form.gridCols, rows, cols);
    }
  }

  function changeProfile(profileVersionId: string) {
    if (readOnly) return;
    const entry = profileEntries.find(
      (candidate) => candidate.version.id === profileVersionId,
    );
    setForm((current) => ({
      ...current,
      troopProfileVersionId: profileVersionId,
      formalTrials: entry?.version.formalTrials ?? 0,
    }));
    setPreviewRow(entry && entry.version.rows.length > 1 ? 1 : 0);
  }

  function setSpawnAtSelected(kind: "A" | "B") {
    if (readOnly || singleSelectedIndex === null) {
      notify("请先选择一个格子", "error");
      return;
    }
    const index = singleSelectedIndex;
    const other = kind === "A" ? form.spawnB : form.spawnA;
    if (index === other) {
      notify("两个出生格不能重合", "error");
      return;
    }
    patchForm(kind === "A" ? { spawnA: index } : { spawnB: index });
    notify(`第 ${index} 格已设为出生格 ${kind}`);
  }

  function beginUpload() {
    if (readOnly || effectiveSelectedIndices.length === 0) {
      notify("请先选择至少一个格子", "error");
      return;
    }
    setUploadTarget({
      slot: form.activeSlot,
      indices: effectiveSelectedIndices,
      session: editSessionRef.current,
    });
    fileInputRef.current?.click();
  }

  function clearSelectedImages() {
    if (readOnly || effectiveSelectedIndices.length === 0) return;
    const slot = form.activeSlot;
    const selected = new Set(effectiveSelectedIndices);
    setForm((current) => ({
      ...current,
      cells: {
        ...current.cells,
        [slot]: current.cells[slot].map((cell, cellIndex) =>
          selected.has(cellIndex) ? null : cell,
        ),
      },
    }));
    notify(`已清除 ${selected.size} 个格子的图片`);
  }

  function restoreSelectedWhite() {
    if (readOnly || effectiveSelectedIndices.length === 0) return;
    const slot = form.activeSlot;
    const selected = new Set(effectiveSelectedIndices);
    setForm((current) => ({
      ...current,
      cells: {
        ...current.cells,
        [slot]: current.cells[slot].map((cell, cellIndex) =>
          selected.has(cellIndex) ? null : cell,
        ),
      },
      colors: {
        ...current.colors,
        [slot]: current.colors[slot].map((color, cellIndex) =>
          selected.has(cellIndex) ? null : color,
        ),
      },
    }));
    notify(`已将 ${selected.size} 个格子恢复为白色`);
  }

  function applyBackgroundColor() {
    if (readOnly || effectiveSelectedIndices.length === 0) return;
    const slot = form.activeSlot;
    const selected = new Set(effectiveSelectedIndices);
    const color = batchColor.toUpperCase();
    setForm((current) => ({
      ...current,
      colors: {
        ...current.colors,
        [slot]: current.colors[slot].map((value, cellIndex) =>
          selected.has(cellIndex) ? color : value,
        ),
      },
    }));
    notify(`已设置 ${selected.size} 个格子的背景颜色`);
  }

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    const target = uploadTarget;
    event.target.value = "";
    setUploadTarget(null);
    if (!file || !target || readOnly) return;
    if (file.type !== "image/png" && file.type !== "image/jpeg") {
      setImageError("地图单元格仅支持 PNG/JPG 图片");
      notify("地图单元格仅支持 PNG/JPG 图片", "error");
      return;
    }
    setUploading(true);
    setImageError(null);
    try {
      const response = await adminApi.upload<MediaUploadResponse>(
        "/media",
        imageUploadForm(file, "map-cell"),
      );
      const slotCells = formRef.current.cells[target.slot];
      const targets = target.indices.filter(
        (index) => index >= 0 && index < slotCells.length,
      );
      if (target.session !== editSessionRef.current || targets.length === 0) {
        notify("已切换版本，过期上传已丢弃", "error");
        return;
      }
      setForm((current) => {
        const currentCells = current.cells[target.slot];
        const selected = new Set(targets);
        return {
          ...current,
          cells: {
            ...current.cells,
            [target.slot]: currentCells.map((cell, cellIndex) =>
              selected.has(cellIndex) ? response.asset.id : cell,
            ),
          },
        };
      });
      notify(`已上传图片到 ${targets.length} 个格子`);
    } catch (err) {
      setImageError(errorMessage(err));
      notify(errorMessage(err), "error");
    } finally {
      setUploading(false);
    }
  }

  function buildPayload(): { payload: MapGroupDraftPayload | null; errors: string[] } {
    const errors: string[] = [];
    if (dimensionsError) errors.push(dimensionsError);
    if (descriptionError) errors.push(descriptionError);
    if (factorLevelError) errors.push(factorLevelError);
    const factors: Record<string, string> = {};
    if (form.factors.length > 50) {
      errors.push("分析因素不能超过 50 项");
    }
    form.factors.forEach((row, index) => {
      const key = row.key.trim();
      const value = row.value.trim();
      if (!key || !value) {
        errors.push(`分析因素第 ${index + 1} 行的名称和取值都不能为空`);
        return;
      }
      if (Object.prototype.hasOwnProperty.call(factors, key)) {
        errors.push(`分析因素名称重复：${key}`);
        return;
      }
      factors[key] = value;
    });
    const total =
      parsedRows !== null && parsedCols !== null ? parsedRows * parsedCols : null;
    if (
      total !== null &&
      total > 0 &&
      total !== form.gridRows * form.gridCols
    ) {
      errors.push("地图尺寸与当前格子数量不一致");
    }
    for (const slot of mapSlots) {
      if ((form.cells[slot] ?? []).length !== form.gridRows * form.gridCols) {
        errors.push(`${MAP_SLOT_LABELS[slot]} 地图的格子数量必须为 ${form.gridRows * form.gridCols}`);
      }
      if ((form.colors[slot] ?? []).length !== form.gridRows * form.gridCols) {
        errors.push(`${MAP_SLOT_LABELS[slot]} 地图的格子颜色数量必须为 ${form.gridRows * form.gridCols}`);
      }
    }
    if (
      !Number.isInteger(form.spawnA) ||
      !Number.isInteger(form.spawnB) ||
      form.spawnA < 0 ||
      form.spawnB < 0 ||
      form.spawnA >= form.gridRows * form.gridCols ||
      form.spawnB >= form.gridRows * form.gridCols
    ) {
      errors.push("出生格必须在网格范围内");
    } else if (form.spawnA === form.spawnB) {
      errors.push("两个出生格不能重合");
    }
    if (!selectedProfileEntry) {
      errors.push("请选择已发布的兵力配置方案版本");
    } else if (selectedProfileEntry.version.status !== "published") {
      errors.push("所选的兵力配置方案版本不是已发布状态，请选择新的已发布版本");
    }
    if (selectedProfileEntry && form.formalTrials !== selectedProfileEntry.version.formalTrials) {
      errors.push(
        `地图组正式对局数与兵力配置不一致（方案为 ${selectedProfileEntry.version.formalTrials} 局）`,
      );
    }
    const practiceTurnCap = parsePositiveInteger(form.practiceTurnCap);
    const practiceTurnSeconds = parsePositiveInteger(form.practiceTurnSeconds);
    const formalTurnCap = parsePositiveInteger(form.formalTurnCap);
    const formalTurnSeconds = parsePositiveInteger(form.formalTurnSeconds);
    const restSeconds = parsePositiveInteger(form.restSeconds);
    if (practiceTurnCap === null) errors.push("练习回合上限必须是正整数");
    if (practiceTurnSeconds === null) errors.push("练习回合倒计时必须是正整数");
    if (formalTurnCap === null) errors.push("正式回合上限必须是正整数");
    if (formalTurnSeconds === null) errors.push("正式回合倒计时必须是正整数");
    if (restSeconds === null) errors.push("局间休息必须是正整数");
    const basePayCents = parsePositiveCents(form.basePayYuan);
    const performanceRateCents = parsePositiveCents(form.performanceRateYuan);
    const performanceFloorCents = parseNonNegativeCents(form.performanceFloorYuan);
    const performanceCapCents = parsePositiveCents(form.performanceCapYuan);
    const showupPayCents = parsePositiveCents(form.showupPayYuan);
    if (basePayCents === null) errors.push("基础被试费必须是大于 0 的金额");
    if (performanceRateCents === null) errors.push("绩效单价必须是大于 0 的金额");
    if (performanceFloorCents === null) errors.push("绩效保底必须是非负金额");
    if (performanceCapCents === null) errors.push("绩效上限必须是大于 0 的金额");
    if (showupPayCents === null) errors.push("到场费必须是大于 0 的金额");
    if (
      performanceFloorCents !== null &&
      performanceCapCents !== null &&
      performanceFloorCents > performanceCapCents
    ) {
      errors.push("绩效保底不能高于绩效上限");
    }
    if (errors.length > 0) return { payload: null, errors };
    const payload: MapGroupDraftPayload = {
      mode: form.mode,
      rows: parsedRows as number,
      cols: parsedCols as number,
      spawns: { A: form.spawnA, B: form.spawnB },
      troopProfileVersionId: form.troopProfileVersionId,
      practiceTrials: 1,
      formalTrials: form.formalTrials,
      practiceTurnCap: practiceTurnCap as number,
      practiceTurnSeconds: practiceTurnSeconds as number,
      formalTurnCap: formalTurnCap as number,
      formalTurnSeconds: formalTurnSeconds as number,
      restSeconds: restSeconds as number,
      randomizeFormal: form.randomizeFormal,
      factors,
      payment: {
        basePayCents: basePayCents as number,
        performanceRateCents: performanceRateCents as number,
        performanceFloorCents: performanceFloorCents as number,
        performanceCapCents: performanceCapCents as number,
        showupPayCents: showupPayCents as number,
      },
      maps: mapSlots.map((slot) => ({
        slot,
        description: description,
        factorLevel: factorLevel,
        cells: (form.cells[slot] ?? []).slice(0, totalFromInput ?? 0),
        colors: (form.colors[slot] ?? []).slice(0, totalFromInput ?? 0),
        landmarkCells: (form.landmarks[slot] ?? [])
          .slice(0, totalFromInput ?? 0)
          .flatMap((isLandmark, index) => (isLandmark ? [index] : [])),
      })),
    };
    return { payload, errors: [] };
  }

  async function persistDraft(showNotice: boolean): Promise<string | null> {
    const result = buildPayload();
    setValidationErrors(result.errors);
    if (!result.payload) {
      setSaveError(null);
      if (showNotice) notify("请先修正地图组配置错误", "error");
      return null;
    }
    setSaving(true);
    setSaveError(null);
    try {
      if (isNew || selection === null) {
        const response = await adminApi.post<MapGroupResponse>(
          "/map-groups",
          result.payload,
        );
        await reload(response.mapGroup.id);
        if (showNotice) {
          notify(`地图组草稿已创建，第 ${response.mapGroup.version} 版`);
        }
        return response.mapGroup.id;
      }
      const response = await adminApi.patch<MapGroupResponse>(
        `/map-groups/${selection}`,
        result.payload,
      );
      await reload(response.mapGroup.id);
      if (showNotice) notify("地图组草稿已保存");
      return response.mapGroup.id;
    } catch (err) {
      setSaveError(errorMessage(err));
      if (showNotice) notify(errorMessage(err), "error");
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function handleSave() {
    await persistDraft(true);
  }

  async function handlePublish() {
    const check = buildPayload();
    setValidationErrors(check.errors);
    if (!check.payload) {
      notify("请先修正地图组配置错误", "error");
      return;
    }
    const ok = await confirm({
      title: "发布地图组版本",
      message:
        "发布后同名已发布的旧版本会归档，已使用旧版本创建的房间不受影响。发布后本版本不可修改。",
      confirmLabel: "发布",
    });
    if (!ok) return;
    setPublishing(true);
    setSaveError(null);
    try {
      const id = await persistDraft(false);
      if (!id) return;
      await adminApi.post(`/map-groups/${id}/publish`);
      await reload(id);
      notify("地图组版本已发布");
    } catch (err) {
      setSaveError(errorMessage(err));
      notify(errorMessage(err), "error");
    } finally {
      setPublishing(false);
    }
  }

  function startNewGroup() {
    editSessionRef.current += 1;
    const entry = preferredProfileEntry(profiles);
    setSelection("new");
    setForm(newFormState(entry?.version.id ?? "", entry?.version.formalTrials ?? 0));
    clearSelection();
    setPreviewRow(entry && entry.version.rows.length > 1 ? 1 : 0);
    setValidationErrors([]);
    setSaveError(null);
    setImageError(null);
  }

  function startNextVersion() {
    editSessionRef.current += 1;
    setSelection("new");
    clearSelection();
    setValidationErrors([]);
    setSaveError(null);
    notify("已基于当前版本载入新草稿，保存后生成下一版本");
  }

  const versionGroups = useMemo(() => {
    const groups = new Map<string, MapGroupVersion[]>();
    const ordered = [...versions].sort(
      (left, right) =>
        new Date(right.createdAt).getTime() - new Date(left.createdAt).getTime(),
    );
    for (const version of ordered) {
      const list = groups.get(version.name) ?? [];
      list.push(version);
      groups.set(version.name, list);
    }
    for (const list of groups.values()) {
      list.sort((left, right) => right.version - left.version);
    }
    return Array.from(groups.entries()).map(([name, items]) => ({ name, versions: items }));
  }, [versions]);

  const editorTitle = isNew
    ? "新建地图组"
    : selectedVersion
      ? `${selectedVersion.name} · 第 ${selectedVersion.version} 版`
      : "地图组";

  return (
    <div>
      <PageHeader
        title="地图组"
        subtitle="配置地图视觉、出生格、回合参数与费用。地图组固定绑定一个已发布的兵力配置方案，正式对局数必须与方案正式行数一致。"
        actions={
          <button
            type="button"
            className="admin-btn admin-btn-primary"
            onClick={startNewGroup}
            data-testid="map-group-create"
          >
            <Plus size={16} />
            新建地图组
          </button>
        }
      />

      {error ? (
        <ErrorNotice
          message={error}
          onRetry={() => setReloadNonce((value) => value + 1)}
        />
      ) : null}

      {loading ? (
        <LoadingBlock rows={7} label="正在加载地图组" />
      ) : versions.length === 0 && selection !== "new" ? (
        <EmptyState
          icon={MapIcon}
          title="暂无地图组版本"
          description="新建并发布地图组后，才能为它创建指导语和 Room。"
          action={
            <button type="button" className="admin-btn admin-btn-primary" onClick={startNewGroup}>
              新建地图组
            </button>
          }
        />
      ) : (
        <div className="admin-layout-columns admin-layout-columns-wide">
          <aside className="admin-card admin-sticky-side">
            <h2 className="admin-section-title">版本列表</h2>
            <div className="admin-version-list">
              {versionGroups.map((group) => (
                <div key={group.name} className="admin-profile-group">
                  <div className="admin-profile-group-head" title={group.name}>
                    <span className="admin-map-group-name">{group.name}</span>
                  </div>
                  {group.versions.map((version) => (
                    <button
                      type="button"
                      key={version.id}
                      className={`admin-version-item${
                        selection === version.id ? " active" : ""
                      }`}
                      onClick={() => applyVersion(version)}
                      data-testid={`map-group-version-${version.id}`}
                    >
                      <div className="admin-version-item-head">
                        <span>第 {version.version} 版</span>
                        <VersionStatusChip status={version.status} />
                      </div>
                      <div className="admin-version-item-meta">
                        {MAP_GROUP_MODE_LABELS[version.mode]} · {version.rows}×
                        {version.cols}
                      </div>
                      <div className="admin-version-item-meta">
                        正式 {version.formalTrials} 局 · {version.profile.name} v
                        {version.profile.version}
                      </div>
                      <div className="admin-version-item-meta">
                        发布：{formatDateTime(version.publishedAt)}
                      </div>
                    </button>
                  ))}
                </div>
              ))}
              {isNew ? (
                <div className="admin-version-item active" style={{ cursor: "default" }}>
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
                  {selectedVersion ? (
                    <VersionStatusChip status={selectedVersion.status} />
                  ) : (
                    <StatusChip>未保存</StatusChip>
                  )}
                  <StatusChip tone="info">{MAP_GROUP_MODE_LABELS[form.mode]}</StatusChip>
                  {readOnly ? <span className="admin-hint">只读</span> : null}
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
                      onClick={startNextVersion}
                      data-testid="map-group-new-version"
                    >
                      <Plus size={15} />
                      基于此版本新建草稿
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary"
                      onClick={() => void handleSave()}
                      disabled={saving || publishing}
                      data-testid="map-group-save"
                    >
                      <Save size={15} />
                      {saving ? "保存中" : "保存草稿"}
                    </button>
                    <button
                      type="button"
                      className="admin-btn admin-btn-primary"
                      onClick={() => void handlePublish()}
                      disabled={saving || publishing}
                      data-testid="map-group-publish"
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
                该版本已发布或归档，所有配置只读。可基于此版本新建草稿后继续修改。
              </div>
            ) : null}
            {profileOptions.length === 0 ? (
              <InlineNotice tone="warning">
                还没有已发布的兵力配置方案。请先在“兵力方案”页创建并发布方案，再保存地图组。
              </InlineNotice>
            ) : null}

            <div className="admin-form-section">
              <h3 className="admin-section-title">基本信息</h3>
              <div className="admin-form-row">
                <Field
                  label="地图模式"
                  htmlFor="map-group-mode"
                  hint="Both 单图：双方看到同一张地图。A/B 双图：双方各看一张。"
                >
                  <select
                    id="map-group-mode"
                    className="admin-select"
                    value={form.mode}
                    onChange={(event) =>
                      changeMode(event.target.value === "ab" ? "ab" : "both")
                    }
                    disabled={readOnly}
                    data-testid="map-group-mode"
                  >
                    <option value="both">Both 单图</option>
                    <option value="ab">A/B 双图</option>
                  </select>
                </Field>
                <Field
                  label="行数"
                  htmlFor="map-group-rows"
                  hint="至少 2 行"
                  error={parsedRows === null ? "请输入大于等于 2 的整数" : null}
                >
                  <input
                    id="map-group-rows"
                    className={`admin-input${parsedRows === null ? " admin-field-error" : ""}`}
                    type="number"
                    min="2"
                    step="1"
                    value={form.rowsText}
                    onChange={(event) => changeDimension("rows", event.target.value)}
                    disabled={readOnly}
                    data-testid="map-group-rows"
                  />
                </Field>
                <Field
                  label="列数"
                  htmlFor="map-group-cols"
                  hint="行列总格数不超过 100"
                  error={
                    parsedCols === null
                      ? "请输入大于等于 2 的整数"
                      : totalFromInput !== null && totalFromInput > 100
                        ? "总格数不能超过 100"
                        : null
                  }
                >
                  <input
                    id="map-group-cols"
                    className={`admin-input${parsedCols === null ? " admin-field-error" : ""}`}
                    type="number"
                    min="2"
                    step="1"
                    value={form.colsText}
                    onChange={(event) => changeDimension("cols", event.target.value)}
                    disabled={readOnly}
                    data-testid="map-group-cols"
                  />
                </Field>
              </div>
              <div className="admin-form-row">
                <Field
                  label="内容描述"
                  htmlFor="map-group-description"
                  hint="四段名称的第一段，不能包含连字符。"
                  error={descriptionError}
                >
                  <input
                    id="map-group-description"
                    className={`admin-input${descriptionError ? " admin-field-error" : ""}`}
                    value={form.description}
                    onChange={(event) => patchForm({ description: event.target.value })}
                    disabled={readOnly}
                    placeholder="例如：中心争夺"
                    data-testid="map-group-description"
                  />
                </Field>
                <Field
                  label="因素水平"
                  htmlFor="map-group-factor-level"
                  hint="四段名称的第三段，不能包含连字符。"
                  error={factorLevelError}
                >
                  <input
                    id="map-group-factor-level"
                    className={`admin-input${factorLevelError ? " admin-field-error" : ""}`}
                    value={form.factorLevel}
                    onChange={(event) => patchForm({ factorLevel: event.target.value })}
                    disabled={readOnly}
                    placeholder="例如：高收益"
                    data-testid="map-group-factor-level"
                  />
                </Field>
              </div>
              <div
                className={`admin-name-preview${nameInvalid ? " is-invalid" : ""}`}
                aria-live="polite"
              >
                <div className="admin-label">完整地图名称</div>
                <div className="admin-name-preview-list">
                  {mapSlots.map((slot) => (
                    <code key={slot}>{`${namePrefix}-${slot}`}</code>
                  ))}
                </div>
                <div className="admin-hint">
                  名称格式为 内容描述-尺寸-因素水平-玩家后缀，四段均不能包含连字符。
                  {dimensionsError ? ` ${dimensionsError}。` : ""}
                  指导语名称将使用组前缀：{namePrefix}
                </div>
              </div>
              <div className="admin-form-section">
                <div className="admin-condition-toolbar">
                  <h3 className="admin-section-title" style={{ marginBottom: 0 }}>
                    分析因素
                  </h3>
                  <button
                    type="button"
                    className="admin-btn admin-btn-secondary admin-btn-sm"
                    onClick={addFactorRow}
                    disabled={readOnly || form.factors.length >= 50}
                    data-testid="map-group-add-factor"
                  >
                    <Plus size={14} />
                    添加因素
                  </button>
                </div>
                <p className="admin-hint">
                  可选的结构化条件，会随地图组版本写入导出数据。名称和取值都不能为空，名称不能重复。
                </p>
                {form.factors.length === 0 ? (
                  <p className="admin-hint">未添加分析因素。图表分析和分组可以使用地图组版本或名称。</p>
                ) : (
                  <div className="admin-factor-list">
                    {form.factors.map((row, index) => (
                      <div className="admin-form-row" key={index}>
                        <Field label="因素名称" htmlFor={`map-group-factor-key-${index}`}>
                          <input
                            id={`map-group-factor-key-${index}`}
                            className="admin-input"
                            value={row.key}
                            onChange={(event) =>
                              updateFactorRow(index, "key", event.target.value)
                            }
                            disabled={readOnly}
                            placeholder="例如：landmark"
                            data-testid={`map-group-factor-key-${index}`}
                          />
                        </Field>
                        <Field label="因素取值" htmlFor={`map-group-factor-value-${index}`}>
                          <input
                            id={`map-group-factor-value-${index}`}
                            className="admin-input"
                            value={row.value}
                            onChange={(event) =>
                              updateFactorRow(index, "value", event.target.value)
                            }
                            disabled={readOnly}
                            placeholder="例如：horizontal"
                            data-testid={`map-group-factor-value-${index}`}
                          />
                        </Field>
                        <button
                          type="button"
                          className="admin-btn admin-btn-secondary admin-btn-sm admin-factor-remove"
                          onClick={() => removeFactorRow(index)}
                          disabled={readOnly}
                          aria-label={`删除分析因素 ${index + 1}`}
                          data-testid={`map-group-factor-remove-${index}`}
                        >
                          <X size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="admin-form-row">
                <Field
                  label="兵力配置方案"
                  htmlFor="map-group-profile"
                  hint="仅可选择已发布版本；正式对局数自动取自方案正式行数。"
                >
                  <select
                    id="map-group-profile"
                    className="admin-select"
                    value={form.troopProfileVersionId}
                    onChange={(event) => changeProfile(event.target.value)}
                    disabled={readOnly}
                    data-testid="map-group-profile"
                  >
                    {form.troopProfileVersionId === "" ? (
                      <option value="">请选择已发布的兵力配置方案</option>
                    ) : null}
                    {profileOptions.map((entry) => (
                      <option key={entry.version.id} value={entry.version.id}>
                        {entry.profile.builtIn ? "内置 · " : ""}
                        {entry.profile.name} · 第 {entry.version.version} 版
                        {entry.version.status === "published" ? "" : "（已归档）"}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field
                  label="对局结构"
                  hint={
                    formalTrialsMismatch
                      ? "地图组正式对局数与所选方案不一致。"
                      : "正式对局数等于方案正式行数。"
                  }
                  error={
                    formalTrialsMismatch
                      ? `地图组正式对局数与兵力配置不一致（方案为 ${profileFormalTrials} 局）`
                      : null
                  }
                >
                  <div className="admin-profile-summary">
                    <span className="admin-chip">练习 1 局</span>
                    <span className="admin-chip">正式 {form.formalTrials} 局</span>
                    <span className="admin-hint">
                      方案共 {selectedProfileRows.length} 行（含练习行）
                    </span>
                  </div>
                </Field>
              </div>
            </div>

            <div className="admin-form-section">
              <div className="admin-condition-toolbar">
                <h3 className="admin-section-title" style={{ marginBottom: 0 }}>
                  地图编辑与预览
                </h3>
                <div className="admin-kind-changer">
                  {mapSlots.map((slot) => (
                    <button
                      type="button"
                      key={slot}
                      className={`admin-btn admin-btn-secondary admin-btn-sm admin-kind-button${
                        form.activeSlot === slot ? " active" : ""
                      }`}
                      onClick={() => switchSlot(slot)}
                      data-testid={`map-group-slot-${slot}`}
                    >
                      {MAP_SLOT_LABELS[slot]} 地图
                    </button>
                  ))}
                </div>
              </div>
              <p className="admin-hint">
                点击格子选中，按住 Ctrl/Command 或 Shift 点击可多选。选中后可统一上传
                PNG/JPG 图片、设置背景颜色、清除图片或恢复白色。未设置图片和颜色的格子显示为白色。
                格子编号、选中格与出生格使用覆盖层显示，不改变画布像素。
                地标格只写入分析元数据，用于后续计算地标边界和相对位置，不改变棋盘显示。
              </p>
              <div className="admin-map-toolbar">
                <span className="admin-label" style={{ marginBottom: 0 }}>
                  {MAP_SLOT_LABELS[form.activeSlot]} 地图
                </span>
                <span className="admin-hint">
                  {form.rowsText}×{form.colsText} · {totalCells} 格
                </span>
                <button
                  type="button"
                  className="admin-btn admin-btn-secondary admin-btn-sm"
                  onClick={selectAllCells}
                  data-testid="map-group-select-all"
                >
                  全选
                </button>
                <button
                  type="button"
                  className="admin-btn admin-btn-secondary admin-btn-sm"
                  onClick={clearSelection}
                  disabled={effectiveSelectedIndices.length === 0}
                  data-testid="map-group-clear-selection"
                >
                  清空选择
                </button>
                {!readOnly ? (
                  <>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/png,image/jpeg"
                      hidden
                      onChange={(event) => void handleFileChange(event)}
                      data-testid="map-group-upload-input"
                    />
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary admin-btn-sm"
                      onClick={beginUpload}
                      disabled={effectiveSelectedIndices.length === 0 || uploading}
                      data-testid="map-group-upload-cell"
                    >
                      <Upload size={14} />
                      {uploading ? "上传中" : "上传图片到选中格"}
                    </button>
                    <label className="admin-map-color-control">
                      <span className="admin-hint">背景色</span>
                      <input
                        type="color"
                        className="admin-color-input"
                        value={batchColor}
                        onChange={(event) => setBatchColor(event.target.value)}
                        aria-label="选择背景颜色"
                        data-testid="map-group-color-input"
                      />
                    </label>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary admin-btn-sm"
                      onClick={applyBackgroundColor}
                      disabled={effectiveSelectedIndices.length === 0}
                      data-testid="map-group-apply-color"
                    >
                      设置背景颜色
                    </button>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary admin-btn-sm"
                      onClick={clearSelectedImages}
                      disabled={effectiveSelectedIndices.length === 0}
                      data-testid="map-group-clear-cell"
                    >
                      <X size={14} />
                      清除图片
                    </button>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary admin-btn-sm"
                      onClick={restoreSelectedWhite}
                      disabled={effectiveSelectedIndices.length === 0}
                      data-testid="map-group-restore-white"
                    >
                      恢复白色
                    </button>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary admin-btn-sm"
                      onClick={() => setSpawnAtSelected("A")}
                      disabled={singleSelectedIndex === null}
                      data-testid="map-group-spawn-a"
                    >
                      设为出生格 A
                    </button>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary admin-btn-sm"
                      onClick={() => setSpawnAtSelected("B")}
                      disabled={singleSelectedIndex === null}
                      data-testid="map-group-spawn-b"
                    >
                      设为出生格 B
                    </button>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary admin-btn-sm"
                      onClick={() => setSelectedLandmark(true)}
                      disabled={effectiveSelectedIndices.length === 0}
                      data-testid="map-group-mark-landmark"
                    >
                      标记地标
                    </button>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary admin-btn-sm"
                      onClick={() => setSelectedLandmark(false)}
                      disabled={effectiveSelectedIndices.length === 0}
                      data-testid="map-group-unmark-landmark"
                    >
                      取消地标
                    </button>
                  </>
                ) : null}
              </div>
              {imageError ? <InlineNotice tone="error">{imageError}</InlineNotice> : null}
              <div className="admin-map-selection-line">
                {effectiveSelectedIndices.length === 0 ? (
                  <span className="admin-hint">未选中格子。</span>
                ) : effectiveSelectedIndices.length === 1 && singleSelectedIndex !== null ? (
                  <>
                    <span className="admin-chip">选中格 {singleSelectedIndex}</span>
                    <span className="admin-hint">
                      {cellPosition(singleSelectedIndex, form.gridCols)}
                    </span>
                    <span className="admin-hint">
                      {activeCells[singleSelectedIndex] && activeColors[singleSelectedIndex]
                        ? "已上传图片并设置背景颜色"
                        : activeCells[singleSelectedIndex]
                          ? "已上传图片"
                          : activeColors[singleSelectedIndex]
                            ? `背景颜色 ${activeColors[singleSelectedIndex]}`
                            : "未上传图片（白色）"}
                    </span>
                  </>
                ) : (
                  <>
                    <span className="admin-chip">
                      已选 {effectiveSelectedIndices.length} 格
                    </span>
                    <span className="admin-hint">批量操作只作用于当前地图的选中格。</span>
                  </>
                )}
                <span className="admin-chip">出生格 A · {form.spawnA}</span>
                <span className="admin-hint">{cellPosition(form.spawnA, form.gridCols)}</span>
                <span className="admin-chip">出生格 B · {form.spawnB}</span>
                <span className="admin-hint">{cellPosition(form.spawnB, form.gridCols)}</span>
                <span className="admin-chip">
                  地标 {activeLandmarks.filter(Boolean).length} 格
                </span>
              </div>

              <div className="admin-map-stage">
                <div
                  className="admin-map-board"
                  style={{ width: `${boardWidth}px`, height: `${boardHeight}px` }}
                >
                  <BoardCanvas
                    width={boardWidth}
                    height={boardHeight}
                    rows={form.gridRows}
                    cols={form.gridCols}
                    visuals={boardVisuals}
                    drawPieces={false}
                    drawInteraction={false}
                    ariaLabel={`${MAP_SLOT_LABELS[form.activeSlot]} 地图预览与编辑`}
                    testId="map-group-board"
                  />
                  <div
                    className="admin-map-board-overlay"
                    style={{
                      gridTemplateColumns: `repeat(${form.gridCols}, minmax(0, 1fr))`,
                      gridTemplateRows: `repeat(${form.gridRows}, minmax(0, 1fr))`,
                    }}
                  >
                    {activeCells.map((_, index) => (
                      <button
                        type="button"
                        key={index}
                        className={`admin-map-cell${
                          effectiveSelectedSet.has(index) ? " selected" : ""
                        }`}
                        onClick={(event) => toggleCellSelection(index, event)}
                        aria-pressed={effectiveSelectedSet.has(index)}
                        aria-label={`第 ${Math.floor(index / form.gridCols) + 1} 行第 ${
                          (index % form.gridCols) + 1
                        } 列，编号 ${index}`}
                        data-testid={`map-group-cell-${index}`}
                      >
                        <span className="admin-map-cell-index">{index}</span>
                        {form.spawnA === index ? (
                          <span className="admin-map-cell-spawn spawn-a">A</span>
                        ) : null}
                        {form.spawnB === index ? (
                          <span className="admin-map-cell-spawn spawn-b">B</span>
                        ) : null}
                        {activeLandmarks[index] ? (
                          <span className="admin-map-cell-landmark">L</span>
                        ) : null}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="admin-map-badge-rail">
                  <Field
                    label="预览配置行"
                    htmlFor="map-group-preview-row"
                    hint="默认显示正式第 1 局。"
                  >
                    <select
                      id="map-group-preview-row"
                      className="admin-select"
                      value={previewRowIndex}
                      onChange={(event) => setPreviewRow(Number(event.target.value))}
                      disabled={previewRowIndex < 0}
                      data-testid="map-group-preview-row"
                    >
                      {selectedProfileRows.map((_, index) => (
                        <option key={index} value={index}>
                          {index === 0 ? "练习" : `正式 ${index}`}
                        </option>
                      ))}
                    </select>
                  </Field>
                  {previewRowValues ? (
                    <>
                      <TrialInfoBadge
                        initialSoldiersA={previewRowValues.soldiersA}
                        initialSoldiersB={previewRowValues.soldiersB}
                        reinforcementA={previewRowValues.soldiersA}
                        reinforcementB={previewRowValues.soldiersB}
                      />
                      <p className="admin-hint admin-map-badge-caption">
                        A +{previewRowValues.soldiersA} · B +{previewRowValues.soldiersB}
                      </p>
                    </>
                  ) : (
                    <p className="admin-hint">选择已发布的配置方案后显示对局信息浮层。</p>
                  )}
                </div>
              </div>
            </div>

            <div className="admin-form-section">
              <h3 className="admin-section-title">对局参数</h3>
              <div className="admin-condition-meta-grid">
                <Field label="练习回合上限" htmlFor="map-group-practice-cap">
                  <input
                    id="map-group-practice-cap"
                    className="admin-input"
                    type="number"
                    min="1"
                    step="1"
                    value={form.practiceTurnCap}
                    onChange={(event) => patchForm({ practiceTurnCap: event.target.value })}
                    disabled={readOnly}
                    data-testid="map-group-practice-turn-cap"
                  />
                </Field>
                <Field label="练习回合倒计时（秒）" htmlFor="map-group-practice-seconds">
                  <input
                    id="map-group-practice-seconds"
                    className="admin-input"
                    type="number"
                    min="1"
                    step="1"
                    value={form.practiceTurnSeconds}
                    onChange={(event) =>
                      patchForm({ practiceTurnSeconds: event.target.value })
                    }
                    disabled={readOnly}
                    data-testid="map-group-practice-turn-seconds"
                  />
                </Field>
                <Field label="正式回合上限" htmlFor="map-group-formal-cap">
                  <input
                    id="map-group-formal-cap"
                    className="admin-input"
                    type="number"
                    min="1"
                    step="1"
                    value={form.formalTurnCap}
                    onChange={(event) => patchForm({ formalTurnCap: event.target.value })}
                    disabled={readOnly}
                    data-testid="map-group-formal-turn-cap"
                  />
                </Field>
                <Field label="正式回合倒计时（秒）" htmlFor="map-group-formal-seconds">
                  <input
                    id="map-group-formal-seconds"
                    className="admin-input"
                    type="number"
                    min="1"
                    step="1"
                    value={form.formalTurnSeconds}
                    onChange={(event) =>
                      patchForm({ formalTurnSeconds: event.target.value })
                    }
                    disabled={readOnly}
                    data-testid="map-group-formal-turn-seconds"
                  />
                </Field>
                <Field label="局间休息（秒）" htmlFor="map-group-rest">
                  <input
                    id="map-group-rest"
                    className="admin-input"
                    type="number"
                    min="1"
                    step="1"
                    value={form.restSeconds}
                    onChange={(event) => patchForm({ restSeconds: event.target.value })}
                    disabled={readOnly}
                    data-testid="map-group-rest-seconds"
                  />
                </Field>
                <Field label="正式对局顺序">
                  <label className="admin-check-item">
                    <input
                      type="checkbox"
                      checked={form.randomizeFormal}
                      onChange={(event) =>
                        patchForm({ randomizeFormal: event.target.checked })
                      }
                      disabled={readOnly}
                      data-testid="map-group-randomize"
                    />
                    <span>随机化正式对局顺序</span>
                  </label>
                </Field>
              </div>
            </div>

            <div className="admin-form-section">
              <h3 className="admin-section-title">费用参数</h3>
              <p className="admin-hint">
                以元为单位输入，平台按分存储。默认参数下完成报酬为 45 到 65 元；
                绩效按士兵数量计算后截断到保底与上限之间。
              </p>
              <div className="admin-condition-meta-grid">
                <Field
                  label="基础被试费（元）"
                  htmlFor="map-group-base-pay"
                  hint="默认 10.00"
                >
                  <input
                    id="map-group-base-pay"
                    className="admin-input"
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={form.basePayYuan}
                    onChange={(event) => patchForm({ basePayYuan: event.target.value })}
                    disabled={readOnly}
                    data-testid="map-group-base-pay"
                  />
                </Field>
                <Field
                  label="绩效单价（元 / 士兵）"
                  htmlFor="map-group-performance-rate"
                  hint="默认 0.01，即每士兵 1 分"
                >
                  <input
                    id="map-group-performance-rate"
                    className="admin-input"
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={form.performanceRateYuan}
                    onChange={(event) =>
                      patchForm({ performanceRateYuan: event.target.value })
                    }
                    disabled={readOnly}
                    data-testid="map-group-performance-rate"
                  />
                </Field>
                <Field
                  label="绩效保底（元）"
                  htmlFor="map-group-performance-floor"
                  hint="默认 35.00"
                >
                  <input
                    id="map-group-performance-floor"
                    className="admin-input"
                    type="number"
                    min="0"
                    step="0.01"
                    value={form.performanceFloorYuan}
                    onChange={(event) =>
                      patchForm({ performanceFloorYuan: event.target.value })
                    }
                    disabled={readOnly}
                    data-testid="map-group-performance-floor"
                  />
                </Field>
                <Field
                  label="绩效上限（元）"
                  htmlFor="map-group-performance-cap"
                  hint="默认 55.00"
                >
                  <input
                    id="map-group-performance-cap"
                    className="admin-input"
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={form.performanceCapYuan}
                    onChange={(event) =>
                      patchForm({ performanceCapYuan: event.target.value })
                    }
                    disabled={readOnly}
                    data-testid="map-group-performance-cap"
                  />
                </Field>
                <Field
                  label="到场费（元）"
                  htmlFor="map-group-showup-pay"
                  hint="默认 10.00"
                >
                  <input
                    id="map-group-showup-pay"
                    className="admin-input"
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={form.showupPayYuan}
                    onChange={(event) => patchForm({ showupPayYuan: event.target.value })}
                    disabled={readOnly}
                    data-testid="map-group-showup-pay"
                  />
                </Field>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
