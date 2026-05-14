<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import Meters from "./Meters.svelte";
  import Timeseries from "./Timeseries.svelte";
  import {
    fetchAuditLog,
    fetchChannelMap,
    fetchHealth,
    fetchOperatingMode,
    fetchRecentActions,
    fetchRules,
    forceDryRun,
    setOperatingMode,
    setRuleEnabled,
    subscribeMeters,
    subscribeRecommendations,
    updateChannel,
    type ActionEntry,
    type AuditEntry,
    type ChannelMapEntry,
    type ChannelMeter,
    type HealthResponse,
    type OperatingModeState,
    type RecommendationPayload,
    type RuleState,
  } from "./lib/api";

  let health = $state<HealthResponse | null>(null);
  let healthError = $state<string | null>(null);
  // 추천 + 도착 시각. service 운영자가 새 알림을 놓치지 않도록 발화 시각 추적.
  type StreamedRecommendation = RecommendationPayload & { receivedAt: number };
  let recommendations = $state<StreamedRecommendation[]>([]);
  // 마지막 "확인" 누른 시각. receivedAt > lastAckedAt 인 추천은 미확인 = 강조.
  let lastAckedAt = $state<number>(Date.now());
  // 최근 도착 후 NEW_PULSE_MS 동안 펄스 강조. 매 250ms 톡으로 재평가 트리거.
  const NEW_PULSE_MS = 6_000;
  let nowTick = $state<number>(Date.now());
  let streamConnected = $state(false);
  let recentActions = $state<ActionEntry[]>([]);
  let killSwitchStatus = $state<string | null>(null);
  let killSwitchBusy = $state(false);
  let meterChannels = $state<ChannelMeter[]>([]);
  let metersConnected = $state(false);

  // 채널별 시계열 ring buffer — App 차원에서 누적, Timeseries 컴포넌트로 전달.
  // 60초 윈도우 × ~9 Hz ≈ 540 points/channel × 32ch ≈ 17k 숫자 — 가볍다.
  type SeriesPoint = { t: number; rms: number; peak: number };
  const TIMESERIES_WINDOW_MS = 120_000; // 2분치 보관(최대 windowSeconds=120).
  let meterHistory = $state<Map<number, SeriesPoint[]>>(new Map());
  let selectedTimeseriesChannel = $state<number | null>(null);
  let timeseriesWindowSec = $state(60);
  let auditEntries = $state<AuditEntry[]>([]);
  let auditEnabled = $state<boolean | null>(null);
  let channelMap = $state<ChannelMapEntry[]>([]);
  let channelMapError = $state<string | null>(null);
  let rules = $state<RuleState[]>([]);
  let rulesError = $state<string | null>(null);
  let rulesBusy = $state<Set<string>>(new Set());
  let operatingMode = $state<OperatingModeState | null>(null);
  let operatingModeError = $state<string | null>(null);
  let operatingModeBusy = $state(false);

  const MAX_VISIBLE_RECS = 50;
  const RECENT_ACTIONS_POLL_MS = 5_000;
  const AUDIT_LOG_POLL_MS = 10_000;
  const AUDIT_LIMIT = 50;

  let unsubscribe: (() => void) | null = null;
  let unsubscribeMeters: (() => void) | null = null;
  let recentActionsTimer: ReturnType<typeof setInterval> | null = null;
  let auditLogTimer: ReturnType<typeof setInterval> | null = null;
  let nowTickTimer: ReturnType<typeof setInterval> | null = null;

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

  async function refreshOperatingMode(): Promise<void> {
    try {
      operatingMode = await fetchOperatingMode();
      operatingModeError = null;
    } catch (e) {
      operatingModeError = String(e);
    }
  }

  async function changeOperatingMode(mode: string): Promise<void> {
    if (operatingModeBusy) return;
    operatingModeBusy = true;
    operatingModeError = null;
    try {
      operatingMode = await setOperatingMode(mode);
    } catch (e) {
      operatingModeError = String(e);
    } finally {
      operatingModeBusy = false;
    }
  }

  async function refreshRules(): Promise<void> {
    try {
      const data = await fetchRules();
      rules = data.rules;
      rulesError = null;
    } catch (e) {
      rulesError = String(e);
    }
  }

  async function toggleRule(rule: RuleState): Promise<void> {
    if (rulesBusy.has(rule.name)) return;
    rulesBusy = new Set([...rulesBusy, rule.name]);
    try {
      const updated = await setRuleEnabled(rule.name, !rule.enabled);
      rules = rules.map((r) => (r.name === updated.name ? updated : r));
      rulesError = null;
    } catch (e) {
      rulesError = String(e);
    } finally {
      const next = new Set(rulesBusy);
      next.delete(rule.name);
      rulesBusy = next;
    }
  }

  function ruleLabel(name: string): string {
    return (
      {
        loudness: "RMS 라우드니스",
        lufs: "LUFS",
        peak: "Peak / True Peak",
        feedback: "하울링 감지",
        dynamic_range: "Dynamic Range",
        lra: "LRA",
        phase: "Stereo Phase",
      }[name] ?? name
    );
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

  // 채널맵 인-라인 편집 state — 한 번에 한 채널만 편집.
  const CATEGORIES = ["vocal", "preacher", "choir", "instrument", "unknown"];
  let editingChannel = $state<number | null>(null);
  let editCategory = $state<string>("unknown");
  let editLabel = $state<string>("");
  let editPair = $state<string>("");  // 빈 문자열 = None
  let editSaving = $state(false);
  let editError = $state<string | null>(null);

  function startEdit(entry: ChannelMapEntry): void {
    editingChannel = entry.channel;
    editCategory = entry.category;
    editLabel = entry.label;
    editPair = entry.stereo_pair_with ? String(entry.stereo_pair_with) : "";
    editError = null;
  }

  function cancelEdit(): void {
    editingChannel = null;
    editError = null;
  }

  async function saveEdit(): Promise<void> {
    if (editingChannel === null || editSaving) return;
    editSaving = true;
    editError = null;
    try {
      const pair =
        editPair.trim() === "" ? null : Number.parseInt(editPair, 10);
      if (pair !== null && (!Number.isFinite(pair) || pair < 1)) {
        throw new Error("stereo pair은 양수 채널 번호여야 합니다");
      }
      await updateChannel(editingChannel, editCategory, editLabel, pair);
      await refreshChannelMap();
      editingChannel = null;
    } catch (e) {
      editError = String(e);
    } finally {
      editSaving = false;
    }
  }

  async function handleKillSwitch(): Promise<void> {
    if (killSwitchBusy) return;
    killSwitchBusy = true;
    try {
      const data = await forceDryRun();
      killSwitchStatus = `${data.status}${data.effective_mode ? ` (mode=${data.effective_mode})` : ""}`;
      // 상태 갱신 — 모드 토글 비활성화 + kill_switch_engaged=true 반영.
      health = await fetchHealth();
      await refreshOperatingMode();
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
    await refreshRules();
    await refreshOperatingMode();

    unsubscribe = subscribeRecommendations(
      (rec) => {
        streamConnected = true;
        // 최신을 위쪽에. 도착 시각을 함께 박아 펄스/미확인 카운트 계산에 사용.
        const withTs: StreamedRecommendation = { ...rec, receivedAt: Date.now() };
        recommendations = [withTs, ...recommendations].slice(0, MAX_VISIBLE_RECS);
      },
      () => {
        streamConnected = false;
      },
    );

    // 펄스 표시·미확인 카운트는 시간에 종속 — 1/4초 톡으로 재평가 트리거.
    nowTickTimer = setInterval(() => {
      nowTick = Date.now();
    }, 250);

    unsubscribeMeters = subscribeMeters(
      (snapshot) => {
        metersConnected = true;
        meterChannels = snapshot.channels;
        // 시계열 buffer 누적 — 2분치만 유지.
        const now = Date.now();
        const cutoff = now - TIMESERIES_WINDOW_MS;
        const next = new Map(meterHistory);
        for (const ch of snapshot.channels) {
          const arr = next.get(ch.channel) ?? [];
          arr.push({ t: now, rms: ch.rms_dbfs, peak: ch.peak_dbfs });
          // 오래된 포인트 제거 (앞에서부터 잘라내기).
          while (arr.length > 0 && arr[0].t < cutoff) arr.shift();
          next.set(ch.channel, arr);
        }
        meterHistory = next;
        // 첫 데이터 도달 시 첫 채널을 디폴트 선택.
        if (selectedTimeseriesChannel === null && snapshot.channels.length > 0) {
          selectedTimeseriesChannel = snapshot.channels[0].channel;
        }
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
    if (nowTickTimer !== null) clearInterval(nowTickTimer);
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
    lastAckedAt = Date.now();
  }

  function acknowledgeRecommendations(): void {
    lastAckedAt = Date.now();
  }

  // 미확인 카운트 — 마지막 확인 시각 이후 도착한 추천.
  const unreadRecCount = $derived(
    recommendations.filter((r) => r.receivedAt > lastAckedAt).length,
  );

  function isRecNewlyArrived(rec: StreamedRecommendation): boolean {
    // 도착 후 NEW_PULSE_MS 이내면 펄스. nowTick 갱신 시 자동 재계산.
    return nowTick - rec.receivedAt < NEW_PULSE_MS;
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
        <dt>운영 모드</dt>
        <dd class="mode-cell">
          {#if operatingMode}
            <div
              class="mode-toggle"
              role="group"
              aria-label="운영 모드"
              class:locked={operatingMode.kill_switch_engaged}
            >
              {#each ["dry-run", "assist", "auto"] as m (m)}
                <button
                  class="mode-btn"
                  class:active={operatingMode.mode === m}
                  disabled={operatingModeBusy || operatingMode.kill_switch_engaged}
                  onclick={() => changeOperatingMode(m)}
                >{m}</button>
              {/each}
            </div>
            {#if operatingMode.kill_switch_engaged}
              <span class="kill-active">🛑 킬 스위치 활성 — 재시작 필요</span>
            {/if}
            {#if operatingModeError}
              <span class="error-inline">{operatingModeError}</span>
            {/if}
          {:else}
            <span>{health.operating_mode}</span>
          {/if}
        </dd>
        <dt>샘플레이트</dt><dd>{health.sample_rate} Hz</dd>
        <dt>채널 수</dt><dd>{health.num_channels}</dd>
        <dt>오디오 캡처</dt><dd>{health.audio_enabled ? "활성" : "비활성"}</dd>
        <dt>LUFS 분석</dt><dd>{health.lufs_analysis_enabled ? "활성" : "비활성"}</dd>
        <dt>Feedback 감지</dt><dd>{health.feedback_analysis_enabled ? "활성" : "비활성"}</dd>
        <dt>Peak 감시</dt><dd>{health.peak_analysis_enabled ? "활성" : "비활성"}</dd>
        <dt>Dynamic Range</dt><dd>{health.dynamic_range_analysis_enabled ? "활성" : "비활성"}</dd>
        <dt>LRA</dt><dd>{health.lra_analysis_enabled ? "활성" : "비활성"}</dd>
        <dt>Stereo Phase</dt><dd>{health.phase_analysis_enabled ? "활성" : "비활성"}</dd>
        <dt>미터 스트림</dt><dd>{health.meter_stream_enabled ? "활성" : "비활성"}</dd>
      </dl>
    {:else}
      <p>로딩 중…</p>
    {/if}
  </section>

  <section class="card">
    <h2>
      룰 토글
      <span class="hint-inline">— service 도중 즉시 켜고 끔(재시작 불필요)</span>
    </h2>
    {#if rulesError}
      <p class="error">오류: {rulesError}</p>
    {/if}
    {#if rules.length === 0}
      <p class="hint">로딩 중…</p>
    {:else}
      <div class="rule-toggles">
        {#each rules as rule (rule.name)}
          <label class="rule-row" class:active={rule.enabled}>
            <input
              type="checkbox"
              checked={rule.enabled}
              disabled={rulesBusy.has(rule.name)}
              onchange={() => toggleRule(rule)}
            />
            <span class="rule-name">{ruleLabel(rule.name)}</span>
            <span class="rule-state">{rule.enabled ? "활성" : "비활성"}</span>
          </label>
        {/each}
      </div>
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
      <p class="hint">
        편집은 즉시 <code>config/channels.yaml</code>에 저장되고, *라이브
        처리 루프*도 다음 frame부터 즉시 반영됩니다 (재시작 불필요).
      </p>
      <table class="channel-map">
        <thead>
          <tr>
            <th>ch</th>
            <th>카테고리</th>
            <th>라벨</th>
            <th>stereo</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {#each channelMap as entry (entry.channel)}
            {#if editingChannel === entry.channel}
              <tr class="editing">
                <td class="ch-num">ch{String(entry.channel).padStart(2, "0")}</td>
                <td class="ch-category">
                  <select bind:value={editCategory}>
                    {#each CATEGORIES as cat (cat)}
                      <option value={cat}>{categoryLabel(cat)}</option>
                    {/each}
                  </select>
                </td>
                <td class="ch-label">
                  <input
                    type="text"
                    bind:value={editLabel}
                    placeholder="라벨"
                    disabled={editSaving}
                  />
                </td>
                <td class="ch-pair">
                  <input
                    type="text"
                    bind:value={editPair}
                    placeholder="페어 ch (비우면 mono)"
                    disabled={editSaving}
                    inputmode="numeric"
                  />
                </td>
                <td class="ch-actions">
                  <button
                    class="btn-save"
                    onclick={saveEdit}
                    disabled={editSaving}
                  >{editSaving ? "저장 중…" : "저장"}</button>
                  <button
                    class="btn-cancel"
                    onclick={cancelEdit}
                    disabled={editSaving}
                  >취소</button>
                </td>
              </tr>
              {#if editError}
                <tr><td colspan="5" class="edit-error">오류: {editError}</td></tr>
              {/if}
            {:else}
              <tr>
                <td class="ch-num">ch{String(entry.channel).padStart(2, "0")}</td>
                <td class="ch-category">
                  <span class="cat-pill cat-{entry.category}">{categoryLabel(entry.category)}</span>
                </td>
                <td class="ch-label">{entry.label || "—"}</td>
                <td class="ch-pair">
                  {#if entry.stereo_pair_with}
                    <span class="pair-pill">↔ ch{String(entry.stereo_pair_with).padStart(2, "0")}</span>
                  {:else}
                    <span class="pair-mono">—</span>
                  {/if}
                </td>
                <td class="ch-actions">
                  <button class="btn-edit" onclick={() => startEdit(entry)}>편집</button>
                </td>
              </tr>
            {/if}
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

  <section class="card">
    <h2>
      채널 시계열
      <span class="hint-inline">— RMS·Peak dBFS, 최대 2분 누적</span>
    </h2>
    {#if meterChannels.length === 0}
      <p class="hint">미터 스트림이 시작되면 채널을 선택할 수 있습니다.</p>
    {:else}
      <div class="ts-controls">
        <select
          class="ts-select"
          bind:value={selectedTimeseriesChannel}
        >
          {#each meterChannels as ch (ch.channel)}
            <option value={ch.channel}>
              ch{String(ch.channel).padStart(2, "0")} — {ch.label || ch.category}
            </option>
          {/each}
        </select>
        <div class="filter-group" role="group" aria-label="윈도우">
          {#each [30, 60, 120] as sec (sec)}
            <button
              class="filter-btn"
              class:active={timeseriesWindowSec === sec}
              onclick={() => (timeseriesWindowSec = sec)}
            >{sec}s</button>
          {/each}
        </div>
      </div>
      {#if selectedTimeseriesChannel !== null}
        {@const sel = meterChannels.find((c) => c.channel === selectedTimeseriesChannel)}
        <Timeseries
          channel={selectedTimeseriesChannel}
          label={sel?.label ?? ""}
          points={meterHistory.get(selectedTimeseriesChannel) ?? []}
          windowSeconds={timeseriesWindowSec}
        />
      {/if}
    {/if}
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
      {#if unreadRecCount > 0}
        <span class="unread-badge" title="미확인 추천 — 확인 버튼으로 리셋">
          새 알림 {unreadRecCount}건
        </span>
      {/if}
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
        class="ack-btn"
        disabled={unreadRecCount === 0}
        onclick={acknowledgeRecommendations}
        title="새 알림 카운트를 0으로 — 추천 자체는 유지"
      >확인 ({unreadRecCount})</button>
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
          <li
            class="rec rec--{rec.kind}"
            class:rec--new={isRecNewlyArrived(rec)}
            class:rec--unack={rec.receivedAt > lastAckedAt}
          >
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

  /* 운영 모드 토글 (상태 카드 안) */
  .mode-cell {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  .mode-toggle {
    display: inline-flex;
    gap: 0;
    border: 1px solid #2a2f39;
    border-radius: 0.25rem;
    overflow: hidden;
    width: fit-content;
  }
  .mode-toggle.locked {
    opacity: 0.5;
  }
  .mode-btn {
    background: #1a1d24;
    color: #8b95a3;
    border: none;
    border-right: 1px solid #2a2f39;
    padding: 0.3rem 0.7rem;
    font-size: 0.75rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    cursor: pointer;
    transition: background 0.1s, color 0.1s;
  }
  .mode-btn:last-child {
    border-right: none;
  }
  .mode-btn:hover:not(:disabled):not(.active) {
    background: #232730;
    color: #c8cdd6;
  }
  .mode-btn.active {
    background: #1e3a5f;
    color: #aac4ff;
  }
  .mode-btn:disabled {
    cursor: not-allowed;
  }
  .kill-active {
    color: #ff9a9a;
    font-size: 0.75rem;
  }
  .error-inline {
    color: #ff7676;
    font-size: 0.75rem;
  }

  /* 채널 시계열 카드 */
  .ts-controls {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
    flex-wrap: wrap;
  }
  .ts-select {
    background: #1a1d24;
    color: #c8cdd6;
    border: 1px solid #2a2f39;
    border-radius: 0.25rem;
    padding: 0.3rem 0.55rem;
    font-size: 0.85rem;
    font-family: inherit;
    min-width: 14rem;
  }
  .ts-select:focus {
    outline: none;
    border-color: #2a4a73;
  }

  /* 룰 토글 카드 */
  .rule-toggles {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
    gap: 0.4rem;
  }
  .rule-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.7rem;
    background: #1f232b;
    border: 1px solid #2a2f39;
    border-radius: 0.25rem;
    cursor: pointer;
    transition: background 0.1s, border-color 0.1s;
    font-size: 0.85rem;
  }
  .rule-row:hover {
    background: #232730;
  }
  .rule-row.active {
    border-color: #2a4a73;
    background: #1e2a3a;
  }
  .rule-row input[type="checkbox"] {
    margin: 0;
    accent-color: #6c8cff;
    cursor: pointer;
  }
  .rule-row input[type="checkbox"]:disabled {
    opacity: 0.5;
    cursor: wait;
  }
  .rule-name {
    flex: 1;
    color: #c8cdd6;
  }
  .rule-state {
    color: #5a6270;
    font-size: 0.75rem;
    font-variant-numeric: tabular-nums;
  }
  .rule-row.active .rule-state {
    color: #aac4ff;
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
  .ch-pair {
    width: 7rem;
    font-size: 0.8rem;
  }
  .pair-pill {
    display: inline-block;
    padding: 0.1rem 0.45rem;
    border-radius: 999px;
    background: #1e3a5f;
    color: #aac4ff;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.75rem;
  }
  .pair-mono {
    color: #5a6270;
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
  .ch-actions {
    width: 7rem;
    text-align: right;
  }
  .btn-edit,
  .btn-cancel,
  .btn-save {
    background: transparent;
    color: #8b95a3;
    border: 1px solid #2a2f39;
    padding: 0.2rem 0.5rem;
    border-radius: 0.2rem;
    font-size: 0.75rem;
    cursor: pointer;
    font-family: inherit;
  }
  .btn-edit:hover:not(:disabled),
  .btn-cancel:hover:not(:disabled) {
    background: #2a2f39;
    color: #c8cdd6;
  }
  .btn-save {
    background: #1e3a5f;
    color: #aac4ff;
    border-color: #2a4a73;
    margin-right: 0.25rem;
  }
  .btn-save:hover:not(:disabled) {
    background: #2a4a73;
  }
  .btn-save:disabled,
  .btn-cancel:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  tr.editing {
    background: #1f232b;
  }
  tr.editing select,
  tr.editing input[type="text"] {
    background: #1a1d24;
    color: #e6e8eb;
    border: 1px solid #2a4a73;
    border-radius: 0.2rem;
    padding: 0.2rem 0.4rem;
    font-size: 0.8rem;
    font-family: inherit;
    width: 100%;
    box-sizing: border-box;
  }
  tr.editing input[type="text"]:focus,
  tr.editing select:focus {
    outline: none;
    border-color: #6c8cff;
  }
  .edit-error {
    color: #ff7676;
    font-size: 0.8rem;
    padding: 0.25rem 0.5rem;
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
  .clear-btn,
  .ack-btn {
    background: transparent;
    color: #8b95a3;
    border: 1px solid #2a2f39;
    padding: 0.3rem 0.65rem;
    border-radius: 0.25rem;
    font-size: 0.8rem;
    cursor: pointer;
    transition: background 0.1s, color 0.1s;
  }
  .clear-btn:hover:not(:disabled),
  .ack-btn:hover:not(:disabled) {
    background: #2a2f39;
    color: #c8cdd6;
  }
  .clear-btn:disabled,
  .ack-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .ack-btn:not(:disabled) {
    color: #ffcc88;
    border-color: #6a4a1f;
    background: #2a1f0d;
  }
  .ack-btn:not(:disabled):hover {
    background: #3a2912;
  }

  .unread-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.2rem 0.55rem;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 600;
    background: #4a2f0d;
    color: #ffd093;
    border: 1px solid #6a4a1f;
    margin-left: 0.5rem;
    animation: badge-pulse 1.4s ease-in-out infinite;
  }
  @keyframes badge-pulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(255, 204, 136, 0.0); }
    50% { box-shadow: 0 0 0 4px rgba(255, 204, 136, 0.18); }
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
  .rec--unack {
    background: #2a2f3b;
  }
  .rec--new {
    animation: rec-flash 1.0s ease-out;
  }
  .rec--new.rec--feedback_alert {
    animation: rec-flash-alert 1.0s ease-out;
  }
  @keyframes rec-flash {
    0% { background: #2a3a5a; box-shadow: 0 0 0 0 rgba(108, 140, 255, 0.5); }
    100% { background: #2a2f3b; box-shadow: 0 0 0 0 rgba(108, 140, 255, 0); }
  }
  @keyframes rec-flash-alert {
    0% { background: #4a2424; box-shadow: 0 0 0 0 rgba(255, 118, 118, 0.6); }
    100% { background: #2a2f3b; box-shadow: 0 0 0 0 rgba(255, 118, 118, 0); }
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
