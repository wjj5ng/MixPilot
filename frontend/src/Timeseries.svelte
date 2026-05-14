<script lang="ts">
  /**
   * 단일 채널의 RMS·Peak dBFS 시계열 그래프 — Canvas 기반.
   *
   * 데이터는 ring buffer로 App에서 누적. 본 컴포넌트는 *순수 시각화* — 새 props
   * 들어올 때마다 canvas redraw.
   */

  type Point = { t: number; rms: number; peak: number };

  let {
    points = [],
    label = "",
    channel = 0,
    windowSeconds = 60,
  }: {
    points: Point[];
    label?: string;
    channel?: number;
    windowSeconds?: number;
  } = $props();

  // dBFS 스케일.
  const DB_FLOOR = -60;
  const DB_CEILING = 0;

  let canvas = $state<HTMLCanvasElement | null>(null);

  // canvas resize 대응 — 부모 폭에 맞춰 그림.
  let canvasWidth = $state(640);
  const canvasHeight = 160;

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

    // 배경.
    ctx.fillStyle = "#1a1d24";
    ctx.fillRect(0, 0, w, h);

    // 격자 — Y(dB) -60, -40, -20, 0 라인.
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
    // -6, -12 라인 — 임계 시각화 (점선).
    ctx.setLineDash([2, 3]);
    for (const db of [-6, -12]) {
      const y = dbToY(db, h);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    if (points.length < 2) {
      ctx.fillStyle = "#5a6270";
      ctx.font = "11px sans-serif";
      ctx.fillText("데이터 누적 중…", w / 2 - 30, h / 2);
      return;
    }

    const now = points[points.length - 1].t;
    const tStart = now - windowSeconds * 1000;

    // X축 — 시간 ticks (10초마다).
    ctx.fillStyle = "#5a6270";
    for (let s = 0; s <= windowSeconds; s += 10) {
      const t = now - (windowSeconds - s) * 1000;
      const x = tToX(t, tStart, now, w);
      ctx.beginPath();
      ctx.moveTo(x, h - 12);
      ctx.lineTo(x, h - 8);
      ctx.strokeStyle = "#262a33";
      ctx.stroke();
      const sec = windowSeconds - s;
      if (sec === 0) {
        ctx.fillText("now", x - 8, h - 1);
      } else {
        ctx.fillText(`-${sec}s`, x - 8, h - 1);
      }
    }

    // Peak 곡선 — 얇은 점선 (먼저 그려 RMS 뒤로).
    ctx.strokeStyle = "#ffb547";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 2]);
    ctx.beginPath();
    let started = false;
    for (const p of points) {
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

    // RMS 곡선 — 굵은 실선.
    ctx.strokeStyle = "#6fcf97";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    started = false;
    for (const p of points) {
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

  function dbToY(db: number, h: number): number {
    // -60 floor → h-15, 0 ceiling → 5 (조금의 padding).
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

<div
  class="timeseries"
  bind:clientWidth={canvasWidth}
>
  <div class="header">
    <span class="title">
      ch{String(channel).padStart(2, "0")} {label || "(미정)"}
    </span>
    <span class="legend">
      <span class="legend-rms">━ RMS</span>
      <span class="legend-peak">┄ Peak</span>
    </span>
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
  }
  .title {
    color: #c8cdd6;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .legend {
    display: flex;
    gap: 0.6rem;
    font-size: 0.75rem;
  }
  .legend-rms {
    color: #6fcf97;
  }
  .legend-peak {
    color: #ffb547;
  }
  canvas {
    display: block;
    border: 1px solid #262a33;
    border-radius: 0.2rem;
  }
</style>
