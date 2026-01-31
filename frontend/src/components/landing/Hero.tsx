import { Button } from "@/components/ui/button";
import { Video, Wrench, Shield, ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

export function Hero() {
  return (
    <section className="relative min-h-screen flex items-center justify-center overflow-hidden bg-gradient-hero">
      {/* Ambient glow effect */}
      <div className="absolute inset-0 bg-gradient-glow opacity-50" />
      
      {/* Floating decorative elements */}
      <div className="absolute top-1/4 left-1/4 w-72 h-72 bg-accent/10 rounded-full blur-3xl animate-float" />
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-accent/5 rounded-full blur-3xl animate-float animation-delay-200" />
      
      <div className="container relative z-10 px-4 py-20 md:py-32">
        <div className="max-w-4xl mx-auto text-center">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary-foreground/10 backdrop-blur-sm border border-primary-foreground/20 mb-8 animate-fade-in-up">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-accent" />
            </span>
            <span className="text-primary-foreground/90 text-sm font-medium">
              AI-Powered Home Repair Assistant
            </span>
          </div>

          {/* Main heading */}
          <h1 className="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-bold text-primary-foreground leading-tight mb-6 animate-fade-in-up animation-delay-200">
            Like FaceTiming{" "}
            <span className="text-gradient-accent">Your Dad</span>
            <br />
            For Home Repairs
          </h1>

          {/* Subtitle */}
          <p className="text-lg sm:text-xl text-primary-foreground/70 max-w-2xl mx-auto mb-10 animate-fade-in-up animation-delay-400">
            Show your plumbing, appliances, or renovation project through live video. 
            Our AI sees, measures, and guides you step-by-step — just like having an expert 
            right there with you.
          </p>

          {/* CTA Buttons */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-16 animate-fade-in-up animation-delay-600">
            <Button variant="hero" size="xl" asChild>
              <Link to="/chat">
                <Video className="w-5 h-5" />
                Start Video Chat
                <ArrowRight className="w-5 h-5" />
              </Link>
            </Button>
            <Button variant="heroOutline" size="lg" asChild>
              <a href="#how-it-works">
                See How It Works
              </a>
            </Button>
          </div>

          {/* Trust indicators */}
          <div className="flex flex-wrap items-center justify-center gap-8 text-primary-foreground/60 animate-fade-in-up animation-delay-600">
            <div className="flex items-center gap-2">
              <Shield className="w-5 h-5 text-accent" />
              <span className="text-sm">Privacy First</span>
            </div>
            <div className="flex items-center gap-2">
              <Video className="w-5 h-5 text-accent" />
              <span className="text-sm">Real-Time Analysis</span>
            </div>
            <div className="flex items-center gap-2">
              <Wrench className="w-5 h-5 text-accent" />
              <span className="text-sm">Expert Guidance</span>
            </div>
          </div>
        </div>
      </div>

      {/* Bottom gradient fade */}
      <div className="absolute bottom-0 left-0 right-0 h-32 bg-gradient-to-t from-background to-transparent" />
    </section>
  );
}
