interface ByDay {
  date: string;
  count: number;
}

export function ViewsChart({ byDay }: { byDay: ByDay[] }) {
  if (!byDay || byDay.length === 0) {
    return (
      <div
        style={{
          padding: "24px 12px",
          textAlign: "center",
          color: "var(--text-dim)",
          fontSize: 12,
          border: "1px dashed var(--border)",
          borderRadius: 12,
        }}
      >
        아직 조회가 없습니다
      </div>
    );
  }

  const width = 480;
  const height = 140;
  const padX = 8;
  const padTop = 12;
  const padBottom = 22;
  const chartW = width - padX * 2;
  const chartH = height - padTop - padBottom;
  const n = byDay.length;
  const barW = Math.min(28, chartW / n);
  const step = chartW / n;
  const maxCount = Math.max(1, ...byDay.map((d) => d.count));
  const labelEvery = Math.ceil(n / 8);

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${width} ${height}`}
      style={{
        display: "block",
        background: "rgba(255,255,255,0.02)",
        border: "1px solid var(--border)",
        borderRadius: 12,
      }}
      role="img"
      aria-label="일별 조회수"
    >
      {byDay.map((d, i) => {
        const h = (d.count / maxCount) * chartH;
        const x = padX + i * step + (step - barW) / 2;
        const y = padTop + (chartH - h);
        const showLabel = i % labelEvery === 0 || i === n - 1;
        return (
          <g key={d.date}>
            <rect
              x={x}
              y={y}
              width={barW}
              height={h}
              rx={2}
              fill="var(--accent)"
              opacity={0.85}
            >
              <title>{`${d.date}: ${d.count}`}</title>
            </rect>
            {showLabel && (
              <text
                x={x + barW / 2}
                y={height - 6}
                textAnchor="middle"
                fontSize={9}
                fill="var(--text-dim)"
                fontFamily="var(--font-mono)"
              >
                {d.date.slice(5)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
