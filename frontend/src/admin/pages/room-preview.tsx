import { useEffect, useMemo, useState } from "react";
import type { MapGroupVersion, MapSlot } from "../../shared/types";
import { BoardCanvas } from "../../shared/board/BoardCanvas";
import { LoadingBlock } from "../ui";
import "../admin-rooms.css";

const MAX_BOARD_WIDTH = 420;

function previewCellSize(rows: number, cols: number): number {
  const cells = Math.max(1, Math.max(rows, cols));
  return Math.max(30, Math.min(56, Math.floor(MAX_BOARD_WIDTH / cells)));
}

function markerPosition(index: number, rows: number, cols: number): { left: string; top: string } {
  const safeCols = Math.max(1, cols);
  const safeRows = Math.max(1, rows);
  const row = Math.floor(index / safeCols);
  const col = index % safeCols;
  return {
    left: `${((col + 0.5) / safeCols) * 100}%`,
    top: `${((row + 0.5) / safeRows) * 100}%`,
  };
}

export function RoomMapPreview({
  mapGroup,
  loading = false,
  error = null,
}: {
  mapGroup: MapGroupVersion | null;
  loading?: boolean;
  error?: string | null;
}) {
  const [slot, setSlot] = useState<MapSlot>(mapGroup?.mode === "both" ? "Both" : "A");

  useEffect(() => {
    setSlot(mapGroup?.mode === "both" ? "Both" : "A");
  }, [mapGroup?.versionId]);

  const effectiveSlot: MapSlot =
    mapGroup?.mode === "both" ? "Both" : slot === "Both" ? "A" : slot;
  const map = useMemo(
    () => mapGroup?.maps.find((item) => item.slot === effectiveSlot) ?? null,
    [mapGroup, effectiveSlot],
  );
  const visuals = useMemo(
    () =>
      map
        ? map.cells.map((assetId) => ({ color: null, backgroundAssetId: assetId }))
        : [],
    [map],
  );

  if (loading) {
    return <LoadingBlock rows={4} label="正在加载地图预览" />;
  }

  if (!mapGroup) {
    return (
      <p className="admin-hint">
        {error ? `地图预览加载失败：${error}` : "暂无可用的地图组数据。"}
      </p>
    );
  }

  if (map === null) {
    return <p className="admin-hint">该地图组不包含所选槽位的地图。</p>;
  }

  const cellSize = previewCellSize(mapGroup.rows, mapGroup.cols);
  const width = cellSize * mapGroup.cols;
  const height = cellSize * mapGroup.rows;

  return (
    <div className="room-map-preview" data-testid="room-map-preview">
      <div className="room-map-preview__toolbar">
        <div className="admin-btn-row" role="tablist" aria-label="地图槽位">
          {mapGroup.mode === "both" ? (
            <button
              type="button"
              className={`admin-btn admin-btn-sm ${slot === "Both" ? "admin-btn-primary" : "admin-btn-secondary"}`}
              aria-selected={slot === "Both"}
              role="tab"
              onClick={() => setSlot("Both")}
              data-testid="room-map-preview-slot-both"
            >
              Both 地图
            </button>
          ) : (
            (["A", "B"] as MapSlot[]).map((entry) => (
              <button
                key={entry}
                type="button"
                className={`admin-btn admin-btn-sm ${slot === entry ? "admin-btn-primary" : "admin-btn-secondary"}`}
                aria-selected={slot === entry}
                role="tab"
                onClick={() => setSlot(entry)}
                data-testid={`room-map-preview-slot-${entry.toLowerCase()}`}
              >
                {entry} 地图
              </button>
            ))
          )}
        </div>
        <span className="admin-hint">
          {mapGroup.rows} × {mapGroup.cols} · {mapGroup.mode === "both" ? "Both 模式" : "A/B 模式"}
        </span>
      </div>

      <div className="room-map-preview__board-wrap">
        <div className="room-map-preview__board" style={{ width: `${width}px`, height: `${height}px` }}>
          <BoardCanvas
            width={width}
            height={height}
            rows={mapGroup.rows}
            cols={mapGroup.cols}
            visuals={visuals}
            drawPieces={false}
            drawInteraction={false}
            ariaLabel={`地图预览：${map.name}`}
            testId="room-map-preview-canvas"
          />
          <div className="room-map-preview__markers" aria-hidden="true">
            {(["A", "B"] as const).map((player) => {
              const index = mapGroup.spawns[player];
              if (index < 0 || index >= mapGroup.rows * mapGroup.cols) return null;
              const position = markerPosition(index, mapGroup.rows, mapGroup.cols);
              return (
                <div
                  key={player}
                  className={`room-map-preview__marker room-map-preview__marker-${player.toLowerCase()}`}
                  style={position}
                  data-testid={`room-map-preview-spawn-${player.toLowerCase()}`}
                >
                  <span className="room-map-preview__marker-shape">
                    <span className="room-map-preview__marker-label">{player}</span>
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="room-map-preview__meta">
        <div>
          <strong>{map.name}</strong>
          <span className="admin-hint"> · {map.sizeToken}</span>
        </div>
        <div className="admin-hint">{map.description}</div>
        <div className="admin-hint">因素水平：{map.factorLevel}</div>
        <div className="admin-hint">A/B 标记为出生格。预览仅显示地图背景与网格。</div>
      </div>
    </div>
  );
}
