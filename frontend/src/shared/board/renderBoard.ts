import type { BoardState, ConditionVisual } from "../types";

export interface BoardImageEntry {
  image: HTMLImageElement;
  loaded: boolean;
  failed: boolean;
  dark: boolean;
}

export const BOARD_GRID_COLOR = "#B8B8B8";
export const BOARD_SELECTION_COLOR = "#505050";
export const BOARD_HOVER_COLOR = "#AEAEB2";
export const BOARD_PIECE_INK_LIGHT = "#1C1C1E";
export const BOARD_PIECE_INK_DARK = "#ffffff";

const NUMBER_FONT =
  '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif';

const imageCache = new Map<string, BoardImageEntry>();
const listeners = new Set<() => void>();
let imageVersion = 0;

export function subscribeBoardImages(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getBoardImageVersion(): number {
  return imageVersion;
}

function notifyBoardImages(): void {
  imageVersion += 1;
  for (const listener of listeners) listener();
}

function hexBrightness(color: string): number | null {
  const match = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(color.trim());
  if (match === null) return null;
  let hex = match[1];
  if (hex.length === 3) {
    hex = hex
      .split("")
      .map((part) => part + part)
      .join("");
  }
  const r = Number.parseInt(hex.slice(0, 2), 16);
  const g = Number.parseInt(hex.slice(2, 4), 16);
  const b = Number.parseInt(hex.slice(4, 6), 16);
  return (r * 299 + g * 587 + b * 114) / 1000;
}

function imageIsDark(image: HTMLImageElement): boolean {
  try {
    const probe = document.createElement("canvas");
    probe.width = 16;
    probe.height = 16;
    const context = probe.getContext("2d");
    if (context === null) return true;
    context.drawImage(image, 0, 0, 16, 16);
    const data = context.getImageData(0, 0, 16, 16).data;
    let total = 0;
    for (let index = 0; index < data.length; index += 4) {
      total += data[index] * 0.299 + data[index + 1] * 0.587 + data[index + 2] * 0.114;
    }
    return total / (data.length / 4) < 140;
  } catch {
    return true;
  }
}

export function getBoardImage(assetId: string): BoardImageEntry {
  const cached = imageCache.get(assetId);
  if (cached !== undefined) return cached;
  const image = new Image();
  const entry: BoardImageEntry = { image, loaded: false, failed: false, dark: true };
  imageCache.set(assetId, entry);
  image.onload = () => {
    entry.loaded = true;
    entry.dark = imageIsDark(image);
    notifyBoardImages();
  };
  image.onerror = () => {
    entry.failed = true;
    notifyBoardImages();
  };
  image.src = `/media/${assetId}`;
  return entry;
}

export function boardImagesReady(visuals: ConditionVisual[]): boolean {
  for (const visual of visuals) {
    if (visual.backgroundAssetId === null) continue;
    const entry = getBoardImage(visual.backgroundAssetId);
    if (!entry.loaded && !entry.failed) return false;
  }
  return true;
}

export interface DrawBoardOptions {
  width: number;
  height: number;
  rows: number;
  cols: number;
  visuals: ConditionVisual[];
  board?: BoardState | null;
  selected?: number[];
  hovered?: number | null;
  disabled?: boolean;
  drawPieces?: boolean;
  drawInteraction?: boolean;
}

export function drawBoard(context: CanvasRenderingContext2D, options: DrawBoardOptions): void {
  const {
    width,
    height,
    rows,
    cols,
    visuals,
    board = null,
    selected = [],
    hovered = null,
    disabled = false,
    drawPieces = true,
    drawInteraction = true,
  } = options;
  if (width <= 0 || height <= 0) return;

  const cellWidth = width / cols;
  const cellHeight = height / rows;
  const selectedSet = new Set(selected);

  context.clearRect(0, 0, width, height);

  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const index = row * cols + col;
      const visual = visuals[index] ?? { color: null, backgroundAssetId: null };
      const x = col * cellWidth;
      const y = row * cellHeight;
      let dark = false;

      context.fillStyle = "#ffffff";
      context.fillRect(x, y, cellWidth, cellHeight);

      if (visual.backgroundAssetId) {
        const entry = getBoardImage(visual.backgroundAssetId);
        if (entry.loaded && !entry.failed) {
          const image = entry.image;
          const naturalWidth = image.naturalWidth || image.width;
          const naturalHeight = image.naturalHeight || image.height;
          const scale = Math.max(cellWidth / naturalWidth, cellHeight / naturalHeight);
          const drawWidth = naturalWidth * scale;
          const drawHeight = naturalHeight * scale;
          context.save();
          context.beginPath();
          context.rect(x, y, cellWidth, cellHeight);
          context.clip();
          context.drawImage(
            image,
            x + (cellWidth - drawWidth) / 2,
            y + (cellHeight - drawHeight) / 2,
            drawWidth,
            drawHeight,
          );
          context.restore();
          dark = entry.dark;
        } else if (visual.color) {
          context.fillStyle = visual.color;
          context.fillRect(x, y, cellWidth, cellHeight);
          const brightness = hexBrightness(visual.color);
          dark = brightness === null ? true : brightness < 140;
        }
      } else if (visual.color) {
        context.fillStyle = visual.color;
        context.fillRect(x, y, cellWidth, cellHeight);
        const brightness = hexBrightness(visual.color);
        dark = brightness === null ? true : brightness < 140;
      }

      if (!drawPieces || board === null) continue;
      const owner = board.owners[index] ?? 0;
      const soldiers = board.soldiers[index] ?? 0;
      if (owner === 0) continue;

      const ink = dark ? BOARD_PIECE_INK_DARK : BOARD_PIECE_INK_LIGHT;
      const centerX = x + cellWidth / 2;
      const centerY = y + cellHeight / 2;
      const radius = Math.min(cellWidth, cellHeight) * 0.31;

      context.beginPath();
      if (owner === 1) {
        context.arc(centerX, centerY, radius, 0, Math.PI * 2);
      } else {
        context.moveTo(centerX, centerY - radius);
        context.lineTo(centerX + radius, centerY);
        context.lineTo(centerX, centerY + radius);
        context.lineTo(centerX - radius, centerY);
        context.closePath();
      }
      context.lineWidth = 1.5;
      context.strokeStyle = ink;
      context.lineJoin = "round";
      context.stroke();

      const fontSize = Math.max(10, Math.min(cellWidth, cellHeight) * 0.19);
      context.fillStyle = ink;
      context.font = `600 ${fontSize}px ${NUMBER_FONT}`;
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillText(String(soldiers), centerX, centerY);
    }
  }

  context.lineWidth = 1;
  context.strokeStyle = BOARD_GRID_COLOR;
  context.beginPath();
  for (let col = 0; col <= cols; col += 1) {
    const lineX = col === cols ? width - 0.5 : Math.round((width * col) / cols) + 0.5;
    context.moveTo(lineX, 0);
    context.lineTo(lineX, height);
  }
  for (let row = 0; row <= rows; row += 1) {
    const lineY = row === rows ? height - 0.5 : Math.round((height * row) / rows) + 0.5;
    context.moveTo(0, lineY);
    context.lineTo(width, lineY);
  }
  context.stroke();

  if (!drawInteraction) return;
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const index = row * cols + col;
      const x = col * cellWidth;
      const y = row * cellHeight;
      if (selectedSet.has(index)) {
        context.lineWidth = 2;
        context.strokeStyle = BOARD_SELECTION_COLOR;
        context.strokeRect(x + 1, y + 1, cellWidth - 2, cellHeight - 2);
      } else if (!disabled && hovered === index) {
        context.lineWidth = 1;
        context.strokeStyle = BOARD_HOVER_COLOR;
        context.strokeRect(x + 0.5, y + 0.5, cellWidth - 1, cellHeight - 1);
      }
    }
  }
}

export function cellIndexFromPoint(
  clientX: number,
  clientY: number,
  rect: DOMRect,
  rows: number,
  cols: number,
): number | null {
  const x = clientX - rect.left;
  const y = clientY - rect.top;
  if (x < 0 || y < 0 || x >= rect.width || y >= rect.height) return null;
  const col = Math.min(cols - 1, Math.floor((x / rect.width) * cols));
  const row = Math.min(rows - 1, Math.floor((y / rect.height) * rows));
  return row * cols + col;
}
