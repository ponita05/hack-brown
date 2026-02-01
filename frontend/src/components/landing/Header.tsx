import { Button } from "@/components/ui/button";
import { Video, Wrench } from "lucide-react";
import { Link } from "react-router-dom";

export function Header() {
  return (
    <header className="fixed top-0 left-0 right-0 z-50 bg-gradient-to-r from-orange-600 via-orange-500 to-orange-600 border-b border-orange-700/30 shadow-lg shadow-orange-500/20">
      <div className="container px-4">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-2 group">
            <div className="w-9 h-9 rounded-lg bg-white/95 flex items-center justify-center shadow-md group-hover:shadow-lg transition-shadow">
              <Wrench className="w-5 h-5 text-orange-600" />
            </div>
            <span className="font-black text-lg text-white tracking-tight">
              Handy<span className="text-orange-100">Daddy</span>
            </span>
          </Link>

          {/* Navigation */}
          <nav className="hidden md:flex items-center gap-8">
            <a
              href="#how-it-works"
              className="text-sm font-bold text-orange-50 hover:text-white transition-colors uppercase tracking-wide"
            >
              How It Works
            </a>
            <a
              href="#use-cases"
              className="text-sm font-bold text-orange-50 hover:text-white transition-colors uppercase tracking-wide"
            >
              Use Cases
            </a>
          </nav>

          {/* CTA */}
          <Button size="sm" asChild className="bg-white text-orange-600 hover:bg-orange-50 font-black shadow-md hover:shadow-lg transition-all uppercase tracking-wide">
            <Link to="/chat">
              <Video className="w-4 h-4" />
              Start Chat
            </Link>
          </Button>
        </div>
      </div>
    </header>
  );
}
