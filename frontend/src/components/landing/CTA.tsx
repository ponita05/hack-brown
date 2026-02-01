import { Button } from "@/components/ui/button";
import { Video, ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

export function CTA() {
  return (
    <section className="py-24 bg-gradient-to-r from-orange-600 via-orange-500 to-orange-600 relative overflow-hidden">
      {/* Ambient effects */}
      <div className="absolute inset-0 bg-gradient-to-br from-orange-400/20 via-transparent to-amber-400/20" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-white/10 rounded-full blur-3xl" />

      <div className="container px-4 relative z-10">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl sm:text-4xl md:text-5xl lg:text-6xl font-black text-white mb-6 tracking-tight leading-tight uppercase">
            Ready to Fix It{" "}
            <span className="text-orange-100 font-black">Like a Pro?</span>
          </h2>
          <p className="text-lg sm:text-xl text-orange-50 mb-10 max-w-xl mx-auto leading-relaxed font-bold">
            Stop waiting for expensive contractors. Get instant expert guidance
            for any home repair or renovation project.
          </p>

          <Button
            size="xl"
            asChild
            className="bg-white text-orange-600 hover:bg-orange-50 font-bold shadow-2xl shadow-orange-900/30 px-8"
          >
            <Link to="/chat">
              <Video className="w-5 h-5" />
              Start Your First Video Chat
              <ArrowRight className="w-5 h-5" />
            </Link>
          </Button>

          <p className="mt-6 text-sm text-orange-100 font-extrabold tracking-widest uppercase">
            No sign-up required • Free to try • Available 24/7
          </p>
        </div>
      </div>
    </section>
  );
}
