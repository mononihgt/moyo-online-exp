import { useLayoutEffect, useMemo, useRef, useSyncExternalStore } from "react";
import type { CSSProperties } from "react";

import type { BoardState, ConditionVisual } from "../types";
import {
  boardImagesReady,
  drawBoard,
  getBoardImageVersion,
  subscribeBoardImages,
} from "./renderBoard";

export interface BoardCanvasProps {
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
  className?: string;
  style?: CSSProperties;
  ariaLabel?: string;
  testId?: string;
}

export function BoardCanvas({
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
  className,
  style,
  ariaLabel,
  testId,
}: BoardCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const version = useSyncExternalStore(
    subscribeBoardImages,
    getBoardImageVersion,
    () => 0,
  );
  const imagesReady = useMemo(() => boardImagesReady(visuals), [visuals, version]);

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null || width <= 0 || height <= 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const context = canvas.getContext("2d");
    if (context === null) return;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawBoard(context, {
      width,
      height,
      rows,
      cols,
      visuals,
      board,
      selected,
      hovered,
      disabled,
      drawPieces,
      drawInteraction,
    });
  }, [
    board,
    cols,
    disabled,
    drawInteraction,
    drawPieces,
    height,
    hovered,
    selected,
    version,
    visuals,
    width,
  ]);

  return (
    <canvas
      ref={canvasRef}
      className={className}
      style={{ width: `${width}px`, height: `${height}px`, ...style }}
      role="img"
      aria-label={ariaLabel}
      data-testid={testId}
      data-images-ready={imagesReady ? "true" : "false"}
    />
  );
}
