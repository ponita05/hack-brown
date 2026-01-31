import { useState, useRef, useCallback, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Header } from "@/components/landing/Header";
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
  Pause
} from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { toast } from "sonner";

interface Message {
  role: "user" | "assistant";
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
  overall_danger_level: "low" | "medium" | "high";
  location: string;
  fixture: string;
  observed_symptoms: string[];
  requires_shutoff: boolean;
  water_present: boolean;
  immediate_action: string;
  professional_needed: boolean;
}

export default function VideoChat() {
  const [isVideoActive, setIsVideoActive] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputMessage, setInputMessage] = useState("");
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [autoCapture, setAutoCapture] = useState(false);
  const [latestAnalysis, setLatestAnalysis] = useState<HomeIssueAnalysis | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const autoCaptureTimerRef = useRef<number | null>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const startVideo = useCallback(async () => {
    console.log("🎥 Starting camera...");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: "user",  // Use front camera (for laptops/webcams)
          width: { ideal: 1280 },
          height: { ideal: 720 }
        }
      });

      console.log("✅ Got stream:", stream);
      console.log("📹 Video tracks:", stream.getVideoTracks());

      if (videoRef.current) {
        console.log("📺 Setting srcObject on video element");
        videoRef.current.srcObject = stream;
        streamRef.current = stream;

        // Wait for video to be ready
        videoRef.current.onloadedmetadata = () => {
          console.log("📊 Video metadata loaded. Dimensions:", videoRef.current?.videoWidth, "x", videoRef.current?.videoHeight);
        };

        // Explicitly play the video (required for some browsers)
        try {
          await videoRef.current.play();
          console.log("▶️ Video playing");
          setIsVideoActive(true);
          toast.success("Camera started! Point at your issue.");
        } catch (playError) {
          console.error("❌ Error playing video:", playError);
          toast.error("Could not play video: " + (playError as Error).message);
        }
      } else {
        console.error("❌ videoRef.current is null!");
      }
    } catch (error) {
      console.error("❌ Error accessing camera:", error);
      toast.error("Could not access camera. Please check permissions.");
    }
  }, []);

  const stopVideo = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setIsVideoActive(false);
    setAutoCapture(false); // Stop auto-capture when video stops
  }, []);

  const captureFrame = useCallback((): string | null => {
    if (!videoRef.current || !canvasRef.current) return null;

    const video = videoRef.current;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");

    if (!ctx) return null;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    ctx.drawImage(video, 0, 0);

    return canvas.toDataURL("image/jpeg", 0.8);
  }, []);

  // Send frame to FastAPI backend for Gemini analysis
  const sendFrameToBackend = useCallback(async () => {
    if (!videoRef.current || videoRef.current.readyState < 2) {
      console.log("Video not ready yet");
      return;
    }

    console.log("📸 Capturing frame...");
    const dataUrl = captureFrame();
    if (!dataUrl) return;

    const startTime = Date.now();

    try {
      // Convert data URL to blob
      const response = await fetch(dataUrl);
      const blob = await response.blob();

      const formData = new FormData();
      formData.append("image", blob, "frame.jpg");
      formData.append("session_id", "demo-session-1");

      console.log("📤 Sending to Gemini API...");
      const res = await fetch("http://localhost:8000/frame", {
        method: "POST",
        body: formData,
      });

      const result = await res.json();
      const elapsed = Date.now() - startTime;

      if (result.success && result.data) {
        setLatestAnalysis(result.data);
        console.log(`✅ Frame analyzed successfully (${elapsed}ms)`);
        console.log("📊 Full JSON Response:", JSON.stringify(result.data, null, 2));
        console.log("🔝 Top 3 Issues:", result.data.prospected_issues.map((i: any) =>
          `${i.rank}. ${i.issue_name} (${(i.confidence * 100).toFixed(0)}%)`
        ).join(", "));

        const topIssue = result.data.prospected_issues?.[0]?.issue_name || "Issue detected";
        toast.success(`Analyzed: ${topIssue}`);
      } else {
        console.error("❌ Analysis failed:", result);
        toast.error("Analysis failed. Check console for details.");
      }
    } catch (error) {
      console.error("❌ Error sending frame to backend:", error);
      toast.error("Cannot connect to backend. Is it running on port 8000?");
    }
  }, [captureFrame]);

  // Auto-capture effect: runs every 4 seconds when enabled
  useEffect(() => {
    if (!autoCapture || !isVideoActive) {
      // Clear timer if auto-capture is disabled or video stopped
      if (autoCaptureTimerRef.current) {
        window.clearInterval(autoCaptureTimerRef.current);
        autoCaptureTimerRef.current = null;
      }
      return;
    }

    // Start the interval
    autoCaptureTimerRef.current = window.setInterval(() => {
      sendFrameToBackend();
    }, 4000); // 4 seconds

    // Cleanup on unmount or when dependencies change
    return () => {
      if (autoCaptureTimerRef.current) {
        window.clearInterval(autoCaptureTimerRef.current);
        autoCaptureTimerRef.current = null;
      }
    };
  }, [autoCapture, isVideoActive, sendFrameToBackend]);

  const sendMessage = async (includeImage: boolean = false) => {
    if (!inputMessage.trim() && !includeImage) return;
    
    setIsLoading(true);
    
    let imageData: string | null = null;
    if (includeImage && isVideoActive) {
      imageData = captureFrame();
    }

    const userMessage: Message = {
      role: "user",
      content: inputMessage || "What do you see in this image? Help me identify and fix any issues.",
      image: imageData || undefined,
    };

    setMessages(prev => [...prev, userMessage]);
    setInputMessage("");

    try {
      const { data, error } = await supabase.functions.invoke("analyze-home-issue", {
        body: {
          message: userMessage.content,
          image: imageData,
          history: messages.slice(-6), // Send last 6 messages for context
        },
      });

      if (error) {
        console.error("Edge function error:", error);
        
        if (error.message?.includes("429")) {
          toast.error("Rate limit reached. Please wait a moment and try again.");
        } else if (error.message?.includes("402")) {
          toast.error("AI credits exhausted. Please add more credits to continue.");
        } else {
          toast.error("Failed to get AI response. Please try again.");
        }
        return;
      }

      const assistantMessage: Message = {
        role: "assistant",
        content: data.response,
      };

      setMessages(prev => [...prev, assistantMessage]);
    } catch (error) {
      console.error("Error sending message:", error);
      toast.error("Something went wrong. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(false);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <Header />
      
      <main className="pt-20 pb-8">
        <div className="container px-4">
          <div className={`grid gap-6 ${isFullscreen ? "" : "lg:grid-cols-2"} max-w-7xl mx-auto`}>
            
            {/* Video Section */}
            <div className={`${isFullscreen ? "hidden" : ""} order-1`}>
              <div className="relative aspect-video bg-primary rounded-2xl overflow-hidden shadow-card">
                {/* Video element - always rendered so ref is available */}
                <video
                  ref={videoRef}
                  autoPlay
                  playsInline
                  muted
                  className={`w-full h-full object-cover ${isVideoActive ? "" : "hidden"}`}
                />

                {/* Video overlay controls - shown when video is active */}
                {isVideoActive && (
                  <>
                    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-3">
                      <Button
                        variant={autoCapture ? "default" : "hero"}
                        size="lg"
                        onClick={() => setAutoCapture(!autoCapture)}
                        className={autoCapture ? "bg-green-600 hover:bg-green-700" : ""}
                      >
                        {autoCapture ? (
                          <>
                            <Pause className="w-5 h-5" />
                            Auto-Analyzing (4s)
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
                        onClick={() => sendMessage(true)}
                        disabled={isLoading}
                      >
                        {isLoading ? (
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
                    {/* Live indicator */}
                    <div className="absolute top-4 left-4 flex items-center gap-2 px-3 py-1.5 rounded-full bg-destructive/90 text-destructive-foreground text-sm font-medium">
                      <span className="w-2 h-2 rounded-full bg-current animate-pulse-live" />
                      LIVE
                    </div>
                  </>
                )}

                {/* Start camera prompt - shown when video is not active */}
                {!isVideoActive && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center text-primary-foreground p-8">
                    <div className="w-20 h-20 rounded-full bg-primary-foreground/10 flex items-center justify-center mb-6">
                      <Video className="w-10 h-10" />
                    </div>
                    <h3 className="text-xl font-semibold mb-2 text-center">
                      Start Your Video Session
                    </h3>
                    <p className="text-primary-foreground/70 text-center mb-6 max-w-sm">
                      Point your camera at the issue and our AI will help identify
                      the problem and guide you through the fix.
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
                    <span>Claude Analysis - Top 3 Issues</span>
                    <span className={`text-xs px-2 py-1 rounded-full ${
                      latestAnalysis.overall_danger_level === 'high' ? 'bg-red-500/20 text-red-500' :
                      latestAnalysis.overall_danger_level === 'medium' ? 'bg-yellow-500/20 text-yellow-500' :
                      'bg-green-500/20 text-green-500'
                    }`}>
                      {latestAnalysis.overall_danger_level.toUpperCase()}
                    </span>
                  </h4>

                  {/* Location & Immediate Action */}
                  <div className="space-y-2 text-sm mb-3 pb-3 border-b border-border">
                    <div>
                      <span className="font-medium text-foreground">Location: </span>
                      <span className="text-muted-foreground">{latestAnalysis.location}</span>
                    </div>
                    <div>
                      <span className="font-medium text-foreground">Immediate Action: </span>
                      <span className="text-muted-foreground">{latestAnalysis.immediate_action}</span>
                    </div>
                  </div>

                  {/* Top 3 Prospected Issues */}
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
                            <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                              issue.rank === 1
                                ? 'bg-blue-500 text-white'
                                : issue.rank === 2
                                ? 'bg-purple-500 text-white'
                                : 'bg-gray-500 text-white'
                            }`}>
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

                  {/* Status Badges */}
                  <div className="flex gap-2 text-xs pt-3 mt-3 border-t border-border">
                    <span className={`px-2 py-1 rounded ${latestAnalysis.requires_shutoff ? 'bg-red-500/20 text-red-500' : 'bg-gray-500/20 text-gray-500'}`}>
                      {latestAnalysis.requires_shutoff ? '⚠️ Shutoff Required' : '✓ No Shutoff'}
                    </span>
                    <span className={`px-2 py-1 rounded ${latestAnalysis.professional_needed ? 'bg-orange-500/20 text-orange-500' : 'bg-blue-500/20 text-blue-500'}`}>
                      {latestAnalysis.professional_needed ? '👷 Pro Needed' : '🔧 DIY Possible'}
                    </span>
                  </div>
                </div>
              )}

              {/* Tips */}
              <div className="mt-4 p-4 rounded-xl bg-secondary/50 border border-border">
                <h4 className="font-medium text-foreground mb-2 flex items-center gap-2">
                  <MessageCircle className="w-4 h-4 text-accent" />
                  Tips for best results
                </h4>
                <ul className="text-sm text-muted-foreground space-y-1">
                  <li>• Ensure good lighting on the problem area</li>
                  <li>• Hold camera steady and close enough to see details</li>
                  <li>• Click "Start Auto-Capture" for continuous analysis every 4 seconds</li>
                </ul>
              </div>
            </div>

            {/* Chat Section */}
            <div className={`order-2 flex flex-col ${isFullscreen ? "max-w-3xl mx-auto w-full" : ""}`}>
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

              {/* Messages */}
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
                      className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                    >
                      <div
                        className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                          msg.role === "user"
                            ? "bg-primary text-primary-foreground"
                            : "bg-secondary text-secondary-foreground"
                        }`}
                      >
                        {msg.image && (
                          <img
                            src={msg.image}
                            alt="Captured frame"
                            className="rounded-lg mb-2 max-h-48 object-cover"
                          />
                        )}
                        <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
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

              {/* Input */}
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

      {/* Hidden canvas for frame capture */}
      <canvas ref={canvasRef} className="hidden" />
    </div>
  );
}
