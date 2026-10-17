import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";

import type { BoardState, ConditionVisual } from "../shared/types";

interface CachedImage {
  image: HTMLImageElement;
  loaded: boolean;
  failed: boolean;
  dark: boolean;
}

const imageCache = new Map<string, CachedImage>();

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

export function GameBoard({
  board,
  visuals,
  selected,
  warCells,
  flashKey,
  disabled = false,
  onToggle,
  onClear,
}: {
  board: BoardState;
  visuals: ConditionVisual[];
  selected: number[];
  warCells: number[];
  flashKey: string | number;
  disabled?: boolean;
  onToggle: (cellIndex: number) => void;
  onClear: () => void;
}) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [imageVersion, setImageVersion] = useState(0);

  const { rows, cols } = board;

  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (wrapper === null) return;
    const measure = () => {
      const rect = wrapper.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;
      const cell = Math.min(rect.width / cols, rect.height / rows);
      const width = Math.max(1, Math.floor(cell * cols));
      const height = Math.max(1, Math.floor(cell * rows));
      setSize((current) =>
        current.width === width && current.height === height ? current : { width, height },
      );
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(wrapper);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [cols, rows]);

  const loadImage = useCallback((assetId: string) => {
    const cached = imageCache.get(assetId);
    if (cached !== undefined) return cached;
    const image = new Image();
    const entry: CachedImage = { image, loaded: false, failed: false, dark: true };
    imageCache.set(assetId, entry);
    image.onload = () => {
      entry.loaded = true;
      entry.dark = imageIsDark(image);
      setImageVersion((version) => version + 1);
    };
    image.onerror = () => {
      entry.failed = true;
      setImageVersion((version) => version + 1);
    };
    image.src = `/media/${assetId}`;
    return entry;
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null || size.width <= 0 || size.height <= 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(size.width * dpr);
    canvas.height = Math.round(size.height * dpr);
    const context = canvas.getContext("2d");
    if (context === null) return;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, size.width, size.height);
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, size.width, size.height);

    const cellWidth = size.width / cols;
    const cellHeight = size.height / rows;
    const selectedSet = new Set(selected);
    const warSet = new Set(warCells);

    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < cols; col += 1) {
        const index = row * cols + col;
        const visual = visuals[index] ?? { color: null, backgroundAssetId: null };
        const x = col * cellWidth;
        const y = row * cellHeight;
        let dark = false;

        if (visual.backgroundAssetId) {
          const entry = loadImage(visual.backgroundAssetId);
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

        const owner = board.owners[index] ?? 0;
        const soldiers = board.soldiers[index] ?? 0;
        const ink = dark ? "#ffffff" : "#1C1C1E";
        const stroke = dark ? "rgba(255,255,255,0.7)" : "rgba(28,28,30,0.55)";
        const centerX = x + cellWidth / 2;
        const centerY = y + cellHeight * 0.36;
        const markerSize = Math.min(cellWidth, cellHeight) * 0.17;

        if (owner === 1) {
          context.beginPath();
          context.arc(centerX, centerY, markerSize, 0, Math.PI * 2);
          context.fillStyle = ink;
          context.fill();
          context.lineWidth = 1;
          context.strokeStyle = stroke;
          context.stroke();
        } else if (owner === 2) {
          context.beginPath();
          context.moveTo(centerX, centerY - markerSize);
          context.lineTo(centerX + markerSize, centerY);
          context.lineTo(centerX, centerY + markerSize);
          context.lineTo(centerX - markerSize, centerY);
          context.closePath();
          context.fillStyle = ink;
          context.fill();
          context.lineWidth = 1;
          context.strokeStyle = stroke;
          context.stroke();
        }

        if (owner !== 0) {
          const fontSize = Math.max(11, Math.min(cellWidth, cellHeight) * 0.26);
          context.fillStyle = ink;
          context.font = `600 ${fontSize}px ui-monospace, SFMono-Regular, Menlo, monospace`;
          context.textAlign = "center";
          context.textBaseline = "middle";
          context.fillText(String(soldiers), centerX, y + cellHeight * 0.73);
        }

        if (warSet.has(index)) {
          context.lineWidth = 2;
          context.strokeStyle = "#FF9F0A";
          context.strokeRect(x + 1, y + 1, cellWidth - 2, cellHeight - 2);
        }
        if (selectedSet.has(index)) {
          context.fillStyle = "rgba(52, 199, 89, 0.16)";
          context.fillRect(x, y, cellWidth, cellHeight);
          context.lineWidth = 2;
          context.strokeStyle = "#34C759";
          context.strokeRect(x + 1, y + 1, cellWidth - 2, cellHeight - 2);
        }

        context.lineWidth = 1;
        context.strokeStyle = "#E5E5EA";
        context.strokeRect(x + 0.5, y + 0.5, cellWidth - 1, cellHeight - 1);
      }
    }
  }, [board, cols, loadImage, rows, selected, size.height, size.width, visuals, warCells, imageVersion]);

  const cellFromEvent = (event: MouseEvent<HTMLDivElement>): number | null => {
    if (size.width <= 0 || size.height <= 0) return null;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    if (x < 0 || y < 0 || x >= rect.width || y >= rect.height) return null;
    const col = Math.min(cols - 1, Math.floor((x / rect.width) * cols));
    const row = Math.min(rows - 1, Math.floor((y / rect.height) * rows));
    return row * cols + col;
  };

  return (
    <div className="exp-board-wrap" ref={wrapperRef}>
      <div
        className="exp-board-stage"
        style={{ width: `${size.width}px`, height: `${size.height}px` }}
        onClick={(event) => {
          if (disabled) return;
          const index = cellFromEvent(event);
          if (index !== null) onToggle(index);
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          if (!disabled) onClear();
        }}
        onDragStart={(event) => event.preventDefault()}
        data-testid="game-canvas-wrap"
      >
        <canvas
          ref={canvasRef}
          className={disabled ? "exp-canvas exp-canvas-disabled" : "exp-canvas"}
          data-testid="game-canvas"
          role="img"
          aria-label={`棋盘，共 ${rows} 行 ${cols} 列，已选择 ${selected.length} 个格子。左键切换选择，右键清除选择，空格键提交。`}
        />
        {warCells.length > 0 ? (
          <div
            key={flashKey}
            className="exp-war-overlay"
            aria-hidden="true"
            style={{
              gridTemplateColumns: `repeat(${cols}, 1fr)`,
              gridTemplateRows: `repeat(${rows}, 1fr)`,
            }}
          >
            {warCells.map((index) => {
              if (index < 0 || index >= rows * cols) return null;
              return (
                <span
                  key={index}
                  className="exp-war-cell"
                  style={{
                    gridColumn: `${(index % cols) + 1}`,
                    gridRow: `${Math.floor(index / cols) + 1}`,
                  }}
                />
              );
            })}
          </div>
        ) : null}
      </div>
    </div>
  );
}
