<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import {
    fetchHealth,
    subscribeRecommendations,
    type HealthResponse,
    type RecommendationPayload,
  } from "./lib/api";

  let health = $state<HealthResponse | null>(null);
  let healthError = $state<string | null>(null);
  let recommendations = $state<RecommendationPayload[]>([]);
  let streamConnected = $state(false);

  const MAX_VISIBLE_RECS = 50;

  let unsubscribe: (() => void) | null = null;

  onMount(async () => {
    try {
      health = await fetchHealth();
    } catch (e) {
      healthError = String(e);
    }

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
  });

  onDestroy(() => {
    if (unsubscribe) unsubscribe();
  });

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
      </dl>
    {:else}
      <p>로딩 중…</p>
    {/if}
  </section>

  <section class="card">
    <h2>
      추천 스트림
      <span class="stream-status" class:connected={streamConnected}>
        {streamConnected ? "수신 중" : "대기"}
      </span>
    </h2>
    {#if recommendations.length === 0}
      <p class="hint">
        아직 추천 없음. <code>MIXPILOT_AUDIO__ENABLED=true</code>로 캡처를 켜야
        분석이 시작됩니다.
      </p>
    {:else}
      <ul class="rec-list">
        {#each recommendations as rec, i (i)}
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
</style>
