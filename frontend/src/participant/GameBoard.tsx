import {
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";

import { BoardCanvas } from "../shared/board/BoardCanvas";
import { cellIndexFromPoint } from "../shared/board/renderBoard";
import type { BoardState, ConditionVisual } from "../shared/types";

export interface GameBoardLayout {
  boardWidth: number;
  boardHeight: number;
  areaWidth: number;
  areaHeight: number;
}

export function GameBoard({
  board,
  visuals,
  selected,
  warCells,
  flashKey,
  disabled = false,
  topRightOverlay = null,
  onToggle,
  onClear,
  onLayout,
}: {
  board: BoardState;
  visuals: ConditionVisual[];
  selected: number[];
  warCells: number[];
  flashKey: string | number;
  disabled?: boolean;
  topRightOverlay?: ReactNode;
  onToggle: (cellIndex: number) => void;
  onClear: () => void;
  onLayout?: (layout: GameBoardLayout) => void;
}) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const onLayoutRef = useRef(onLayout);
  const lastLayoutRef = useRef<GameBoardLayout | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [hovered, setHovered] = useState<number | null>(null);

  const { rows, cols } = board;

  useEffect(() => {
    onLayoutRef.current = onLayout;
  }, [onLayout]);

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
      const previous = lastLayoutRef.current;
      if (
        previous === null ||
        previous.boardWidth !== width ||
        previous.boardHeight !== height ||
        previous.areaWidth !== rect.width ||
        previous.areaHeight !== rect.height
      ) {
        const layout = {
          boardWidth: width,
          boardHeight: height,
          areaWidth: rect.width,
          areaHeight: rect.height,
        };
        lastLayoutRef.current = layout;
        onLayoutRef.current?.(layout);
      }
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

  useEffect(() => {
    if (disabled) setHovered(null);
  }, [disabled]);

  useEffect(() => {
    setHovered(null);
  }, [size.height, size.width]);

  const cellFromEvent = (event: MouseEvent<HTMLDivElement>): number | null => {
    if (size.width <= 0 || size.height <= 0) return null;
    return cellIndexFromPoint(
      event.clientX,
      event.clientY,
      event.currentTarget.getBoundingClientRect(),
      rows,
      cols,
    );
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
        onMouseMove={(event) => {
          if (disabled) return;
          const index = cellFromEvent(event);
          setHovered((current) => (current === index ? current : index));
        }}
        onMouseLeave={() => setHovered(null)}
        onContextMenu={(event) => {
          event.preventDefault();
          if (!disabled) onClear();
        }}
        onDragStart={(event) => event.preventDefault()}
        data-testid="game-canvas-wrap"
      >
        <BoardCanvas
          width={size.width}
          height={size.height}
          rows={rows}
          cols={cols}
          visuals={visuals}
          board={board}
          selected={selected}
          hovered={hovered}
          disabled={disabled}
          drawPieces
          drawInteraction
          className={disabled ? "exp-canvas exp-canvas-disabled" : "exp-canvas"}
          testId="game-canvas"
          ariaLabel={`棋盘，共 ${rows} 行 ${cols} 列，已选择 ${selected.length} 个格子。左键切换选择，右键清除选择，空格键提交。`}
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
      {topRightOverlay !== null ? (
        <div className="exp-board-top-right">{topRightOverlay}</div>
      ) : null}
    </div>
  );
}
