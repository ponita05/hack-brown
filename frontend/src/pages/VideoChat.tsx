// frontend/src/pages/VideoChat.tsx
import { useState, useRef, useCallback, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Header } from '@/components/landing/Header';
import {
  Video,
  VideoOff,
  Send,
  Camera,
  Loader2,
  MessageCircle,
  Maximize2,
  Minimize2,
  Play,
  Pause,
  BookOpen,
} from 'lucide-react';
import { supabase } from '@/integrations/supabase/client';
import { toast } from 'sonner';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  image?: string;
}

interface ProspectedIssue {
  rank: number;
  issue_name: string;
  suspected_cause: string;
  confidence: number;
  symptoms_match: string[];
  category: string;
}

interface HomeIssueAnalysis {
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

// ✅ ms 추가: 프레임 한 번 보내고 응답 오기까지 걸린 시간
type SendResult = { ok: boolean; reason: SendResultReason; ms?: number };

// RAG /solution response
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

const BACKEND_URL = 'http://127.0.0.1:8000';
const SESSION_ID = 'demo-session-1';

// ✅ Auto 모드: “응답이 오면” 최대한 빨리 다음 프레임 보냄
// 이 값은 “응답 후 다음 요청까지의 최소 딜레이”
const AUTO_CAPTURE_INTERVAL_MS = 300;

// ✅ Manual이 auto(또는 다른 요청) 끝날 때까지 기다릴 때 폴링 간격
const MANUAL_WAIT_POLL_MS = 120;

// ✅ toast 너무 많이 뜨는 거 방지
const TOAST_COOLDOWN_MS = 1500;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function VideoChat() {
  const [isVideoActive, setIsVideoActive] = useState(false);

  // 채팅(Edge function)용 로딩
  const [isLoading, setIsLoading] = useState(false);

  // 수동 프레임 캡처(backend /frame)용 로딩 (따로!)
  const [manualCaptureLoading, setManualCaptureLoading] = useState(false);

  // ✅ RAG 솔루션 로딩/결과
  const [solutionLoading, setSolutionLoading] = useState(false);
  const [finalSolution, setFinalSolution] = useState<string | null>(null);
  const [citations, setCitations] = useState<RagCitation[]>([]);
  const [ragQuery, setRagQuery] = useState<string>('');

  const [messages, setMessages] = useState<Message[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [autoCapture, setAutoCapture] = useState(false);
  const [latestAnalysis, setLatestAnalysis] =
    useState<HomeIssueAnalysis | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // ✅ rerender 유발 방지: 상태 대신 ref로 “루프/전송 상태” 관리
  const inFlightRef = useRef(false);
  const stopLoopRef = useRef(false);
  const loopStartedRef = useRef(false);
  const lastToastAtRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

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

      setIsVideoActive(true);
      toast.success('Camera started! Point at your issue.');
    } catch (error) {
      console.error('❌ startVideo error:', error);
      toast.error('Could not access camera. Please check permissions.');
    }
  }, []);

  const stopVideo = useCallback(() => {
    // ✅ 루프 멈추기
    stopLoopRef.current = true;
    loopStartedRef.current = false;

    // ✅ 진행 중 fetch 중단
    abortRef.current?.abort();
    abortRef.current = null;

    // ✅ 카메라 정지
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    setAutoCapture(false);
    setIsVideoActive(false);
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

  /**
   * ✅ 백엔드에 프레임 1장 보내고 결과 받기
   * - Auto 모드에서는 “응답 오면” 다시 보냄 (setInterval X)
   * - throttled/duplicate/busy는 “실패 토스트”를 띄우지 않는다
   * - 콘솔에 latency(ms) 출력
   */
  const sendFrameToBackend = useCallback(async (): Promise<SendResult> => {
    if (inFlightRef.current) return { ok: false, reason: 'busy' };

    if (!videoRef.current || videoRef.current.readyState < 2) {
      return { ok: false, reason: 'video-not-ready' };
    }

    const dataUrl = captureFrame();
    if (!dataUrl) return { ok: false, reason: 'no-frame' };

    inFlightRef.current = true;

    const t0 = performance.now();
    console.log(`[frame] → sending @ ${new Date().toISOString()}`);

    try {
      // dataURL -> Blob
      const blobResp = await fetch(dataUrl);
      const blob = await blobResp.blob();

      const formData = new FormData();
      formData.append('image', blob, 'frame.jpg');
      formData.append('session_id', SESSION_ID);

      // ✅ AbortController로 stopVideo 시 요청 중단 가능
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
        console.error(
          `[frame] ✗ HTTP ${res.status} in ${ms.toFixed(0)}ms`,
          text,
        );
        return { ok: false, reason: 'failed', ms };
      }

      const result = await res.json().catch(() => null);

      if (result?.success && result?.data) {
        const analysis: HomeIssueAnalysis = result.data;
        setLatestAnalysis(analysis);

        const topIssue =
          analysis.prospected_issues?.[0]?.issue_name || 'Issue detected';

        const now = Date.now();
        if (now - lastToastAtRef.current > TOAST_COOLDOWN_MS) {
          toast.success(`Analyzed: ${topIssue}`);
          lastToastAtRef.current = now;
        }

        console.log(`[frame] ✓ success in ${ms.toFixed(0)}ms`, { topIssue });
        return { ok: true, reason: 'ok', ms };
      }

      if (result?.skipped) {
        const reason = String(result.reason || 'skipped');
        console.warn(
          `[frame] ⚠ skipped(${reason}) in ${ms.toFixed(0)}ms`,
          result,
        );

        if (reason === 'throttled')
          return { ok: false, reason: 'throttled', ms };
        if (reason === 'duplicate')
          return { ok: false, reason: 'duplicate', ms };
        if (reason === 'busy') return { ok: false, reason: 'busy', ms };

        return { ok: false, reason: 'skipped', ms };
      }

      console.error(
        `[frame] ✗ Unexpected result in ${ms.toFixed(0)}ms`,
        result,
      );
      return { ok: false, reason: 'failed', ms };
    } catch (error: any) {
      const ms = performance.now() - t0;

      if (error?.name === 'AbortError') {
        console.warn(`[frame] aborted in ${ms.toFixed(0)}ms`);
        return { ok: false, reason: 'skipped', ms };
      }
      console.error(`[frame] ✗ network in ${ms.toFixed(0)}ms`, error);
      return { ok: false, reason: 'network', ms };
    } finally {
      inFlightRef.current = false;
    }
  }, [captureFrame]);

  /**
   * ✅ Auto-Capture 루프 (응답-기반)
   * - “응답이 오면” 바로 다음 프레임을 보냄
   * - busy/duplicate/throttled일 때만 약간 기다렸다가 재시도
   */
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
        const r = await sendFrameToBackend();

        // ✅ 상황별로 “다음 요청까지” 기다리는 시간 조절
        let waitMs = AUTO_CAPTURE_INTERVAL_MS;

        if (!r.ok) {
          if (r.reason === 'busy') waitMs = 250;
          else if (r.reason === 'duplicate') waitMs = 700;
          else if (r.reason === 'throttled') waitMs = 600;
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
        } else {
          // ok면 최대한 빠르게 (짧게)
          waitMs = AUTO_CAPTURE_INTERVAL_MS;
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

    // 수동 캡처할 때, 이전 솔루션은 초기화(선택)
    setFinalSolution(null);
    setCitations([]);
    setRagQuery('');

    // ✅ auto나 다른 전송이 돌고 있으면 끝날 때까지 “대기”
    while (inFlightRef.current) {
      await sleep(MANUAL_WAIT_POLL_MS);
    }

    const r = await sendFrameToBackend();

    if (!r.ok) {
      if (r.reason === 'network') toast.error('Backend not reachable.');
      else if (r.reason === 'video-not-ready')
        toast.error('Video not ready yet.');
      else if (r.reason === 'no-frame') toast.error('Could not capture frame.');
      else if (r.reason === 'failed') toast.error('Analysis failed.');
    }

    setManualCaptureLoading(false);
  };

  /**
   * ✅ RAG 솔루션 생성 (backend /solution)
   * - Redis의 latest 분석(JSON)을 기반으로 RAG retrieval 후 최종 해결책 생성
   */
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

  const sendMessage = async (includeImage: boolean = false) => {
    if (!inputMessage.trim() && !includeImage) return;

    setIsLoading(true);

    let imageData: string | null = null;
    if (includeImage && isVideoActive) {
      imageData = captureFrame();
    }

    const userMessage: Message = {
      role: 'user',
      content:
        inputMessage ||
        'What do you see in this image? Help me identify and fix any issues.',
      image: imageData || undefined,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputMessage('');

    try {
      const { data, error } = await supabase.functions.invoke(
        'analyze-home-issue',
        {
          body: {
            message: userMessage.content,
            image: imageData,
            history: messages.slice(-6),
          },
        },
      );

      if (error) {
        console.error('Edge function error:', error);

        if (error.message?.includes('429')) {
          toast.error('Rate limit reached. Please wait and try again.');
        } else if (error.message?.includes('402')) {
          toast.error('AI credits exhausted. Please add more credits.');
        } else {
          toast.error('Failed to get AI response. Please try again.');
        }
        return;
      }

      const assistantMessage: Message = {
        role: 'assistant',
        content: data.response,
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      console.error('Error sending message:', error);
      toast.error('Something went wrong. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(false);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <Header />

      <main className="pt-20 pb-8">
        <div className="container px-4">
          <div
            className={`grid gap-6 ${
              isFullscreen ? '' : 'lg:grid-cols-2'
            } max-w-7xl mx-auto`}
          >
            {/* Video Section */}
            <div className={`${isFullscreen ? 'hidden' : ''} order-1`}>
              <div className="relative aspect-video bg-primary rounded-2xl overflow-hidden shadow-card">
                <video
                  ref={videoRef}
                  autoPlay
                  playsInline
                  muted
                  className={`w-full h-full object-cover ${
                    isVideoActive ? '' : 'hidden'
                  }`}
                />

                {isVideoActive && (
                  <>
                    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-3">
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
                        size="icon"
                        onClick={stopVideo}
                        className="rounded-full"
                      >
                        <VideoOff className="w-5 h-5" />
                      </Button>
                    </div>

                    <div className="absolute top-4 left-4 flex items-center gap-2 px-3 py-1.5 rounded-full bg-destructive/90 text-destructive-foreground text-sm font-medium">
                      <span className="w-2 h-2 rounded-full bg-current animate-pulse-live" />
                      LIVE
                    </div>
                  </>
                )}

                {!isVideoActive && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center text-primary-foreground p-8">
                    <div className="w-20 h-20 rounded-full bg-primary-foreground/10 flex items-center justify-center mb-6">
                      <Video className="w-10 h-10" />
                    </div>
                    <h3 className="text-xl font-semibold mb-2 text-center">
                      Start Your Video Session
                    </h3>
                    <p className="text-primary-foreground/70 text-center mb-6 max-w-sm">
                      Point your camera at the issue and our AI will help
                      identify the problem and guide you through the fix.
                    </p>
                    <Button variant="hero" size="lg" onClick={startVideo}>
                      <Video className="w-5 h-5" />
                      Start Camera
                    </Button>
                  </div>
                )}
              </div>

              {/* Latest Analysis Panel */}
              {latestAnalysis && (
                <div className="mt-4 p-4 rounded-xl bg-card border border-border">
                  <h4 className="font-semibold text-foreground mb-3 flex items-center justify-between">
                    <span>Analysis - Top 3 Issues</span>
                    <span
                      className={`text-xs px-2 py-1 rounded-full ${
                        latestAnalysis.overall_danger_level === 'high'
                          ? 'bg-red-500/20 text-red-500'
                          : latestAnalysis.overall_danger_level === 'medium'
                            ? 'bg-yellow-500/20 text-yellow-500'
                            : 'bg-green-500/20 text-green-500'
                      }`}
                    >
                      {latestAnalysis.overall_danger_level.toUpperCase()}
                    </span>
                  </h4>

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
                        Immediate Action:{' '}
                      </span>
                      <span className="text-muted-foreground">
                        {latestAnalysis.immediate_action}
                      </span>
                    </div>
                  </div>

                  <div className="space-y-2">
                    {latestAnalysis.prospected_issues.map((issue, idx) => (
                      <div
                        key={idx}
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

                  {/* ✅ RAG 버튼 */}
                  <div className="mt-4 flex gap-2">
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
                      Generate Solution (RAG)
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

                  {/* ✅ RAG 결과 표시 */}
                  {finalSolution && (
                    <div className="mt-4 p-4 rounded-xl bg-secondary/40 border border-border">
                      {ragQuery && (
                        <div className="text-xs text-muted-foreground mb-2">
                          <span className="font-medium">RAG Query:</span>{' '}
                          {ragQuery}
                        </div>
                      )}

                      <h5 className="font-semibold text-foreground mb-2">
                        Fix Plan
                      </h5>
                      <div className="text-sm whitespace-pre-wrap text-foreground">
                        {finalSolution}
                      </div>

                      {citations.length > 0 && (
                        <div className="mt-4">
                          <h6 className="text-sm font-semibold text-foreground mb-2">
                            Sources (Top Matches)
                          </h6>
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
                                  {c.text.slice(0, 260)}
                                  {c.text.length > 260 ? '…' : ''}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              <div className="mt-4 p-4 rounded-xl bg-secondary/50 border border-border">
                <h4 className="font-medium text-foreground mb-2 flex items-center gap-2">
                  <MessageCircle className="w-4 h-4 text-accent" />
                  Tips for best results
                </h4>
                <ul className="text-sm text-muted-foreground space-y-1">
                  <li>• Ensure good lighting on the problem area</li>
                  <li>• Hold camera steady and close enough to see details</li>
                  <li>
                    • Auto mode sends the next frame right after each result
                    returns
                  </li>
                </ul>
              </div>
            </div>

            {/* Chat Section */}
            <div
              className={`order-2 flex flex-col ${
                isFullscreen ? 'max-w-3xl mx-auto w-full' : ''
              }`}
            >
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-foreground">
                  Chat with FixDad AI
                </h2>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setIsFullscreen(!isFullscreen)}
                  className="lg:flex hidden"
                >
                  {isFullscreen ? (
                    <Minimize2 className="w-4 h-4" />
                  ) : (
                    <Maximize2 className="w-4 h-4" />
                  )}
                </Button>
              </div>

              <div className="flex-1 min-h-[400px] max-h-[600px] overflow-y-auto rounded-2xl bg-card border border-border p-4 space-y-4">
                {messages.length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-center p-8">
                    <div className="w-16 h-16 rounded-full bg-accent/10 flex items-center justify-center mb-4">
                      <MessageCircle className="w-8 h-8 text-accent" />
                    </div>
                    <h3 className="font-semibold text-foreground mb-2">
                      Ready to help!
                    </h3>
                    <p className="text-muted-foreground text-sm max-w-sm">
                      Start your camera and capture an image, or just describe
                      your home issue in the chat below.
                    </p>
                  </div>
                ) : (
                  messages.map((msg, index) => (
                    <div
                      key={index}
                      className={`flex ${
                        msg.role === 'user' ? 'justify-end' : 'justify-start'
                      }`}
                    >
                      <div
                        className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                          msg.role === 'user'
                            ? 'bg-primary text-primary-foreground'
                            : 'bg-secondary text-secondary-foreground'
                        }`}
                      >
                        {msg.image && (
                          <img
                            src={msg.image}
                            alt="Captured frame"
                            className="rounded-lg mb-2 max-h-48 object-cover"
                          />
                        )}
                        <p className="text-sm whitespace-pre-wrap">
                          {msg.content}
                        </p>
                      </div>
                    </div>
                  ))
                )}

                {isLoading && (
                  <div className="flex justify-start">
                    <div className="bg-secondary text-secondary-foreground rounded-2xl px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span className="text-sm">Analyzing...</span>
                      </div>
                    </div>
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>

              <div className="mt-4 flex gap-2">
                <div className="flex-1 relative">
                  <textarea
                    value={inputMessage}
                    onChange={(e) => setInputMessage(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Describe your issue or ask a question..."
                    className="w-full px-4 py-3 pr-12 rounded-xl bg-card border border-border resize-none focus:outline-none focus:ring-2 focus:ring-ring text-foreground placeholder:text-muted-foreground"
                    rows={1}
                  />
                </div>
                <Button
                  onClick={() => sendMessage(false)}
                  disabled={isLoading || !inputMessage.trim()}
                  size="icon"
                  className="h-[46px] w-[46px] rounded-xl"
                >
                  {isLoading ? (
                    <Loader2 className="w-5 h-5 animate-spin" />
                  ) : (
                    <Send className="w-5 h-5" />
                  )}
                </Button>
              </div>
            </div>
          </div>
        </div>
      </main>

      <canvas ref={canvasRef} className="hidden" />
    </div>
  );
}
