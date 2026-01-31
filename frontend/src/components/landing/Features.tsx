import { Video, Lightbulb, Wrench, Ruler, MessageCircle, Zap } from "lucide-react";

const features = [
  {
    icon: Video,
    title: "Live Video Analysis",
    description: "Point your camera at any issue. Our AI sees exactly what you see and understands the problem in real-time.",
  },
  {
    icon: Ruler,
    title: "AI Measurements",
    description: "Get accurate measurements and dimensions through your camera. Perfect for renovation planning.",
  },
  {
    icon: Lightbulb,
    title: "Step-by-Step Guidance",
    description: "Receive clear, jargon-free instructions tailored to your skill level. Like having a patient expert beside you.",
  },
  {
    icon: Wrench,
    title: "Tool Recommendations",
    description: "Know exactly what tools you need before you start. No more mid-project hardware store runs.",
  },
  {
    icon: MessageCircle,
    title: "Ask Anything",
    description: "Curious about load-bearing walls or pipe materials? Ask follow-up questions anytime.",
  },
  {
    icon: Zap,
    title: "Instant Help",
    description: "No appointments, no waiting. Get expert advice the moment you need it, 24/7.",
  },
];

export function Features() {
  return (
    <section id="how-it-works" className="py-24 bg-background">
      <div className="container px-4">
        <div className="text-center mb-16">
          <h2 className="text-3xl sm:text-4xl font-bold text-foreground mb-4">
            Everything You Need to{" "}
            <span className="text-gradient-accent">Fix It Yourself</span>
          </h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            Whether it's a leaky faucet, a broken appliance, or planning a full renovation — 
            we've got you covered.
          </p>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8 max-w-6xl mx-auto">
          {features.map((feature, index) => (
            <div
              key={feature.title}
              className="group relative p-8 rounded-2xl bg-card border border-border hover:border-accent/30 transition-all duration-300 hover:shadow-card"
              style={{ animationDelay: `${index * 100}ms` }}
            >
              {/* Icon */}
              <div className="w-14 h-14 rounded-xl bg-accent/10 flex items-center justify-center mb-6 group-hover:bg-accent/20 transition-colors">
                <feature.icon className="w-7 h-7 text-accent" />
              </div>

              {/* Content */}
              <h3 className="text-xl font-semibold text-foreground mb-3">
                {feature.title}
              </h3>
              <p className="text-muted-foreground leading-relaxed">
                {feature.description}
              </p>

              {/* Hover accent */}
              <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-accent/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none" />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
