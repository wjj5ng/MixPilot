<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import Meters from "./Meters.svelte";
  import {
    fetchAuditLog,
    fetchChannelMap,
    fetchHealth,
    fetchRecentActions,
    forceDryRun,
    subscribeMeters,
    subscribeRecommendations,
    type ActionEntry,
    type AuditEntry,
    type ChannelMapEntry,
    type ChannelMeter,
    type HealthResponse,
    type RecommendationPayload,
  } from "./lib/api";

  let health = $state<HealthResponse | null>(null);
  let healthError = $state<string | null>(null);
  let recommendations = $state<RecommendationPayload[]>([]);
  let streamConnected = $state(false);
  let recentActions = $state<ActionEntry[]>([]);
  let killSwitchStatus = $state<string | null>(null);
  let killSwitchBusy = $state(false);
  let meterChannels = $state<ChannelMeter[]>([]);
  let metersConnected = $state(false);
  let auditEntries = $state<AuditEntry[]>([]);
  let auditEnabled = $state<boolean | null>(null);
  let channelMap = $state<ChannelMapEntry[]>([]);
  let channelMapError = $state<string | null>(null);

  const MAX_VISIBLE_RECS = 50;
  const RECENT_ACTIONS_POLL_MS = 5_000;
  const AUDIT_LOG_POLL_MS = 10_000;
  const AUDIT_LIMIT = 50;

  let unsubscribe: (() => void) | null = null;
  let unsubscribeMeters: (() => void) | null = null;
  let recentActionsTimer: ReturnType<typeof setInterval> | null = null;
  let auditLogTimer: ReturnType<typeof setInterval> | null = null;

  async function refreshRecentActions(): Promise<void> {
    try {
      const data = await fetchRecentActions();
      recentActions = data.entries;
    } catch (e) {
      console.warn("recent-actions fetch failed", e);
    }
  }

  async function refreshAuditLog(): Promise<void> {
    try {
      const data = await fetchAuditLog(AUDIT_LIMIT);
      auditEnabled = data.enabled;
      auditEntries = data.entries;
    } catch (e) {
      console.warn("audit-log fetch failed", e);
    }
  }

  async function refreshChannelMap(): Promise<void> {
    try {
      const data = await fetchChannelMap();
      channelMap = data.entries;
      channelMapError = null;
    } catch (e) {
      channelMapError = String(e);
    }
  }

  function categoryLabel(cat: string): string {
    return (
      {
        vocal: "보컬",
        preacher: "설교자",
        choir: "성가대",
        instrument: "악기",
        unknown: "미정",
      }[cat] ?? cat
    );
  }

  async function handleKillSwitch(): Promise<void> {
    if (killSwitchBusy) return;
    killSwitchBusy = true;
    try {
      const data = await forceDryRun();
      killSwitchStatus = `${data.status}${data.effective_mode ? ` (mode=${data.effective_mode})` : ""}`;
      // health도 새로고침 — operating_mode 표시 갱신.
      health = await fetchHealth();
    } catch (e) {
      killSwitchStatus = `오류: ${String(e)}`;
    } finally {
      killSwitchBusy = false;
    }
  }

  onMount(async () => {
    try {
      health = await fetchHealth();
    } catch (e) {
      healthError = String(e);
    }
    await refreshRecentActions();
    recentActionsTimer = setInterval(refreshRecentActions, RECENT_ACTIONS_POLL_MS);

    await refreshAuditLog();
    auditLogTimer = setInterval(refreshAuditLog, AUDIT_LOG_POLL_MS);

    await refreshChannelMap();

    unsubscribe = subscribeRecommendations(
      (rec) => {
        streamConnected = true;
        // 최신을 위쪽에. 최대 N개 유지.
        recommendations = [rec, ...recommendations].slice(0, MAX_VISIBLE_RECS);
      },
      () => {
        streamConnected = false;
      },
    );

    unsubscribeMeters = subscribeMeters(
      (snapshot) => {
        metersConnected = true;
        meterChannels = snapshot.channels;
      },
      () => {
        metersConnected = false;
      },
    );
  });

  onDestroy(() => {
    if (unsubscribe) unsubscribe();
    if (unsubscribeMeters) unsubscribeMeters();
    if (recentActionsTimer !== null) clearInterval(recentActionsTimer);
    if (auditLogTimer !== null) clearInterval(auditLogTimer);
  });

  // 감사 로그 필터.
  type AuditOutcomeFilter = null | "applied" | "blocked";
  let auditOutcomeFilter = $state<AuditOutcomeFilter>(null);
  let auditQuery = $state("");

  const visibleAuditEntries = $derived.by(() => {
    let entries = auditEntries;
    if (auditOutcomeFilter === "applied") {
      entries = entries.filter((e) => e.outcome === "applied");
    } else if (auditOutcomeFilter === "blocked") {
      entries = entries.filter(
        (e) => e.outcome === "blocked_policy" || e.outcome === "blocked_guard",
      );
    }
    const query = auditQuery.trim().toLowerCase();
    if (query) {
      entries = entries.filter((e) => {
        const haystack = [
          String(e.channel),
          `ch${String(e.channel).padStart(2, "0")}`,
          e.label,
          e.category,
          e.kind,
          e.reason,
          e.rec_reason,
        ]
          .join(" ")
          .toLowerCase();
        return haystack.includes(query);
      });
    }
    return entries;
  });

  function outcomeLabel(outcome: string): string {
    return (
      {
        applied: "적용",
        blocked_policy: "정책 차단",
        blocked_guard: "가드 차단",
      }[outcome] ?? outcome
    );
  }

  function outcomeClass(outcome: string): string {
    return (
      {
        applied: "outcome-applied",
        blocked_policy: "outcome-blocked",
        blocked_guard: "outcome-blocked",
      }[outcome] ?? ""
    );
  }

  function formatAuditTime(ts: number): string {
    const d = new Date(ts * 1000);
    return d.toLocaleString("ko-KR", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }

  function kindLabel(kind: string): string {
    return (
      {
        info: "정보",
        gain_adjust: "게인",
        eq_adjust: "EQ",
        mute: "뮤트",
        unmute: "언뮤트",
        feedback_alert: "하울링",
      }[kind] ?? kind
    );
  }

  // 종류별 필터 — null이면 모두 표시.
  type KindFilter = null | "alerts" | "info";
  let kindFilter = $state<KindFilter>(null);

  const visibleRecommendations = $derived.by(() => {
    if (kindFilter === null) return recommendations;
    if (kindFilter === "alerts") {
      // 정보(info) 제외 — 액션·하울링만.
      return recommendations.filter((r) => r.kind !== "info");
    }
    if (kindFilter === "info") {
      return recommendations.filter((r) => r.kind === "info");
    }
    return recommendations;
  });

  function clearRecommendations(): void {
    recommendations = [];
  }
</script>

<main>
  <header>
    <h1>MixPilot</h1>
    <div class="subtitle">라이브 오디오 분석·믹싱 어시스턴트</div>
  </header>

  <section class="card">
    <h2>상태</h2>
    {#if healthError}
      <p class="error">백엔드 연결 실패: {healthError}</p>
    {:else if health}
      <dl>
        <dt>운영 모드</dt><dd>{health.operating_mode}</dd>
        <dt>샘플레이트</dt><dd>{health.sample_rate} Hz</dd>
        <dt>채널 수</dt><dd>{health.num_channels}</dd>
        <dt>오디오 캡처</dt><dd>{health.audio_enabled ? "활성" : "비활성"}</dd>
        <dt>LUFS 분석</dt><dd>{health.lufs_analysis_enabled ? "활성" : "비활성"}</dd>
        <dt>Feedback 감지</dt><dd>{health.feedback_analysis_enabled ? "활성" : "비활성"}</dd>
        <dt>Peak 감시</dt><dd>{health.peak_analysis_enabled ? "활성" : "비활성"}</dd>
        <dt>Dynamic Range</dt><dd>{health.dynamic_range_analysis_enabled ? "활성" : "비활성"}</dd>
        <dt>LRA</dt><dd>{health.lra_analysis_enabled ? "활성" : "비활성"}</dd>
        <dt>미터 스트림</dt><dd>{health.meter_stream_enabled ? "활성" : "비활성"}</dd>
      </dl>
    {:else}
      <p>로딩 중…</p>
    {/if}
  </section>

  <section class="card">
    <h2>
      채널 매핑 ({channelMap.length})
      <button
        class="reload-btn"
        onclick={refreshChannelMap}
        title="config/channels.yaml 다시 읽기"
      >새로고침</button>
    </h2>
    {#if channelMapError}
      <p class="error">로드 실패: {channelMapError}</p>
    {:else if channelMap.length === 0}
      <p class="hint">채널맵이 비어 있습니다 — <code>config/channels.yaml</code> 확인.</p>
    {:else}
      <table class="channel-map">
        <thead>
          <tr>
            <th>ch</th>
            <th>카테고리</th>
            <th>라벨</th>
          </tr>
        </thead>
        <tbody>
          {#each channelMap as entry (entry.channel)}
            <tr>
              <td class="ch-num">ch{String(entry.channel).padStart(2, "0")}</td>
              <td class="ch-category">
                <span class="cat-pill cat-{entry.category}">{categoryLabel(entry.category)}</span>
              </td>
              <td class="ch-label">{entry.label || "—"}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </section>

  <section class="card">
    <h2>
      라이브 미터 ({meterChannels.length})
      <span class="stream-status" class:connected={metersConnected}>
        {metersConnected ? "수신 중" : "대기"}
      </span>
    </h2>
    <Meters channels={meterChannels} />
  </section>

  <section class="card kill-switch">
    <h2>킬 스위치</h2>
    <p class="hint">
      자동 액션을 즉시 정지하고 운영자가 직접 콘솔을 제어하도록
      <code>dry-run</code> 모드로 강제 다운그레이드합니다. 한 번 누르면 프로세스
      재시작 전까지 모든 자동 송신이 차단됩니다 (ADR-0008 §3).
    </p>
    <button class="danger" disabled={killSwitchBusy} onclick={handleKillSwitch}>
      {killSwitchBusy ? "처리 중…" : "🛑 자동 응답 정지 (dry-run 강제)"}
    </button>
    {#if killSwitchStatus}
      <p class="status">→ {killSwitchStatus}</p>
    {/if}
  </section>

  <section class="card">
    <h2>
      최근 자동 액션 ({recentActions.length})
      <span class="hint-inline">— 60초 윈도우, 5초마다 새로고침</span>
    </h2>
    {#if recentActions.length === 0}
      <p class="hint">자동 적용된 액션 없음.</p>
    {:else}
      <ul class="action-list">
        {#each recentActions as action, i (i)}
          <li class="action">
            <div class="action-head">
              <span class="action-channel">ch{String(action.channel).padStart(2, "0")}</span>
              <span class="action-kind">{action.kind}</span>
              <span class="action-time">{action.timestamp.toFixed(1)}</span>
            </div>
            <div class="action-osc">
              {#each action.osc_messages as msg}
                <code>{msg.address} = {msg.value}</code>
              {/each}
            </div>
            {#if action.reason}
              <div class="action-reason">{action.reason}</div>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section class="card">
    <h2>
      감사 로그 ({visibleAuditEntries.length}{visibleAuditEntries.length !==
      auditEntries.length
        ? ` / ${auditEntries.length}`
        : ""})
      <span class="hint-inline">— JSONL 영구 이력, 10초마다 새로고침</span>
    </h2>
    {#if auditEnabled === false}
      <p class="hint">
        <code>MIXPILOT_AUDIT_LOG_PATH</code>가 설정되지 않아 감사 로그가
        비활성입니다. ADR-0008 §3.8 참조.
      </p>
    {:else if auditEntries.length === 0}
      <p class="hint">아직 자동 액션 시도가 없습니다.</p>
    {:else}
      <div class="audit-controls">
        <div class="filter-group" role="group" aria-label="결과 필터">
          <button
            class="filter-btn"
            class:active={auditOutcomeFilter === null}
            onclick={() => (auditOutcomeFilter = null)}
          >전체</button>
          <button
            class="filter-btn"
            class:active={auditOutcomeFilter === "applied"}
            onclick={() => (auditOutcomeFilter = "applied")}
          >적용</button>
          <button
            class="filter-btn"
            class:active={auditOutcomeFilter === "blocked"}
            onclick={() => (auditOutcomeFilter = "blocked")}
          >차단</button>
        </div>
        <input
          class="audit-search"
          type="search"
          placeholder="ch / 라벨 / 사유 검색…"
          bind:value={auditQuery}
        />
      </div>
      {#if visibleAuditEntries.length === 0}
        <p class="hint">검색·필터 일치 결과가 없습니다.</p>
      {:else}
      <ul class="audit-list">
        {#each visibleAuditEntries as entry, i (i)}
          <li class="audit-entry {outcomeClass(entry.outcome)}">
            <div class="audit-head">
              <span class="audit-time">{formatAuditTime(entry.timestamp)}</span>
              <span class="audit-channel">
                ch{String(entry.channel).padStart(2, "0")}
                {#if entry.label}<span class="audit-label">{entry.label}</span>{/if}
              </span>
              <span class="audit-kind">{kindLabel(entry.kind)}</span>
              <span class="audit-outcome">{outcomeLabel(entry.outcome)}</span>
            </div>
            {#if entry.reason}
              <div class="audit-reason">{entry.reason}</div>
            {/if}
            {#if entry.rec_reason}
              <div class="audit-rec-reason">→ {entry.rec_reason}</div>
            {/if}
          </li>
        {/each}
      </ul>
      {/if}
    {/if}
  </section>

  <section class="card">
    <h2>
      추천 스트림
      <span class="stream-status" class:connected={streamConnected}>
        {streamConnected ? "수신 중" : "대기"}
      </span>
    </h2>
    <div class="rec-controls">
      <div class="filter-group" role="group" aria-label="추천 필터">
        <button
          class="filter-btn"
          class:active={kindFilter === null}
          onclick={() => (kindFilter = null)}
        >전체 ({recommendations.length})</button>
        <button
          class="filter-btn"
          class:active={kindFilter === "alerts"}
          onclick={() => (kindFilter = "alerts")}
        >경고만</button>
        <button
          class="filter-btn"
          class:active={kindFilter === "info"}
          onclick={() => (kindFilter = "info")}
        >정보만</button>
      </div>
      <button
        class="clear-btn"
        disabled={recommendations.length === 0}
        onclick={clearRecommendations}
      >비우기</button>
    </div>
    {#if recommendations.length === 0}
      <p class="hint">
        아직 추천 없음. <code>MIXPILOT_AUDIO__ENABLED=true</code>로 캡처를 켜야
        분석이 시작됩니다.
      </p>
    {:else if visibleRecommendations.length === 0}
      <p class="hint">현재 필터에 일치하는 추천이 없습니다.</p>
    {:else}
      <ul class="rec-list">
        {#each visibleRecommendations as rec, i (i)}
          <li class="rec rec--{rec.kind}">
            <div class="rec-head">
              <span class="rec-channel">ch{String(rec.channel).padStart(2, "0")}</span>
              <span class="rec-kind">{kindLabel(rec.kind)}</span>
              <span class="rec-confidence">{Math.round(rec.confidence * 100)}%</span>
            </div>
            <div class="rec-reason">{rec.reason}</div>
          </li>
        {/each}
      </ul>
    {/if}
  </section>
</main>

<style>
  main {
    max-width: 960px;
    margin: 0 auto;
    padding: 2rem 1.5rem 4rem;
  }

  header h1 {
    margin: 0 0 0.25rem;
    font-size: 2rem;
    letter-spacing: -0.02em;
  }
  header .subtitle {
    color: #8b95a3;
    font-size: 0.9rem;
    margin-bottom: 2rem;
  }

  .card {
    background: #1a1d24;
    border: 1px solid #262a33;
    border-radius: 0.5rem;
    padding: 1.25rem 1.5rem;
    margin-bottom: 1.5rem;
  }
  .card h2 {
    margin: 0 0 1rem;
    font-size: 1.1rem;
    color: #c8cdd6;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  dl {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 0.35rem 1rem;
    margin: 0;
  }
  dt {
    color: #8b95a3;
  }

  .error {
    color: #ff7676;
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

  .stream-status {
    font-size: 0.75rem;
    padding: 0.2rem 0.55rem;
    border-radius: 999px;
    background: #2a2f39;
    color: #8b95a3;
    font-weight: 500;
  }
  .stream-status.connected {
    background: #1e3a2e;
    color: #6fcf97;
  }

  /* 채널 매핑 카드 */
  .channel-map {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
  }
  .channel-map th {
    text-align: left;
    color: #8b95a3;
    font-weight: 500;
    padding: 0.35rem 0.5rem;
    border-bottom: 1px solid #2a2f39;
  }
  .channel-map td {
    padding: 0.3rem 0.5rem;
    border-bottom: 1px solid #1a1d24;
    vertical-align: middle;
  }
  .channel-map tbody tr:hover {
    background: #1f232b;
  }
  .ch-num {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    color: #8b95a3;
    width: 4rem;
  }
  .ch-category {
    width: 6rem;
  }
  .ch-label {
    color: #e6e8eb;
  }
  .cat-pill {
    display: inline-block;
    padding: 0.1rem 0.5rem;
    border-radius: 999px;
    font-size: 0.75rem;
    background: #2a2f39;
    color: #c8cdd6;
  }
  .cat-vocal {
    background: #1e3a5f;
    color: #aac4ff;
  }
  .cat-preacher {
    background: #3d2e1a;
    color: #ffce80;
  }
  .cat-choir {
    background: #1e3a2e;
    color: #6fcf97;
  }
  .cat-instrument {
    background: #3a1e3a;
    color: #d99ad9;
  }
  .cat-unknown {
    background: #2a2f39;
    color: #8b95a3;
  }
  .reload-btn {
    background: transparent;
    color: #8b95a3;
    border: 1px solid #2a2f39;
    padding: 0.2rem 0.55rem;
    border-radius: 0.25rem;
    font-size: 0.75rem;
    cursor: pointer;
    margin-left: auto;
    font-weight: 400;
  }
  .reload-btn:hover {
    background: #2a2f39;
    color: #c8cdd6;
  }

  /* 감사 로그 카드 */
  .audit-controls {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
    flex-wrap: wrap;
  }
  .audit-search {
    flex: 1;
    min-width: 12rem;
    background: #1a1d24;
    color: #c8cdd6;
    border: 1px solid #2a2f39;
    border-radius: 0.25rem;
    padding: 0.3rem 0.55rem;
    font-size: 0.85rem;
    font-family: inherit;
  }
  .audit-search:focus {
    outline: none;
    border-color: #2a4a73;
    background: #232730;
  }
  .audit-search::placeholder {
    color: #5a6270;
  }
  .audit-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    max-height: 24rem;
    overflow-y: auto;
  }
  .audit-entry {
    background: #232730;
    border-left: 3px solid #4a5263;
    padding: 0.5rem 0.75rem;
    border-radius: 0 0.25rem 0.25rem 0;
    font-size: 0.85rem;
  }
  .audit-entry.outcome-applied {
    border-left-color: #6fcf97;
  }
  .audit-entry.outcome-blocked {
    border-left-color: #ffb547;
  }
  .audit-head {
    display: flex;
    gap: 0.65rem;
    align-items: baseline;
    flex-wrap: wrap;
  }
  .audit-time {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    color: #5a6270;
    font-size: 0.75rem;
    font-variant-numeric: tabular-nums;
  }
  .audit-channel {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    color: #8b95a3;
  }
  .audit-label {
    color: #c8cdd6;
    margin-left: 0.25rem;
    font-family: inherit;
  }
  .audit-kind {
    color: #c8cdd6;
    font-weight: 500;
  }
  .audit-outcome {
    margin-left: auto;
    font-size: 0.75rem;
    padding: 0.1rem 0.45rem;
    border-radius: 999px;
    background: #2a2f39;
    color: #c8cdd6;
  }
  .outcome-applied .audit-outcome {
    background: #1e3a2e;
    color: #6fcf97;
  }
  .outcome-blocked .audit-outcome {
    background: #3d2e1a;
    color: #ffb547;
  }
  .audit-reason {
    color: #b6bdc7;
    font-size: 0.8rem;
    margin-top: 0.2rem;
  }
  .audit-rec-reason {
    color: #8b95a3;
    font-size: 0.8rem;
    font-style: italic;
    margin-top: 0.1rem;
  }

  .rec-controls {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
  }
  .filter-group {
    display: flex;
    gap: 0.25rem;
  }
  .filter-btn {
    background: #232730;
    color: #8b95a3;
    border: 1px solid #2a2f39;
    padding: 0.3rem 0.65rem;
    border-radius: 0.25rem;
    font-size: 0.8rem;
    cursor: pointer;
    transition: background 0.1s, color 0.1s;
  }
  .filter-btn:hover:not(.active) {
    background: #2a2f39;
    color: #c8cdd6;
  }
  .filter-btn.active {
    background: #1e3a5f;
    color: #aac4ff;
    border-color: #2a4a73;
  }
  .clear-btn {
    background: transparent;
    color: #8b95a3;
    border: 1px solid #2a2f39;
    padding: 0.3rem 0.65rem;
    border-radius: 0.25rem;
    font-size: 0.8rem;
    cursor: pointer;
    transition: background 0.1s, color 0.1s;
  }
  .clear-btn:hover:not(:disabled) {
    background: #2a2f39;
    color: #c8cdd6;
  }
  .clear-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .rec-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .rec {
    background: #232730;
    border-left: 3px solid #4a5263;
    padding: 0.6rem 0.85rem;
    border-radius: 0 0.25rem 0.25rem 0;
  }
  .rec--feedback_alert {
    border-left-color: #ff7676;
  }
  .rec--info {
    border-left-color: #6c8cff;
  }
  .rec-head {
    display: flex;
    gap: 0.75rem;
    align-items: baseline;
    font-size: 0.85rem;
    margin-bottom: 0.2rem;
  }
  .rec-channel {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    color: #8b95a3;
  }
  .rec-kind {
    color: #c8cdd6;
    font-weight: 600;
  }
  .rec-confidence {
    color: #8b95a3;
    margin-left: auto;
    font-variant-numeric: tabular-nums;
  }
  .rec-reason {
    color: #e6e8eb;
    font-size: 0.95rem;
  }

  /* 킬 스위치 */
  .kill-switch .danger {
    background: #4a1f1f;
    color: #ff9a9a;
    border: 1px solid #6a2a2a;
    padding: 0.6rem 1rem;
    border-radius: 0.35rem;
    font-size: 1rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s;
  }
  .kill-switch .danger:hover:not(:disabled) {
    background: #6a2a2a;
    color: #ffcaca;
  }
  .kill-switch .danger:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .kill-switch .status {
    margin: 0.75rem 0 0;
    color: #ff7676;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.85rem;
  }
  .hint-inline {
    font-size: 0.75rem;
    color: #8b95a3;
    font-weight: 400;
    margin-left: 0.5rem;
  }

  /* 최근 액션 */
  .action-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .action {
    background: #232730;
    border-left: 3px solid #6fcf97;
    padding: 0.6rem 0.85rem;
    border-radius: 0 0.25rem 0.25rem 0;
  }
  .action-head {
    display: flex;
    gap: 0.75rem;
    align-items: baseline;
    font-size: 0.85rem;
    margin-bottom: 0.25rem;
  }
  .action-channel {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    color: #8b95a3;
  }
  .action-kind {
    color: #c8cdd6;
    font-weight: 600;
  }
  .action-time {
    color: #8b95a3;
    margin-left: auto;
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .action-osc {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem 0.5rem;
    margin-bottom: 0.25rem;
  }
  .action-osc code {
    font-size: 0.8rem;
  }
  .action-reason {
    color: #b6bdc7;
    font-size: 0.85rem;
  }
</style>
