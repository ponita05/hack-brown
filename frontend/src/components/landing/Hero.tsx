import { Button } from "@/components/ui/button";
import { Video, Wrench, Shield, ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

export function Hero() {
  return (
    <section className="relative min-h-screen flex items-center justify-center overflow-hidden bg-gradient-to-br from-orange-50 via-white to-amber-50">
      {/* Ambient glow effect */}
      <div className="absolute inset-0 bg-gradient-to-br from-orange-100/40 via-transparent to-amber-100/40" />

      {/* Floating decorative elements */}
      <div className="absolute top-1/4 left-1/4 w-72 h-72 bg-orange-400/15 rounded-full blur-3xl animate-float" />
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-amber-400/10 rounded-full blur-3xl animate-float animation-delay-200" />

      <div className="container relative z-10 px-4 py-20 md:py-32">
        <div className="max-w-4xl mx-auto text-center">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-gradient-to-r from-orange-500/10 to-amber-500/10 backdrop-blur-sm border-2 border-orange-400/30 mb-8 animate-fade-in-up shadow-lg shadow-orange-500/10">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-orange-500 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-orange-500" />
            </span>
            <span className="text-orange-700 text-sm font-extrabold tracking-wider uppercase">
              AI-Powered Home Repair Assistant
            </span>
          </div>

          {/* Main heading */}
          <h1 className="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-black text-gray-900 leading-[1.05] mb-6 animate-fade-in-up animation-delay-200 tracking-tight uppercase">
            Like FaceTiming{" "}
            <span className="bg-gradient-to-r from-orange-600 to-amber-500 bg-clip-text text-transparent font-black">Your Handy Daddy</span>
            <br />
            For Home Repairs
          </h1>

          {/* Subtitle */}
          <p className="text-lg sm:text-xl text-gray-700 max-w-2xl mx-auto mb-10 animate-fade-in-up animation-delay-400 leading-relaxed font-bold">
            Show your plumbing, appliances, or renovation project through live video.
            Our AI sees, measures, and guides you step-by-step — just like having an expert
            right there with you.
          </p>

          {/* CTA Buttons */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-16 animate-fade-in-up animation-delay-600">
            <Button
              size="xl"
              asChild
              className="bg-gradient-to-r from-orange-600 to-orange-500 hover:from-orange-700 hover:to-orange-600 text-white font-bold shadow-xl shadow-orange-500/40 px-8"
            >
              <Link to="/chat">
                <Video className="w-5 h-5" />
                Start Video Chat
                <ArrowRight className="w-5 h-5" />
              </Link>
            </Button>
            <Button
              variant="outline"
              size="lg"
              asChild
              className="border-2 border-orange-300 text-orange-700 hover:bg-orange-50 font-semibold"
            >
              <a href="#how-it-works">
                See How It Works
              </a>
            </Button>
          </div>

          {/* Trust indicators */}
          <div className="flex flex-wrap items-center justify-center gap-8 text-gray-700 animate-fade-in-up animation-delay-600">
            <div className="flex items-center gap-2">
              <Shield className="w-5 h-5 text-orange-600" />
              <span className="text-sm font-extrabold uppercase tracking-wide">Privacy First</span>
            </div>
            <div className="flex items-center gap-2">
              <Video className="w-5 h-5 text-orange-600" />
              <span className="text-sm font-extrabold uppercase tracking-wide">Real-Time Analysis</span>
            </div>
            <div className="flex items-center gap-2">
              <Wrench className="w-5 h-5 text-orange-600" />
              <span className="text-sm font-extrabold uppercase tracking-wide">Expert Guidance</span>
            </div>
          </div>
        </div>
      </div>

      {/* Bottom gradient fade */}
      <div className="absolute bottom-0 left-0 right-0 h-32 bg-gradient-to-t from-white to-transparent" />
    </section>
  );
}
