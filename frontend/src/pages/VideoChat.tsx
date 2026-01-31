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
  X,
  Maximize2,
  Minimize2
} from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { toast } from "sonner";

interface Message {
  role: "user" | "assistant";
  content: string;
  image?: string;
}

export default function VideoChat() {
  const [isVideoActive, setIsVideoActive] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputMessage, setInputMessage] = useState("");
  const [isFullscreen, setIsFullscreen] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const startVideo = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ 
        video: { 
          facingMode: "environment",
          width: { ideal: 1280 },
          height: { ideal: 720 }
        } 
      });
      
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        streamRef.current = stream;
        setIsVideoActive(true);
        toast.success("Camera started! Point at your issue.");
      }
    } catch (error) {
      console.error("Error accessing camera:", error);
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
                {isVideoActive ? (
                  <>
                    <video
                      ref={videoRef}
                      autoPlay
                      playsInline
                      muted
                      className="w-full h-full object-cover"
                    />
                    {/* Video overlay controls */}
                    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-3">
                      <Button
                        variant="hero"
                        size="lg"
                        onClick={() => sendMessage(true)}
                        disabled={isLoading}
                      >
                        {isLoading ? (
                          <Loader2 className="w-5 h-5 animate-spin" />
                        ) : (
                          <Camera className="w-5 h-5" />
                        )}
                        Capture & Analyze
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
                ) : (
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
              
              {/* Tips */}
              <div className="mt-4 p-4 rounded-xl bg-secondary/50 border border-border">
                <h4 className="font-medium text-foreground mb-2 flex items-center gap-2">
                  <MessageCircle className="w-4 h-4 text-accent" />
                  Tips for best results
                </h4>
                <ul className="text-sm text-muted-foreground space-y-1">
                  <li>• Ensure good lighting on the problem area</li>
                  <li>• Hold camera steady and close enough to see details</li>
                  <li>• Describe what you're experiencing in the chat</li>
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
