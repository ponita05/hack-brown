// frontend/src/pages/VideoChat.tsx
import { useState, useRef, useCallback, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Header } from '@/components/landing/Header';
import {
  Video,
  VideoOff,
  Camera,
  Loader2,
  Maximize2,
  Minimize2,
  Play,
  Pause,
  BookOpen,
  CheckCircle2,
  RotateCcw,
  AlertTriangle,
  ListChecks,
} from 'lucide-react';
import { toast } from 'sonner';

interface ProspectedIssue {
  rank: number;
  issue_name: string;
  suspected_cause: string;
  confidence: number;
  symptoms_match: string[];
  category: string;
}

interface HomeIssueAnalysis {
  no_issue_detected?: boolean;
  human_detected?: boolean;
  repair_pending?: boolean;

  prospected_issues: ProspectedIssue[];
  overall_danger_level: 'low' | 'medium' | 'high';
  location: string;
  fixture: string;
  observed_symptoms: string[];
  requires_shutoff: boolean;
  water_present: boolean;
  immediate_action: string;
  professional_needed: boolean;
}

type SendResultReason =
  | 'ok'
  | 'busy'
  | 'video-not-ready'
  | 'no-frame'
  | 'throttled'
  | 'duplicate'
  | 'skipped'
  | 'failed'
  | 'network';

type SendResult = { ok: boolean; reason: SendResultReason; ms?: number };

interface RagCitation {
  rank: number;
  score: number | null;
  text: string;
  source: string;
}

interface RagSolutionResponse {
  success: boolean;
  session_id: string;
  query?: string;
  citations?: RagCitation[];
  solution?: string;
  error?: string;
}

// ✅ Guided Fix types
type GuideOutcome =
  | 'done'
  | 'still'
  | 'flushed_again'
  | 'reset'
  | 'danger'
  | 'skip';

interface GuideStep {
  step_id: number;
  title: string;
  instruction: string;
  safety_note?: string | null;
  check_hint?: string | null;
  is_danger_step: boolean;
}

interface GuideState {
  plan_id: string;
  current_step: number;
  completed_steps: number[];
  failed_attempts: Record<string, number>;
  last_updated: number;
  status: 'active' | 'done' | 'paused';

  active?: boolean;
  focus?: {
    fixture?: string;
    location?: string;
    issue_name?: string;
    category?: string;
  };
  interrupt?: {
    active: boolean;
    level: 'medium' | 'high';
    message: string;
    requires_shutoff: boolean;
    created_at: number;
  };
}

interface GuideInitResponse {
  success: boolean;
  session_id: string;
  plan_id: string;
  steps: GuideStep[];
  state: GuideState;
  selected_reason: string;
  error?: string;
}

interface GuideNextResponse {
  success: boolean;
  session_id: string;
  plan_id: string;
  steps: GuideStep[];
  state: GuideState;
  current_step_obj?: GuideStep | null;
  message: string;
  error?: string;
}

type GuideOverlay = null | {
  active: boolean;
  type: 'interrupt' | 'step' | 'done';
  level: 'medium' | 'high';
  message: string;
  title?: string;
  safety_note?: string | null;
  check_hint?: string | null;
  requires_shutoff?: boolean;
  plan_id: string;
  focus?: {
    fixture?: string;
    location?: string;
    issue_name?: string;
    category?: string;
  };
  status: 'active' | 'done' | 'paused';
  current_step: number;
  total_steps: number;
};

const BACKEND_URL = 'http://127.0.0.1:8000';
const SESSION_ID = 'demo-session-1';

const AUTO_CAPTURE_INTERVAL_MS = 350;
const CLIENT_MIN_GAP_MS = 900;

const MANUAL_WAIT_POLL_MS = 120;
const TOAST_COOLDOWN_MS = 1500;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function VideoChat() {
  const [isVideoActive, setIsVideoActive] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // ✅ first analysis gate
  const [hasFirstAnalysis, setHasFirstAnalysis] = useState(false);

  // backend /frame
  const [manualCaptureLoading, setManualCaptureLoading] = useState(false);
  const [autoCapture, setAutoCapture] = useState(false);
  const [latestAnalysis, setLatestAnalysis] =
    useState<HomeIssueAnalysis | null>(null);

  // ✅ RAG
  const [solutionLoading, setSolutionLoading] = useState(false);
  const [finalSolution, setFinalSolution] = useState<string | null>(null);
  const [citations, setCitations] = useState<RagCitation[]>([]);
  const [ragQuery, setRagQuery] = useState<string>('');

  // ✅ Guided Fix
  const [guideLoading, setGuideLoading] = useState(false);
  const [guidePlanId, setGuidePlanId] = useState<string | null>(null);
  const [guideSteps, setGuideSteps] = useState<GuideStep[]>([]);
  const [guideState, setGuideState] = useState<GuideState | null>(null);
  const [guideMessage, setGuideMessage] = useState<string>('');

  // backend overlay
  const [guideOverlay, setGuideOverlay] = useState<GuideOverlay>(null);

  // refs
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // loop refs
  const inFlightRef = useRef(false);
  const stopLoopRef = useRef(false);
  const loopStartedRef = useRef(false);
  const lastToastAtRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const lastClientSendAtRef = useRef(0);
  const prevHadIssueRef = useRef<boolean | null>(null);

  const startVideo = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: 'user',
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
      });

      if (!videoRef.current) return;

      videoRef.current.srcObject = stream;
      streamRef.current = stream;

      await videoRef.current.play();

      setHasFirstAnalysis(false);
      setLatestAnalysis(null);
      setGuideOverlay(null);

      setIsVideoActive(true);
      toast.success('Camera started! Point at your issue.');
    } catch (error) {
      console.error('❌ startVideo error:', error);
      toast.error('Could not access camera. Please check permissions.');
    }
  }, []);

  const stopVideo = useCallback(() => {
    stopLoopRef.current = true;
    loopStartedRef.current = false;

    abortRef.current?.abort();
    abortRef.current = null;

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    setAutoCapture(false);
    setIsVideoActive(false);

    setGuideOverlay(null);
    setLatestAnalysis(null);
    setHasFirstAnalysis(false);

    // guided + rag reset
    setGuidePlanId(null);
    setGuideSteps([]);
    setGuideState(null);
    setGuideMessage('');
    setFinalSolution(null);
    setCitations([]);
    setRagQuery('');

    prevHadIssueRef.current = null;
  }, []);

  const captureFrame = useCallback((): string | null => {
    if (!videoRef.current || !canvasRef.current) return null;

    const video = videoRef.current;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;

    if (!video.videoWidth || !video.videoHeight) return null;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    ctx.drawImage(video, 0, 0);

    return canvas.toDataURL('image/jpeg', 0.8);
  }, []);

  const sendFrameToBackend = useCallback(
    async (showToast: boolean = true): Promise<SendResult> => {
      if (inFlightRef.current) return { ok: false, reason: 'busy' };

      const nowMs = Date.now();
      if (nowMs - lastClientSendAtRef.current < CLIENT_MIN_GAP_MS) {
        return { ok: false, reason: 'throttled' };
      }

      if (!videoRef.current || videoRef.current.readyState < 2) {
        return { ok: false, reason: 'video-not-ready' };
      }

      const dataUrl = captureFrame();
      if (!dataUrl) return { ok: false, reason: 'no-frame' };

      inFlightRef.current = true;
      lastClientSendAtRef.current = nowMs;

      const t0 = performance.now();

      try {
        const blobResp = await fetch(dataUrl);
        const blob = await blobResp.blob();

        const formData = new FormData();
        formData.append('image', blob, 'frame.jpg');
        formData.append('session_id', SESSION_ID);

        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;

        const res = await fetch(`${BACKEND_URL}/frame`, {
          method: 'POST',
          body: formData,
          signal: controller.signal,
        });

        const ms = performance.now() - t0;

        if (!res.ok) {
          const text = await res.text().catch(() => '');
          console.error(`[frame] ✗ HTTP ${res.status}`, text);
          return { ok: false, reason: 'failed', ms };
        }

        const result = await res.json().catch(() => null);

        if (result?.success && result?.data) {
          const analysis: HomeIssueAnalysis = result.data;
          setLatestAnalysis(analysis);
          setHasFirstAnalysis(true);

          setGuideOverlay((result?.guide_overlay ?? null) as GuideOverlay);

          const isNoIssue = analysis?.no_issue_detected === true;
          const hadIssueNow = !isNoIssue;

          const prevHadIssue = prevHadIssueRef.current;
          prevHadIssueRef.current = hadIssueNow;

          const topIssue =
            analysis.prospected_issues?.[0]?.issue_name || 'Issue detected';

          if (showToast) {
            const now = Date.now();
            if (now - lastToastAtRef.current > TOAST_COOLDOWN_MS) {
              if (prevHadIssue === true && isNoIssue) {
                toast.success('✅ Resolved — looks fixed.');
              } else if (isNoIssue) {
                toast.success('✅ Looks good — no issue detected.');
              } else {
                toast.success(`🔎 Issue detected: ${topIssue}`);
              }
              lastToastAtRef.current = now;
            }
          }

          return { ok: true, reason: 'ok', ms };
        }

        if (result?.skipped) {
          const reason = String(result.reason || 'skipped');
          if (reason === 'throttled')
            return { ok: false, reason: 'throttled', ms };
          if (reason === 'duplicate')
            return { ok: false, reason: 'duplicate', ms };
          if (reason === 'busy') return { ok: false, reason: 'busy', ms };
          return { ok: false, reason: 'skipped', ms };
        }

        return { ok: false, reason: 'failed', ms };
      } catch (error: any) {
        const ms = performance.now() - t0;

        if (error?.name === 'AbortError') {
          return { ok: false, reason: 'skipped', ms };
        }
        console.error('[frame] ✗ network', error);
        return { ok: false, reason: 'network', ms };
      } finally {
        inFlightRef.current = false;
      }
    },
    [captureFrame],
  );

  useEffect(() => {
    if (!autoCapture || !isVideoActive) {
      stopLoopRef.current = true;
      loopStartedRef.current = false;
      return;
    }

    if (loopStartedRef.current) return;

    stopLoopRef.current = false;
    loopStartedRef.current = true;

    const run = async () => {
      while (!stopLoopRef.current && autoCapture && isVideoActive) {
        const r = await sendFrameToBackend(true);

        let waitMs = AUTO_CAPTURE_INTERVAL_MS;

        if (!r.ok) {
          if (r.reason === 'busy') waitMs = 300;
          else if (r.reason === 'duplicate') waitMs = 700;
          else if (r.reason === 'throttled') waitMs = 700;
          else if (r.reason === 'network') {
            waitMs = 1200;
            const now = Date.now();
            if (now - lastToastAtRef.current > 3000) {
              toast.error('Cannot connect to backend.');
              lastToastAtRef.current = now;
            }
          } else {
            waitMs = 500;
          }
        }

        await sleep(waitMs);
      }
      loopStartedRef.current = false;
    };

    run();

    return () => {
      stopLoopRef.current = true;
      loopStartedRef.current = false;
    };
  }, [autoCapture, isVideoActive, sendFrameToBackend]);

  const handleManualCapture = async () => {
    setManualCaptureLoading(true);

    setFinalSolution(null);
    setCitations([]);
    setRagQuery('');

    while (inFlightRef.current) {
      await sleep(MANUAL_WAIT_POLL_MS);
    }

    const r = await sendFrameToBackend(false);

    if (r.ok) {
      const a = latestAnalysis;
      await sleep(10);
      const a2 = latestAnalysis ?? a;

      const isNoIssue = a2?.no_issue_detected === true;
      const topIssue =
        a2?.prospected_issues?.[0]?.issue_name || 'Issue detected';

      if (isNoIssue) toast.success('✅ Looks good — no issue detected.');
      else toast.success(`🔎 Issue detected: ${topIssue}`);
    } else {
      if (r.reason === 'network') toast.error('Backend not reachable.');
      else if (r.reason === 'video-not-ready')
        toast.error('Video not ready yet.');
      else if (r.reason === 'no-frame') toast.error('Could not capture frame.');
      else toast.error('Analysis failed. Try steady + better lighting.');
    }

    setManualCaptureLoading(false);
  };

  const fetchRagSolution = async () => {
    setSolutionLoading(true);
    try {
      const res = await fetch(`${BACKEND_URL}/solution`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: SESSION_ID }),
      });

      const data: RagSolutionResponse = await res.json().catch(() => ({
        success: false,
        session_id: SESSION_ID,
        error: 'Invalid JSON from backend',
      }));

      if (!res.ok || !data.success) {
        toast.error(data.error || `Solution failed (${res.status})`);
        return;
      }

      setFinalSolution(data.solution || '(no solution text)');
      setCitations(data.citations || []);
      setRagQuery(data.query || '');

      toast.success('Generated RAG solution!');
    } catch (e) {
      console.error('❌ fetchRagSolution error:', e);
      toast.error('Cannot reach backend /solution');
    } finally {
      setSolutionLoading(false);
    }
  };

  // ==========================================================
  // ✅ Guided Fix
  // ==========================================================
  const startGuidedFix = async () => {
    if (latestAnalysis?.no_issue_detected === true) {
      toast.error('No issue detected in the latest frame.');
      return;
    }

    setGuideLoading(true);
    try {
      const res = await fetch(`${BACKEND_URL}/guide/init`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: SESSION_ID }),
      });

      const data: GuideInitResponse = await res.json().catch(() => ({
        success: false,
        session_id: SESSION_ID,
        plan_id: '',
        steps: [],
        state: null as any,
        selected_reason: '',
        error: 'Invalid JSON from backend',
      }));

      if (!res.ok || !data.success) {
        toast.error(data.error || `Guide init failed (${res.status})`);
        return;
      }

      setGuidePlanId(data.plan_id);
      setGuideSteps(data.steps || []);
      setGuideState(data.state);
      setGuideMessage(`Guide started (${data.selected_reason})`);

      const cur = data.steps?.[(data.state?.current_step || 1) - 1];
      setGuideOverlay(
        cur
          ? {
              active: true,
              type: data.state?.status === 'done' ? 'done' : 'step',
              level: cur.is_danger_step ? 'high' : 'medium',
              message: cur.instruction,
              title: cur.title,
              safety_note: cur.safety_note ?? null,
              check_hint: cur.check_hint ?? null,
              plan_id: data.plan_id,
              focus: data.state?.focus,
              status: data.state?.status || 'active',
              current_step: data.state?.current_step || 1,
              total_steps: data.steps?.length || 0,
            }
          : null,
      );

      toast.success('Guided Fix started!');
    } catch (e) {
      console.error('❌ startGuidedFix error:', e);
      toast.error('Cannot reach backend /guide/init');
    } finally {
      setGuideLoading(false);
    }
  };

  const guideNext = async (outcome: GuideOutcome) => {
    setGuideLoading(true);
    try {
      const res = await fetch(`${BACKEND_URL}/guide/next`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: SESSION_ID, outcome }),
      });

      const data: GuideNextResponse = await res.json().catch(() => ({
        success: false,
        session_id: SESSION_ID,
        plan_id: '',
        steps: [],
        state: null as any,
        current_step_obj: null,
        message: '',
        error: 'Invalid JSON from backend',
      }));

      if (!res.ok || !data.success) {
        toast.error(data.error || `Guide update failed (${res.status})`);
        return;
      }

      setGuidePlanId(data.plan_id);
      setGuideSteps(data.steps || []);
      setGuideState(data.state);
      setGuideMessage(data.message || '');

      const st = data.state;
      const steps = data.steps || [];
      const idx = Math.max(
        0,
        Math.min((st?.current_step || 1) - 1, steps.length - 1),
      );
      const cur = st?.status === 'done' ? null : steps[idx];

      if (st?.status === 'done') {
        setGuideOverlay({
          active: true,
          type: 'done',
          level: 'medium',
          message:
            '✅ Guided Fix completed. If it still doesn’t work, escalate to maintenance/plumber.',
          plan_id: data.plan_id,
          focus: st?.focus,
          status: st.status,
          current_step: st.current_step,
          total_steps: steps.length,
        });
      } else if (cur) {
        setGuideOverlay({
          active: true,
          type: st?.status === 'paused' ? 'interrupt' : 'step',
          level: cur.is_danger_step ? 'high' : 'medium',
          message: cur.instruction,
          title: cur.title,
          safety_note: cur.safety_note ?? null,
          check_hint: cur.check_hint ?? null,
          plan_id: data.plan_id,
          focus: st?.focus,
          status: st?.status || 'active',
          current_step: st?.current_step || 1,
          total_steps: steps.length,
        });
      }

      toast.success(data.message || 'Updated!');
    } catch (e) {
      console.error('❌ guideNext error:', e);
      toast.error('Cannot reach backend /guide/next');
    } finally {
      setGuideLoading(false);
    }
  };

  const resetGuidedFix = async () => {
    setGuideLoading(true);
    try {
      const res = await fetch(`${BACKEND_URL}/guide/reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: SESSION_ID }),
      });

      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.success) {
        toast.error(data?.error || `Guide reset failed (${res.status})`);
        return;
      }
      setGuidePlanId(null);
      setGuideSteps([]);
      setGuideState(null);
      setGuideMessage('Guide reset.');
      setGuideOverlay(null);
      toast.success('Guide reset!');
    } catch (e) {
      console.error('❌ resetGuidedFix error:', e);
      toast.error('Cannot reach backend /guide/reset');
    } finally {
      setGuideLoading(false);
    }
  };

  const getCurrentGuideStep = (): GuideStep | null => {
    if (!guideState || guideSteps.length === 0) return null;
    const idx = Math.max(
      0,
      Math.min(guideState.current_step - 1, guideSteps.length - 1),
    );
    return guideSteps[idx] || null;
  };

  // Text-to-Speech function
  const playVoiceMessage = async (text: string) => {
    try {
      const response = await fetch(`${BACKEND_URL}/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });

      const contentType = response.headers.get('content-type') || '';

      if (!response.ok) {
        const errText = await response.text().catch(() => '');
        console.error('TTS failed HTTP:', response.status, errText);
        return;
      }

      if (!contentType.includes('audio')) {
        const body = await response.text().catch(() => '');
        console.error('TTS returned non-audio:', contentType, body);
        return;
      }

      const audioBlob = await response.blob();
      const audioUrl = URL.createObjectURL(audioBlob);

      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }

      const audio = new Audio(audioUrl);
      audioRef.current = audio;

      await audio.play(); // <-- 여기서 자동재생 막히면 NotAllowedError 뜸

      audio.onended = () => URL.revokeObjectURL(audioUrl);
    } catch (error) {
      console.warn('Voice playback skipped:', error);
    }
  };

  const curStep = getCurrentGuideStep();

  // Three-state categorization logic
  const analysisState = (() => {
    if (!latestAnalysis) return null;

    if (latestAnalysis.no_issue_detected === true) {
      return 'success'; // Green
    }

    if (
      latestAnalysis.human_detected === true &&
      latestAnalysis.repair_pending === true
    ) {
      return 'pending'; // Blue - NEW STATE
    }

    return 'error'; // Red
  })();

  const isLatestNoIssue = analysisState === 'success';
  const isRepairPending = analysisState === 'pending';
  const hasErrors = analysisState === 'error';

  // Voice feedback effect - plays audio when state changes
  useEffect(() => {
    if (!latestAnalysis || !hasFirstAnalysis) return;

    const topIssue =
      latestAnalysis.prospected_issues?.[0]?.issue_name || 'issue';
    const dangerLevel = latestAnalysis.overall_danger_level;
    const immediateAction = latestAnalysis.immediate_action;

    let message = '';

    if (analysisState === 'success') {
      message = 'All clear! No issues detected. Everything looks good.';
    } else if (analysisState === 'pending') {
      message = `I see you're working on it. The ${topIssue} is still present. Keep going!`;
    } else if (analysisState === 'error') {
      if (dangerLevel === 'high') {
        message = `Attention! I detected ${topIssue}. This requires immediate action. ${immediateAction}`;
      } else if (dangerLevel === 'medium') {
        message = `I've spotted ${topIssue}. You should address this soon. ${immediateAction}`;
      } else {
        message = `I found ${topIssue}. ${immediateAction}`;
      }
    }

    if (message) {
      playVoiceMessage(message);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisState, hasFirstAnalysis]);

  // ✅ overlay: backend overlay 우선, 아니면 guideState/analysis로 생성
  const computedOverlay: GuideOverlay = (() => {
    if (guideOverlay?.active) return guideOverlay;

    if (guideState && curStep && guidePlanId) {
      return {
        active: true,
        type: guideState.status === 'done' ? 'done' : 'step',
        level: curStep.is_danger_step ? 'high' : 'medium',
        message:
          guideState.status === 'done'
            ? '✅ Guided Fix completed.'
            : curStep.instruction,
        title: guideState.status === 'done' ? 'Completed' : curStep.title,
        safety_note: curStep.safety_note ?? null,
        check_hint: curStep.check_hint ?? null,
        plan_id: guidePlanId,
        focus: guideState.focus,
        status: guideState.status,
        current_step: guideState.current_step,
        total_steps: guideSteps.length,
      };
    }

    if (isVideoActive && latestAnalysis && !isLatestNoIssue) {
      const top = latestAnalysis.prospected_issues?.[0];
      const level: 'medium' | 'high' =
        latestAnalysis.overall_danger_level === 'high' ? 'high' : 'medium';

      return {
        active: true,
        type: 'step',
        level,
        title: 'Guided Fix Ready',
        message: top
          ? `Likely issue: ${top.issue_name}\nScroll down for details and start step-by-step.`
          : `Scroll down for details and start step-by-step.`,
        safety_note: latestAnalysis.requires_shutoff
          ? 'Turn off water if leaking/overflow risk.'
          : null,
        check_hint: 'Keep camera steady + good lighting.',
        plan_id: guidePlanId || 'pre-guide',
        focus: {
          fixture: latestAnalysis.fixture,
          location: latestAnalysis.location,
          category: top?.category,
          issue_name: top?.issue_name,
        },
        status: 'active',
        current_step: 1,
        total_steps: guideSteps.length || 0,
      };
    }

    // NEW: Repair pending state (human detected with issues)
    if (isVideoActive && latestAnalysis && isRepairPending) {
      const top = latestAnalysis.prospected_issues?.[0];
      return {
        active: true,
        type: 'step',
        level: 'medium',
        title: 'Human Detected - Repair Pending',
        message: top
          ? `Issue: ${top.issue_name}\n\nHuman is present. Continue working on repairs or start guided fix below.`
          : `Human detected. There are items that need repair. Scroll down for details.`,
        safety_note: latestAnalysis.requires_shutoff
          ? 'Turn off water if leaking/overflow risk.'
          : null,
        check_hint: 'Keep camera steady for continuous monitoring.',
        plan_id: guidePlanId || 'pending-repair',
        focus: {
          fixture: latestAnalysis.fixture,
          location: latestAnalysis.location,
          category: top?.category,
          issue_name: top?.issue_name,
        },
        status: 'active',
        current_step: 0,
        total_steps: guideSteps.length || 0,
      };
    }

    if (isVideoActive && latestAnalysis && isLatestNoIssue) {
      return {
        active: true,
        type: 'done',
        level: 'medium',
        title: 'All Good',
        message:
          '✅ No issue detected. Move closer if you still suspect a bug.',
        safety_note: null,
        check_hint: 'Keep camera steady.',
        plan_id: 'idle',
        focus: {
          fixture: latestAnalysis.fixture,
          location: latestAnalysis.location,
        },
        status: 'done',
        current_step: 0,
        total_steps: 0,
      };
    }

    return null;
  })();

  const overlayToShow = computedOverlay;

  const overlayIsSolved =
    overlayToShow?.type === 'done' ||
    (hasFirstAnalysis && latestAnalysis?.no_issue_detected === true);
  const overlayIsHigh = overlayToShow?.level === 'high';

  const showGuideButtons =
    !!guideState &&
    overlayToShow?.type !== 'done' &&
    guideState.status !== 'done';

  const overlayBg = overlayIsSolved
    ? 'bg-green-500/25 border-green-500/40'
    : isRepairPending
      ? 'bg-blue-500/25 border-blue-500/40'
      : overlayIsHigh
        ? 'bg-red-500/25 border-red-500/40'
        : 'bg-orange-500/20 border-orange-500/35';

  const overlayText = overlayIsSolved
    ? 'text-green-50'
    : isRepairPending
      ? 'text-blue-50'
      : overlayIsHigh
        ? 'text-red-50'
        : 'text-orange-50';

  // =======================================================================
  // UI helpers for lower panel
  // =======================================================================
  const dangerBadge = (() => {
    if (!latestAnalysis) return null;

    if (isLatestNoIssue) {
      return (
        <span className="text-xs px-2 py-1 rounded-full bg-green-500/20 text-green-500">
          ✅ NORMAL
        </span>
      );
    }

    if (isRepairPending) {
      return (
        <span className="text-xs px-2 py-1 rounded-full bg-blue-500/20 text-blue-500">
          🔧 REPAIR PENDING
        </span>
      );
    }

    const lvl = latestAnalysis.overall_danger_level;
    const cls =
      lvl === 'high'
        ? 'bg-red-500/20 text-red-500'
        : lvl === 'medium'
          ? 'bg-yellow-500/20 text-yellow-500'
          : 'bg-green-500/20 text-green-500';
    return (
      <span className={`text-xs px-2 py-1 rounded-full ${cls}`}>
        ⚠️ {lvl.toUpperCase()}
      </span>
    );
  })();

  return (
    <div className="min-h-screen bg-background">
      <Header />

      {/* ===== HERO VIDEO AREA (전체를 감싸는 메인) ===== */}
      <main className="pt-20">
        <div className="px-3 sm:px-4">
          <div className="max-w-7xl mx-auto">
            <div
              className={[
                'relative rounded-2xl overflow-hidden shadow-card border border-border bg-primary',
                isFullscreen ? 'h-[calc(100vh-96px)]' : 'h-[70vh] sm:h-[72vh]',
              ].join(' ')}
            >
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className={`w-full h-full object-cover ${
                  isVideoActive ? '' : 'hidden'
                }`}
              />

              {/* Overlay */}
              {isVideoActive && overlayToShow?.active && (
                <div className="absolute top-4 right-4 w-[380px] max-w-[92%] z-30">
                  <div
                    className={`rounded-2xl border ${overlayBg} backdrop-blur-md p-4 shadow-lg`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className={`text-xs ${overlayText} opacity-90`}>
                          {overlayIsSolved
                            ? 'Status • Solved'
                            : `Guided Fix • Step ${overlayToShow.current_step}/${overlayToShow.total_steps}`}
                          {overlayToShow?.focus?.fixture
                            ? ` • ${overlayToShow.focus.fixture}`
                            : ''}
                        </div>

                        {overlayToShow.title && (
                          <div
                            className={`mt-1 text-sm font-semibold ${overlayText}`}
                          >
                            {overlayToShow.title}
                          </div>
                        )}

                        <div
                          className={`mt-2 text-sm ${overlayText} whitespace-pre-wrap`}
                        >
                          {overlayIsSolved
                            ? '✅ Everything looks normal now.'
                            : overlayToShow.message}
                        </div>

                        {overlayToShow.safety_note && (
                          <div
                            className={`mt-2 text-xs ${overlayText} opacity-95 whitespace-pre-wrap`}
                          >
                            ⚠️ {overlayToShow.safety_note}
                          </div>
                        )}

                        {overlayToShow.check_hint && (
                          <div
                            className={`mt-2 text-xs ${overlayText} opacity-80`}
                          >
                            Check: {overlayToShow.check_hint}
                          </div>
                        )}
                      </div>

                      {showGuideButtons && (
                        <div className="flex flex-col gap-2 shrink-0">
                          <Button
                            onClick={() => guideNext('done')}
                            disabled={guideLoading}
                            className="rounded-xl"
                          >
                            {guideLoading ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <CheckCircle2 className="w-4 h-4" />
                            )}
                            Done
                          </Button>

                          <Button
                            variant="secondary"
                            onClick={() => guideNext('still')}
                            disabled={guideLoading}
                            className="rounded-xl"
                          >
                            Still stuck
                          </Button>

                          <Button
                            variant="destructive"
                            onClick={() => guideNext('flushed_again')}
                            disabled={guideLoading}
                            className="rounded-xl"
                          >
                            Flushed again
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Top-left LIVE + Fullscreen */}
              <div className="absolute top-4 left-4 z-30 flex items-center gap-2">
                {isVideoActive && (
                  <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-destructive/90 text-destructive-foreground text-sm font-medium">
                    <span className="w-2 h-2 rounded-full bg-current animate-pulse-live" />
                    LIVE
                  </div>
                )}

                <Button
                  variant="secondary"
                  size="icon"
                  onClick={() => setIsFullscreen((v) => !v)}
                  className="rounded-full"
                >
                  {isFullscreen ? (
                    <Minimize2 className="w-4 h-4" />
                  ) : (
                    <Maximize2 className="w-4 h-4" />
                  )}
                </Button>
              </div>

              {/* Bottom controls */}
              {isVideoActive ? (
                <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-30 flex flex-wrap items-center justify-center gap-3">
                  <Button
                    variant={autoCapture ? 'default' : 'hero'}
                    size="lg"
                    onClick={() => setAutoCapture((v) => !v)}
                    className={
                      autoCapture ? 'bg-green-600 hover:bg-green-700' : ''
                    }
                  >
                    {autoCapture ? (
                      <>
                        <Pause className="w-5 h-5" />
                        Auto-Analyzing
                      </>
                    ) : (
                      <>
                        <Play className="w-5 h-5" />
                        Start Auto-Capture
                      </>
                    )}
                  </Button>

                  <Button
                    variant="secondary"
                    size="lg"
                    onClick={handleManualCapture}
                    disabled={manualCaptureLoading}
                  >
                    {manualCaptureLoading ? (
                      <Loader2 className="w-5 h-5 animate-spin" />
                    ) : (
                      <Camera className="w-5 h-5" />
                    )}
                    Manual Capture
                  </Button>

                  <Button
                    variant="destructive"
                    size="lg"
                    onClick={stopVideo}
                    className="rounded-xl"
                  >
                    <VideoOff className="w-5 h-5" />
                    Stop
                  </Button>
                </div>
              ) : (
                <div className="absolute inset-0 flex flex-col items-center justify-center text-primary-foreground p-8">
                  <div className="w-20 h-20 rounded-full bg-primary-foreground/10 flex items-center justify-center mb-6">
                    <Video className="w-10 h-10" />
                  </div>
                  <h3 className="text-xl font-semibold mb-2 text-center">
                    Start Camera
                  </h3>
                  <p className="text-primary-foreground/70 text-center mb-6 max-w-sm">
                    Point at the issue. Scroll down for Analysis + RAG.
                  </p>
                  <Button variant="hero" size="lg" onClick={startVideo}>
                    <Video className="w-5 h-5" />
                    Start Camera
                  </Button>
                </div>
              )}
            </div>
          </div>

          <div className="max-w-7xl mx-auto mt-6 pb-10">
            <div className="rounded-2xl bg-card border border-border overflow-hidden">
              <div className="px-5 py-4 border-b border-border flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-foreground">
                    Diagnostics Dashboard
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Scrollable panel • tips / analysis / rag
                  </div>
                </div>

                <div className="flex items-center gap-2">{dangerBadge}</div>
              </div>

              <div className="p-4 sm:p-5">
                <div className="grid gap-4 lg:grid-cols-3">
                  {/* LEFT: Tips */}
                  <section className="rounded-2xl border border-border bg-secondary/30 p-4">
                    <div className="text-sm font-semibold text-foreground mb-2">
                      Tips (Left)
                    </div>
                    <ul className="text-sm text-muted-foreground space-y-2">
                      <li>• Use bright lighting (phone flashlight is fine)</li>
                      <li>
                        • Move closer to the object (show details clearly)
                      </li>
                      <li>• Reduce camera shake (hold steady for 2 seconds)</li>
                      <li>
                        • Auto mode waits for a response before sending the next
                        frame and enforces a minimum interval
                      </li>
                      <li>
                        • Even if it says “no issue,” try again from a different
                        angle or distance if symptoms persist
                      </li>
                    </ul>

                    <div className="mt-4 pt-4 border-t border-border">
                      <div className="text-xs font-semibold text-foreground mb-2">
                        Quick actions
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="secondary"
                          className="rounded-xl"
                          onClick={() => {
                            setFinalSolution(null);
                            setCitations([]);
                            setRagQuery('');
                            toast.success('Cleared RAG output.');
                          }}
                          disabled={solutionLoading}
                        >
                          Clear RAG
                        </Button>

                        {!guideState ? (
                          <Button
                            className="rounded-xl"
                            onClick={startGuidedFix}
                            disabled={
                              guideLoading || isLatestNoIssue || !latestAnalysis
                            }
                          >
                            {guideLoading ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <Play className="w-4 h-4" />
                            )}
                            Start Guided Fix
                          </Button>
                        ) : (
                          <Button
                            variant="secondary"
                            className="rounded-xl"
                            onClick={resetGuidedFix}
                            disabled={guideLoading}
                          >
                            <RotateCcw className="w-4 h-4" />
                            Reset Guide
                          </Button>
                        )}
                      </div>

                      {!latestAnalysis && (
                        <div className="mt-3 text-xs text-muted-foreground">
                          If there’s no analysis yet, try Manual Capture once
                        </div>
                      )}
                    </div>
                  </section>

                  {/* CENTER: Analysis */}
                  <section className="rounded-2xl border border-border bg-card p-4">
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-sm font-semibold text-foreground">
                        Analysis (Center)
                      </div>
                      {dangerBadge}
                    </div>

                    {!latestAnalysis ? (
                      <div className="rounded-xl border border-border bg-muted/20 p-4 text-sm text-muted-foreground">
                        No analysis yet. Start camera → Manual Capture or Auto.
                      </div>
                    ) : isLatestNoIssue ? (
                      <div className="p-4 rounded-xl bg-green-500/10 border border-green-500/30 text-sm text-foreground">
                        ✅ No issue detected in the latest frame.
                        <div className="text-xs text-muted-foreground mt-1">
                          If you still have symptoms, move closer + better
                          lighting.
                        </div>
                      </div>
                    ) : isRepairPending ? (
                      <div className="p-4 rounded-xl bg-blue-500/10 border border-blue-500/30 text-sm text-foreground">
                        🔧 Human detected - Repairs in progress
                        <div className="text-xs text-muted-foreground mt-2">
                          System detected a person working on the fixture.
                          Issues are still present. Continue repairs or use
                          guided fix below.
                        </div>
                        <div className="mt-4">
                          {/* Show the issues like normal */}
                          <div className="space-y-2">
                            {(latestAnalysis.prospected_issues || [])
                              .slice(0, 3)
                              .map((issue) => (
                                <div
                                  key={issue.rank}
                                  className={`p-3 rounded-lg border ${
                                    issue.rank === 1
                                      ? 'bg-blue-500/10 border-blue-500/30'
                                      : issue.rank === 2
                                        ? 'bg-purple-500/10 border-purple-500/30'
                                        : 'bg-gray-500/10 border-gray-500/30'
                                  }`}
                                >
                                  <div className="flex items-start justify-between mb-1">
                                    <div className="flex items-center gap-2">
                                      <span
                                        className={`text-xs font-bold px-2 py-0.5 rounded ${
                                          issue.rank === 1
                                            ? 'bg-blue-500 text-white'
                                            : issue.rank === 2
                                              ? 'bg-purple-500 text-white'
                                              : 'bg-gray-500 text-white'
                                        }`}
                                      >
                                        #{issue.rank}
                                      </span>
                                      <span className="text-xs font-medium text-muted-foreground uppercase">
                                        {issue.category}
                                      </span>
                                    </div>
                                    <span className="text-xs font-semibold text-foreground">
                                      {Math.round(issue.confidence * 100)}%
                                      likely
                                    </span>
                                  </div>

                                  <div className="text-sm font-semibold text-foreground mb-1">
                                    {issue.issue_name}
                                  </div>
                                  <div className="text-xs text-muted-foreground">
                                    {issue.suspected_cause}
                                  </div>
                                </div>
                              ))}
                          </div>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="space-y-2 text-sm mb-3 pb-3 border-b border-border">
                          <div>
                            <span className="font-medium text-foreground">
                              Location:{' '}
                            </span>
                            <span className="text-muted-foreground">
                              {latestAnalysis.location}
                            </span>
                          </div>
                          <div>
                            <span className="font-medium text-foreground">
                              Fixture:{' '}
                            </span>
                            <span className="text-muted-foreground">
                              {latestAnalysis.fixture}
                            </span>
                          </div>
                          <div>
                            <span className="font-medium text-foreground">
                              Immediate Action:{' '}
                            </span>
                            <span className="text-muted-foreground">
                              {latestAnalysis.immediate_action}
                            </span>
                          </div>
                        </div>

                        <div className="space-y-2">
                          {(latestAnalysis.prospected_issues || [])
                            .slice(0, 3)
                            .map((issue) => (
                              <div
                                key={issue.rank}
                                className={`p-3 rounded-lg border ${
                                  issue.rank === 1
                                    ? 'bg-blue-500/10 border-blue-500/30'
                                    : issue.rank === 2
                                      ? 'bg-purple-500/10 border-purple-500/30'
                                      : 'bg-gray-500/10 border-gray-500/30'
                                }`}
                              >
                                <div className="flex items-start justify-between mb-1">
                                  <div className="flex items-center gap-2">
                                    <span
                                      className={`text-xs font-bold px-2 py-0.5 rounded ${
                                        issue.rank === 1
                                          ? 'bg-blue-500 text-white'
                                          : issue.rank === 2
                                            ? 'bg-purple-500 text-white'
                                            : 'bg-gray-500 text-white'
                                      }`}
                                    >
                                      #{issue.rank}
                                    </span>
                                    <span className="text-xs font-medium text-muted-foreground uppercase">
                                      {issue.category}
                                    </span>
                                  </div>
                                  <span className="text-xs font-semibold text-foreground">
                                    {Math.round(issue.confidence * 100)}% likely
                                  </span>
                                </div>

                                <div className="text-sm font-semibold text-foreground mb-1">
                                  {issue.issue_name}
                                </div>
                                <div className="text-xs text-muted-foreground">
                                  {issue.suspected_cause}
                                </div>
                              </div>
                            ))}
                        </div>

                        <div className="flex gap-2 text-xs pt-3 mt-3 border-t border-border">
                          <span
                            className={`px-2 py-1 rounded ${
                              latestAnalysis.requires_shutoff
                                ? 'bg-red-500/20 text-red-500'
                                : 'bg-gray-500/20 text-gray-500'
                            }`}
                          >
                            {latestAnalysis.requires_shutoff
                              ? '⚠️ Shutoff Required'
                              : '✓ No Shutoff'}
                          </span>
                          <span
                            className={`px-2 py-1 rounded ${
                              latestAnalysis.professional_needed
                                ? 'bg-orange-500/20 text-orange-500'
                                : 'bg-blue-500/20 text-blue-500'
                            }`}
                          >
                            {latestAnalysis.professional_needed
                              ? '👷 Pro Needed'
                              : '🔧 DIY Possible'}
                          </span>
                        </div>
                      </>
                    )}

                    {/* Guided Fix Center block */}
                    <div className="mt-4 p-4 rounded-2xl bg-secondary/25 border border-border">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <ListChecks className="w-4 h-4" />
                          <div className="text-sm font-semibold text-foreground">
                            Guided Fix
                          </div>
                        </div>

                        {!guideState ? (
                          <Button
                            onClick={startGuidedFix}
                            disabled={
                              guideLoading || isLatestNoIssue || !latestAnalysis
                            }
                            className="rounded-xl"
                          >
                            {guideLoading ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <Play className="w-4 h-4" />
                            )}
                            Start
                          </Button>
                        ) : (
                          <Button
                            variant="secondary"
                            onClick={resetGuidedFix}
                            disabled={guideLoading}
                            className="rounded-xl"
                          >
                            <RotateCcw className="w-4 h-4" />
                            Reset
                          </Button>
                        )}
                      </div>

                      {guideState && (
                        <>
                          <div className="mt-2 text-xs text-muted-foreground">
                            Plan:{' '}
                            <span className="font-medium">{guidePlanId}</span> •
                            Status:{' '}
                            <span className="font-medium">
                              {guideState.status}
                            </span>
                            {guideState?.focus?.issue_name
                              ? ` • Focus: ${guideState.focus.issue_name}`
                              : ''}
                          </div>

                          {guideMessage && (
                            <div className="mt-2 text-sm text-foreground">
                              {guideMessage}
                            </div>
                          )}

                          {curStep && guideState.status !== 'done' && (
                            <div className="mt-3 p-4 rounded-xl bg-card border border-border">
                              <div className="flex items-start justify-between gap-3">
                                <div>
                                  <div className="text-xs text-muted-foreground mb-1">
                                    Step {curStep.step_id} / {guideSteps.length}
                                  </div>
                                  <div className="text-sm font-semibold text-foreground">
                                    {curStep.title}
                                  </div>
                                </div>

                                {curStep.is_danger_step && (
                                  <div className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-red-500/20 text-red-500">
                                    <AlertTriangle className="w-3 h-3" />
                                    Safety
                                  </div>
                                )}
                              </div>

                              <div className="mt-3 text-sm text-foreground whitespace-pre-wrap">
                                {curStep.instruction}
                              </div>

                              {curStep.safety_note && (
                                <div className="mt-3 text-sm text-red-500/90 whitespace-pre-wrap">
                                  ⚠️ {curStep.safety_note}
                                </div>
                              )}

                              {curStep.check_hint && (
                                <div className="mt-3 text-xs text-muted-foreground">
                                  Check: {curStep.check_hint}
                                </div>
                              )}

                              <div className="mt-4 flex flex-wrap gap-2">
                                <Button
                                  onClick={() => guideNext('done')}
                                  disabled={guideLoading}
                                  className="rounded-xl"
                                >
                                  {guideLoading ? (
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                  ) : (
                                    <CheckCircle2 className="w-4 h-4" />
                                  )}
                                  Done
                                </Button>

                                <Button
                                  variant="secondary"
                                  onClick={() => guideNext('still')}
                                  disabled={guideLoading}
                                  className="rounded-xl"
                                >
                                  Still stuck
                                </Button>

                                <Button
                                  variant="destructive"
                                  onClick={() => guideNext('flushed_again')}
                                  disabled={guideLoading}
                                  className="rounded-xl"
                                >
                                  I flushed again
                                </Button>
                              </div>

                              {/* Progress checklist */}
                              <div className="mt-4 border-t border-border pt-3">
                                <div className="text-xs font-semibold text-foreground mb-2">
                                  Progress
                                </div>
                                <div className="space-y-2">
                                  {guideSteps.map((s) => {
                                    const done =
                                      guideState.completed_steps.includes(
                                        s.step_id,
                                      );
                                    const isCurrent =
                                      guideState.current_step === s.step_id &&
                                      guideState.status !== 'done';
                                    return (
                                      <div
                                        key={s.step_id}
                                        className={`flex items-center justify-between p-2 rounded-lg border ${
                                          done
                                            ? 'bg-green-500/10 border-green-500/30'
                                            : isCurrent
                                              ? 'bg-blue-500/10 border-blue-500/30'
                                              : 'bg-muted/30 border-border'
                                        }`}
                                      >
                                        <div className="flex items-center gap-2">
                                          <span
                                            className={`text-xs font-bold px-2 py-0.5 rounded ${
                                              done
                                                ? 'bg-green-600 text-white'
                                                : isCurrent
                                                  ? 'bg-blue-600 text-white'
                                                  : 'bg-gray-500 text-white'
                                            }`}
                                          >
                                            {s.step_id}
                                          </span>
                                          <span className="text-xs text-foreground">
                                            {s.title}
                                          </span>
                                        </div>
                                        <span className="text-xs text-muted-foreground">
                                          {done ? '✓' : isCurrent ? '→' : ''}
                                        </span>
                                      </div>
                                    );
                                  })}
                                </div>
                              </div>
                            </div>
                          )}

                          {guideState.status === 'done' && (
                            <div className="mt-3 p-4 rounded-xl bg-green-500/10 border border-green-500/30">
                              <div className="font-semibold text-foreground">
                                ✅ Guided Fix completed
                              </div>
                              <div className="text-sm text-muted-foreground mt-1">
                                If it still doesn’t work, use RAG summary on the
                                right.
                              </div>
                            </div>
                          )}
                        </>
                      )}

                      {!guideState && (
                        <div className="mt-2 text-xs text-muted-foreground">
                          Start after you have an issue detected.
                        </div>
                      )}
                    </div>
                  </section>

                  {/* RIGHT: RAG Summary */}
                  <section className="rounded-2xl border border-border bg-card p-4">
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-sm font-semibold text-foreground">
                        RAG Summary (Right)
                      </div>
                      <div className="flex gap-2">
                        <Button
                          onClick={fetchRagSolution}
                          disabled={solutionLoading}
                          className="rounded-xl"
                        >
                          {solutionLoading ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            <BookOpen className="w-4 h-4" />
                          )}
                          Generate
                        </Button>
                        <Button
                          variant="secondary"
                          onClick={() => {
                            setFinalSolution(null);
                            setCitations([]);
                            setRagQuery('');
                          }}
                          className="rounded-xl"
                          disabled={solutionLoading}
                        >
                          Clear
                        </Button>
                      </div>
                    </div>

                    {!finalSolution ? (
                      <div className="rounded-xl border border-border bg-muted/20 p-4 text-sm text-muted-foreground">
                        No RAG output yet. Click “Generate”.
                      </div>
                    ) : (
                      <div className="rounded-2xl bg-secondary/30 border border-border p-4">
                        {ragQuery && (
                          <div className="text-xs text-muted-foreground mb-2">
                            <span className="font-medium">Query:</span>{' '}
                            {ragQuery}
                          </div>
                        )}

                        <div className="text-sm font-semibold text-foreground mb-2">
                          Fix Plan
                        </div>
                        <div className="text-sm whitespace-pre-wrap text-foreground">
                          {finalSolution}
                        </div>

                        {citations.length > 0 && (
                          <div className="mt-4">
                            <div className="text-sm font-semibold text-foreground mb-2">
                              Sources (Top Matches)
                            </div>
                            <div className="space-y-2">
                              {citations.slice(0, 3).map((c) => (
                                <div
                                  key={c.rank}
                                  className="p-3 rounded-lg bg-card border border-border"
                                >
                                  <div className="flex items-center justify-between mb-1">
                                    <div className="text-xs font-semibold text-foreground">
                                      #{c.rank} • {c.source}
                                    </div>
                                    <div className="text-xs text-muted-foreground">
                                      score: {c.score?.toFixed(3) ?? 'n/a'}
                                    </div>
                                  </div>
                                  <div className="text-xs text-muted-foreground whitespace-pre-wrap">
                                    {c.text.slice(0, 300)}
                                    {c.text.length > 300 ? '…' : ''}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    <div className="mt-4 pt-4 border-t border-border">
                      <div className="text-xs font-semibold text-foreground mb-2">
                        When to use RAG
                      </div>
                      <ul className="text-sm text-muted-foreground space-y-1">
                        <li>
                          • When you understand what the issue is, but need
                          precise, step-by-step instructions
                        </li>
                        <li>
                          • When symptoms remain even after completing the
                          Guided Fix
                        </li>
                        <li>
                          • When you need a parts, tools, or safety checklist
                        </li>
                      </ul>
                    </div>
                  </section>
                </div>
              </div>
            </div>

            {/* small footer padding */}
            <div className="h-10" />
          </div>
        </div>
      </main>

      <canvas ref={canvasRef} className="hidden" />
    </div>
  );
}
