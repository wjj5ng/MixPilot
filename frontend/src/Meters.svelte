<script lang="ts">
  import type { ChannelMeter } from "./lib/api";

  let { channels = [] }: { channels: ChannelMeter[] } = $props();

  // dBFS 스케일 범위 — 라이브 운영 표준.
  const DB_FLOOR = -60;
  const DB_CEILING = 0;

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
          <div class="meter-label">ch{String(ch.channel).padStart(2, "0")}</div>
          <div class="meter-bar">
            <div
              class="meter-fill meter-rms"
              style="width: {normalize(ch.rms_dbfs) * 100}%; background: {colorFor(ch.rms_dbfs)};"
            ></div>
            <div
              class="meter-peak"
              style="left: {normalize(ch.peak_dbfs) * 100}%; background: {colorFor(ch.peak_dbfs)};"
            ></div>
          </div>
          <div class="meter-values">
            <span class="meter-rms-val">RMS {ch.rms_dbfs.toFixed(1)}</span>
            <span class="meter-peak-val">Peak {ch.peak_dbfs.toFixed(1)}</span>
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
    grid-template-columns: 3rem 1fr auto;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.8rem;
  }
  .meter-label {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    color: #8b95a3;
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
  .scale {
    display: flex;
    justify-content: space-between;
    margin-left: 3.5rem;
    margin-top: 0.4rem;
    font-size: 0.65rem;
    color: #5a6270;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
</style>
