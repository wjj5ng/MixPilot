<script lang="ts">
  /**
   * 다채널 RMS·Peak dBFS 시계열 오버레이 — Canvas 기반.
   *
   * 각 시리즈는 색이 다른 RMS 실선 + Peak 점선. 채널 비교 시 같은 시간축 위에
   * 라이브 변동 패턴을 한눈에 확인. 데이터는 App의 ring buffer에서 누적.
   */

  type Point = { t: number; rms: number; peak: number };
  type Series = {
    channel: number;
    label: string;
    points: Point[];
    color: string;
  };

  let {
    series = [],
    windowSeconds = 60,
  }: {
    series: Series[];
    windowSeconds?: number;
  } = $props();

  const DB_FLOOR = -60;
  const DB_CEILING = 0;

  let canvas = $state<HTMLCanvasElement | null>(null);
  let canvasWidth = $state(640);
  const canvasHeight = 180;

  $effect(() => {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvasWidth * dpr;
    canvas.height = canvasHeight * dpr;
    canvas.style.width = `${canvasWidth}px`;
    canvas.style.height = `${canvasHeight}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw(ctx, canvasWidth, canvasHeight);
  });

  function draw(ctx: CanvasRenderingContext2D, w: number, h: number): void {
    ctx.clearRect(0, 0, w, h);

    ctx.fillStyle = "#1a1d24";
    ctx.fillRect(0, 0, w, h);

    // Y 격자.
    ctx.strokeStyle = "#262a33";
    ctx.lineWidth = 1;
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillStyle = "#5a6270";
    for (const db of [-60, -40, -20, 0]) {
      const y = dbToY(db, h);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
      ctx.fillText(`${db}`, 4, y - 2);
    }
    ctx.setLineDash([2, 3]);
    for (const db of [-6, -12]) {
      const y = dbToY(db, h);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    // 시리즈 없거나 비어있으면 placeholder.
    const hasData = series.some((s) => s.points.length >= 2);
    if (!hasData) {
      ctx.fillStyle = "#5a6270";
      ctx.font = "11px sans-serif";
      ctx.fillText("데이터 누적 중…", w / 2 - 30, h / 2);
      return;
    }

    // 시간 범위 — 모든 시리즈에서 가장 최근 t.
    let now = 0;
    for (const s of series) {
      if (s.points.length === 0) continue;
      const last = s.points[s.points.length - 1].t;
      if (last > now) now = last;
    }
    if (now === 0) return;
    const tStart = now - windowSeconds * 1000;

    // X tick.
    ctx.fillStyle = "#5a6270";
    for (let sec = 0; sec <= windowSeconds; sec += 10) {
      const t = now - (windowSeconds - sec) * 1000;
      const x = tToX(t, tStart, now, w);
      ctx.beginPath();
      ctx.moveTo(x, h - 12);
      ctx.lineTo(x, h - 8);
      ctx.strokeStyle = "#262a33";
      ctx.stroke();
      const left = windowSeconds - sec;
      if (left === 0) ctx.fillText("now", x - 8, h - 1);
      else ctx.fillText(`-${left}s`, x - 8, h - 1);
    }

    // 각 시리즈: Peak(점선) 먼저 → RMS(실선) 위에.
    for (const s of series) {
      if (s.points.length < 2) continue;
      ctx.strokeStyle = s.color;
      ctx.globalAlpha = 0.55;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 2]);
      ctx.beginPath();
      let started = false;
      for (const p of s.points) {
        if (p.t < tStart) continue;
        const x = tToX(p.t, tStart, now, w);
        const y = dbToY(p.peak, h);
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      }
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1.0;
    }
    for (const s of series) {
      if (s.points.length < 2) continue;
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      let started = false;
      for (const p of s.points) {
        if (p.t < tStart) continue;
        const x = tToX(p.t, tStart, now, w);
        const y = dbToY(p.rms, h);
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      }
      ctx.stroke();
    }
  }

  function dbToY(db: number, h: number): number {
    const norm = Math.max(
      0,
      Math.min(1, (db - DB_FLOOR) / (DB_CEILING - DB_FLOOR)),
    );
    return h - 15 - norm * (h - 25);
  }

  function tToX(t: number, tStart: number, tEnd: number, w: number): number {
    const norm = (t - tStart) / (tEnd - tStart);
    return Math.max(0, Math.min(1, norm)) * (w - 30) + 25;
  }
</script>

<div class="timeseries" bind:clientWidth={canvasWidth}>
  <div class="header">
    {#if series.length === 0}
      <span class="title hint">선택된 채널 없음</span>
    {:else}
      <span class="legend">
        {#each series as s (s.channel)}
          <span class="legend-item" style="color: {s.color}">
            ━ ch{String(s.channel).padStart(2, "0")} {s.label || ""}
          </span>
        {/each}
      </span>
      <span class="legend-note">실선=RMS · 점선=Peak</span>
    {/if}
  </div>
  <canvas bind:this={canvas}></canvas>
</div>

<style>
  .timeseries {
    width: 100%;
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 0.3rem;
    font-size: 0.85rem;
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  .title {
    color: #c8cdd6;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.7rem;
    font-size: 0.78rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .legend-item {
    white-space: nowrap;
  }
  .legend-note {
    color: #5a6270;
    font-size: 0.72rem;
  }
  .hint {
    color: #5a6270;
  }
  canvas {
    display: block;
    border: 1px solid #262a33;
    border-radius: 0.2rem;
  }
</style>
