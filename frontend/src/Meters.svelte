<script lang="ts">
  import type { ChannelMeter } from "./lib/api";

  let { channels = [] }: { channels: ChannelMeter[] } = $props();

  // dBFS 스케일 범위 — 라이브 운영 표준.
  const DB_FLOOR = -60;
  const DB_CEILING = 0;

  // Peak hold: 새 peak가 들어오면 즉시 위치 갱신 + 타임스탬프.
  // HOLD_MS 동안 유지 → 이후 DECAY_DB_PER_FRAME만큼 매 snapshot 떨어뜨림.
  const HOLD_MS = 1500;
  const DECAY_DB_PER_FRAME = 0.5;

  type Hold = { dbfs: number; setAt: number };
  // 채널별 hold 상태 — $state로 reactivity 확보.
  let holds = $state<Map<number, Hold>>(new Map());

  // channels prop이 갱신될 때마다 hold 상태 갱신.
  $effect(() => {
    const now = Date.now();
    const next = new Map(holds);
    for (const ch of channels) {
      const cur = next.get(ch.channel);
      if (cur === undefined || ch.peak_dbfs >= cur.dbfs) {
        // 새 peak가 더 크거나 같음 → 즉시 갱신 + 타임 리셋.
        next.set(ch.channel, { dbfs: ch.peak_dbfs, setAt: now });
      } else if (now - cur.setAt > HOLD_MS) {
        // hold 만료 → 점진적 감쇠. 현재 peak 아래로는 안 떨어짐.
        const decayed = Math.max(ch.peak_dbfs, cur.dbfs - DECAY_DB_PER_FRAME);
        next.set(ch.channel, { dbfs: decayed, setAt: cur.setAt });
      }
    }
    // 더 이상 존재하지 않는 채널은 holds에서 제거.
    const liveIds = new Set(channels.map((c) => c.channel));
    for (const id of next.keys()) {
      if (!liveIds.has(id)) next.delete(id);
    }
    holds = next;
  });

  /** dBFS를 0(floor) ~ 1(ceiling) 정규화. */
  function normalize(db: number): number {
    if (!Number.isFinite(db)) return 0;
    return Math.max(0, Math.min(1, (db - DB_FLOOR) / (DB_CEILING - DB_FLOOR)));
  }

  /** dBFS → 색상 (녹색 안전 / 황색 헤드룸 임박 / 적색 클립). */
  function colorFor(db: number): string {
    if (db >= -1) return "#ff5252";
    if (db >= -6) return "#ffb547";
    return "#6fcf97";
  }

  /** LRA(LU) → 색상.
   *  < 5 LU: 압축 매우 강함(적), 5~15 정상(녹), > 15 다이내믹 큼(황).
   *  null/undefined이면 회색(미평가). */
  function lraColor(lu: number | null | undefined): string {
    if (lu === null || lu === undefined) return "#5a6270";
    if (lu < 5) return "#ff7676";
    if (lu > 15) return "#ffb547";
    return "#6fcf97";
  }

  // 옥타브 밴드 표시 스케일: -60(floor) ~ 0(ceiling) dBFS.
  const BAND_FLOOR_DBFS = -60;
  const BAND_CEILING_DBFS = 0;

  /** 밴드 dBFS → 0(낮음) ~ 1(높음) 정규화 (시각 막대 높이 비율). */
  function bandLevel(db: number): number {
    if (!Number.isFinite(db)) return 0;
    return Math.max(
      0,
      Math.min(1, (db - BAND_FLOOR_DBFS) / (BAND_CEILING_DBFS - BAND_FLOOR_DBFS)),
    );
  }

  // 표시용 옥타브 라벨 (백엔드의 OCTAVE_CENTERS_HZ와 동일 순서).
  const OCTAVE_LABELS = ["125", "250", "500", "1k", "2k", "4k", "8k", "16k"];

  /** Phase correlation [-1, +1] → 색상.
   *  < -0.3: 위험(적), -0.3~0.5: 정상(녹), > 0.5: 거의 모노(황). null=회색. */
  function phaseColor(corr: number | null | undefined): string {
    if (corr === null || corr === undefined) return "#5a6270";
    if (corr < -0.3) return "#ff7676";
    if (corr > 0.5) return "#ffb547";
    return "#6fcf97";
  }

  /** 해당 채널의 hold dBFS, 없으면 현재 peak로 폴백. */
  function holdDbfs(ch: ChannelMeter): number {
    return holds.get(ch.channel)?.dbfs ?? ch.peak_dbfs;
  }
</script>

<div class="meters">
  {#if channels.length === 0}
    <p class="hint">
      미터 스트림 비활성 또는 데이터 없음 —
      <code>MIXPILOT_METER_STREAM__ENABLED=true</code> + 오디오 캡처가 필요합니다.
    </p>
  {:else}
    <div class="meter-grid">
      {#each channels as ch (ch.channel)}
        <div class="meter">
          <div class="meter-ident">
            <span class="meter-channel">ch{String(ch.channel).padStart(2, "0")}</span>
            <span class="meter-source">
              {#if ch.label}{ch.label}{:else}<em>{ch.category}</em>{/if}
            </span>
          </div>
          <div class="meter-bar">
            <div
              class="meter-fill meter-rms"
              style="width: {normalize(ch.rms_dbfs) * 100}%; background: {colorFor(ch.rms_dbfs)};"
            ></div>
            <div
              class="meter-peak"
              style="left: {normalize(ch.peak_dbfs) * 100}%; background: {colorFor(ch.peak_dbfs)};"
            ></div>
            <div
              class="meter-hold"
              style="left: {normalize(holdDbfs(ch)) * 100}%; background: {colorFor(holdDbfs(ch))};"
            ></div>
          </div>
          <div class="meter-values">
            <span class="meter-rms-val">RMS {ch.rms_dbfs.toFixed(1)}</span>
            <span class="meter-peak-val">Peak {ch.peak_dbfs.toFixed(1)}</span>
            <span class="meter-lra-val" style="color: {lraColor(ch.lra_lu)};">
              LRA {ch.lra_lu === null || ch.lra_lu === undefined
                ? "—"
                : `${ch.lra_lu.toFixed(1)} LU`}
            </span>
            {#if ch.stereo_pair_with}
              <span class="meter-phase-val" style="color: {phaseColor(ch.phase_with_pair)};">
                ↔{String(ch.stereo_pair_with).padStart(2, "0")} φ{ch.phase_with_pair === null || ch.phase_with_pair === undefined
                  ? "—"
                  : (ch.phase_with_pair >= 0 ? "+" : "") + ch.phase_with_pair.toFixed(2)}
              </span>
            {/if}
          </div>
          <div class="meter-spectrum" role="img" aria-label="옥타브 스펙트럼">
            {#each ch.octave_bands_dbfs ?? [] as bandDb, i (i)}
              <div
                class="band-cell"
                title="{OCTAVE_LABELS[i] ?? `band ${i + 1}`} Hz: {bandDb.toFixed(1)} dBFS"
              >
                <div
                  class="band-fill"
                  style="height: {bandLevel(bandDb) * 100}%; background: {colorFor(bandDb)};"
                ></div>
              </div>
            {/each}
          </div>
        </div>
      {/each}
    </div>
    <div class="scale">
      <span>-60</span><span>-48</span><span>-36</span><span>-24</span><span>-12</span><span>0 dBFS</span>
    </div>
  {/if}
</div>

<style>
  .meters {
    width: 100%;
  }
  .hint {
    color: #8b95a3;
    font-size: 0.9rem;
  }
  code {
    background: #262a33;
    padding: 0.15rem 0.4rem;
    border-radius: 0.25rem;
    font-size: 0.85em;
  }
  .meter-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 0.25rem;
  }
  .meter {
    display: grid;
    grid-template-columns: 11rem 1fr auto;
    grid-template-rows: auto auto;
    align-items: center;
    column-gap: 0.5rem;
    row-gap: 0.2rem;
    font-size: 0.8rem;
  }
  .meter-ident {
    grid-row: 1 / span 2;
  }
  .meter-bar {
    grid-column: 2;
    grid-row: 1;
  }
  .meter-values {
    grid-column: 3;
    grid-row: 1;
  }
  .meter-spectrum {
    grid-column: 2 / span 2;
    grid-row: 2;
    display: grid;
    grid-template-columns: repeat(8, 1fr);
    gap: 1px;
    height: 0.4rem;
  }
  .band-cell {
    background: #1a1d24;
    border-radius: 0.05rem;
    overflow: hidden;
    position: relative;
    display: flex;
    align-items: flex-end;
  }
  .band-fill {
    width: 100%;
    transition: height 60ms linear, background 60ms linear;
    opacity: 0.85;
  }
  .meter-ident {
    display: flex;
    flex-direction: column;
    line-height: 1.1;
    min-width: 0;
  }
  .meter-channel {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    color: #8b95a3;
    font-size: 0.75rem;
  }
  .meter-source {
    color: #c8cdd6;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .meter-source em {
    color: #5a6270;
    font-style: italic;
    font-size: 0.85em;
  }
  .meter-bar {
    position: relative;
    height: 0.75rem;
    background: #1a1d24;
    border: 1px solid #262a33;
    border-radius: 0.15rem;
    overflow: hidden;
  }
  .meter-fill {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    transition: width 60ms linear;
    opacity: 0.85;
  }
  .meter-peak {
    position: absolute;
    top: -1px;
    bottom: -1px;
    width: 2px;
    transition: left 60ms linear;
    box-shadow: 0 0 4px currentColor;
  }
  .meter-hold {
    /* 표준 콘솔 미터의 peak hold — 가는 막대가 잠시 머문다. */
    position: absolute;
    top: 0;
    bottom: 0;
    width: 1px;
    opacity: 0.6;
    transition: left 200ms linear;
  }
  .meter-values {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-variant-numeric: tabular-nums;
    color: #c8cdd6;
    display: flex;
    gap: 0.5rem;
  }
  .meter-rms-val {
    color: #8b95a3;
  }
  .meter-peak-val {
    color: #c8cdd6;
  }
  .meter-lra-val {
    font-variant-numeric: tabular-nums;
    min-width: 6.5rem;
    text-align: right;
  }
  .meter-phase-val {
    font-variant-numeric: tabular-nums;
    min-width: 6.5rem;
    text-align: right;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.75rem;
  }
  .scale {
    display: flex;
    justify-content: space-between;
    margin-left: 11.5rem;
    margin-top: 0.4rem;
    font-size: 0.65rem;
    color: #5a6270;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
</style>
