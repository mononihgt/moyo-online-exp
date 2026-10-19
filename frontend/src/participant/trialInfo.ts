import type { GameBoardLayout } from "./GameBoard";

export const TRIAL_INFO_REFERENCE_WIDTH = 80;
export const TRIAL_INFO_REFERENCE_HEIGHT = 104;
export const TRIAL_INFO_MIN_SCALE = 0.6;
export const TRIAL_INFO_OVERLAY_INSET = 8;
// 浮层移入顶部栏后，只有横向空出足够距离才回到棋盘旁，避免顶部栏高度变化导致来回切换
const TRIAL_INFO_HUD_CLEARANCE = 64;

// 参考实现的游戏区域宽度为 600，浮层在该尺度下宽 80 高 104
const REFERENCE_BOARD_EDGE = 600;

export interface TrialInfoPlacement {
  scale: number;
  width: number;
  height: number;
  inHud: boolean;
}

export function trialInfoPlacement(
  layout: GameBoardLayout,
  currentlyInHud = false,
): TrialInfoPlacement {
  const boardEdge = Math.min(layout.boardWidth, layout.boardHeight);
  const scale = Math.max(TRIAL_INFO_MIN_SCALE, boardEdge / REFERENCE_BOARD_EDGE);
  const width = TRIAL_INFO_REFERENCE_WIDTH * scale;
  const height = TRIAL_INFO_REFERENCE_HEIGHT * scale;

  const boardLeft = (layout.areaWidth - layout.boardWidth) / 2;
  const boardTop = (layout.areaHeight - layout.boardHeight) / 2;
  const badgeLeft = layout.areaWidth - TRIAL_INFO_OVERLAY_INSET - width;
  const badgeTop = TRIAL_INFO_OVERLAY_INSET;
  const clearance = currentlyInHud ? TRIAL_INFO_HUD_CLEARANCE : 0;
  const horizontallyClear =
    badgeLeft >= boardLeft + layout.boardWidth + clearance;
  const verticallyClear =
    badgeTop >= boardTop + layout.boardHeight || badgeTop + height <= boardTop;
  const inHud = !(horizontallyClear || verticallyClear);

  return { scale, width, height, inHud };
}
