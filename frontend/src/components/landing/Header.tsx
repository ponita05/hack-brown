import { Button } from "@/components/ui/button";
import { Video, Wrench } from "lucide-react";
import { Link } from "react-router-dom";

export function Header() {
  return (
    <header className="fixed top-0 left-0 right-0 z-50 glass border-b border-border/50">
      <div className="container px-4">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-2">
            <div className="w-9 h-9 rounded-lg bg-accent flex items-center justify-center">
              <Wrench className="w-5 h-5 text-accent-foreground" />
            </div>
            <span className="font-bold text-lg text-foreground">
              Dad<span className="text-accent">OnCall</span>
            </span>
          </Link>

          {/* Navigation */}
          <nav className="hidden md:flex items-center gap-8">
            <a 
              href="#how-it-works" 
              className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              How It Works
            </a>
            <a 
              href="#use-cases" 
              className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              Use Cases
            </a>
          </nav>

          {/* CTA */}
          <Button size="sm" asChild>
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
