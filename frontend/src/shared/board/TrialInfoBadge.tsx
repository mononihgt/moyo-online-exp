const REFERENCE_WIDTH = 80;
const REFERENCE_HEIGHT = 104;
const SHAPE_RADIUS = 21;
const SHAPE_SPACING = 50;
const MIN_SCALE = 0.6;

export interface TrialInfoBadgeProps {
  initialSoldiersA: number;
  initialSoldiersB: number;
  reinforcementA: number;
  reinforcementB: number;
  scale?: number;
  className?: string;
}

export function TrialInfoBadge({
  initialSoldiersA,
  initialSoldiersB,
  reinforcementA,
  reinforcementB,
  scale = 1,
  className,
}: TrialInfoBadgeProps) {
  if (initialSoldiersA !== reinforcementA || initialSoldiersB !== reinforcementB) {
    throw new Error("初始兵力与每格收益不一致，无法渲染对局信息浮层");
  }
  const effectiveScale = Math.max(MIN_SCALE, scale);
  const circleY = SHAPE_RADIUS + 5;
  const diamondY = circleY + SHAPE_SPACING;
  const centerX = REFERENCE_WIDTH / 2;
  const diamondRadius = SHAPE_RADIUS;
  const label = `本局初始兵力与每格收益：玩家 A +${initialSoldiersA}，玩家 B +${initialSoldiersB}`;

  return (
    <div
      className={className}
      role="img"
      aria-label={label}
      style={{
        width: `${REFERENCE_WIDTH * effectiveScale}px`,
        height: `${REFERENCE_HEIGHT * effectiveScale}px`,
        pointerEvents: "none",
      }}
      data-testid="trial-info-badge"
    >
      <svg
        viewBox={`0 0 ${REFERENCE_WIDTH} ${REFERENCE_HEIGHT}`}
        width={REFERENCE_WIDTH * effectiveScale}
        height={REFERENCE_HEIGHT * effectiveScale}
        aria-hidden="true"
        focusable="false"
      >
        <circle
          cx={centerX}
          cy={circleY}
          r={SHAPE_RADIUS}
          fill="none"
          stroke="#000000"
          strokeWidth={1}
        />
        <polygon
          points={`${centerX},${diamondY - diamondRadius} ${centerX + diamondRadius},${diamondY} ${centerX},${diamondY + diamondRadius} ${centerX - diamondRadius},${diamondY}`}
          fill="none"
          stroke="#000000"
          strokeWidth={1}
        />
        <text
          x={centerX - 15}
          y={circleY + 7}
          fill="#000000"
          fontFamily='"Times New Roman", Times, serif'
          fontSize={20}
        >
          +{initialSoldiersA}
        </text>
        <text
          x={centerX - 15}
          y={diamondY + 7}
          fill="#000000"
          fontFamily='"Times New Roman", Times, serif'
          fontSize={20}
        >
          +{initialSoldiersB}
        </text>
      </svg>
    </div>
  );
}
