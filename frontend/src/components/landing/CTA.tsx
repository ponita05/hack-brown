import { Button } from "@/components/ui/button";
import { Video, ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

export function CTA() {
  return (
    <section className="py-24 bg-gradient-hero relative overflow-hidden">
      {/* Ambient effects */}
      <div className="absolute inset-0 bg-gradient-glow opacity-30" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-accent/10 rounded-full blur-3xl" />

      <div className="container px-4 relative z-10">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold text-primary-foreground mb-6">
            Ready to Fix It{" "}
            <span className="text-gradient-accent">Like a Pro?</span>
          </h2>
          <p className="text-lg text-primary-foreground/70 mb-10 max-w-xl mx-auto">
            Stop waiting for expensive contractors. Get instant expert guidance 
            for any home repair or renovation project.
          </p>
          
          <Button variant="hero" size="xl" asChild>
            <Link to="/chat">
              <Video className="w-5 h-5" />
              Start Your First Video Chat
              <ArrowRight className="w-5 h-5" />
            </Link>
          </Button>

          <p className="mt-6 text-sm text-primary-foreground/50">
            No sign-up required • Free to try • Available 24/7
          </p>
        </div>
      </div>
    </section>
  );
}
