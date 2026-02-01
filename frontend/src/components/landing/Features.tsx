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
    <section id="how-it-works" className="py-24 bg-white">
      <div className="container px-4">
        <div className="text-center mb-16">
          <h2 className="text-3xl sm:text-4xl md:text-5xl font-black text-gray-900 mb-5 tracking-tight leading-tight uppercase">
            Everything You Need to{" "}
            <span className="bg-gradient-to-r from-orange-600 to-amber-500 bg-clip-text text-transparent font-black">Fix It Yourself</span>
          </h2>
          <p className="text-lg sm:text-xl text-gray-700 max-w-2xl mx-auto leading-relaxed font-bold">
            Whether it's a leaky faucet, a broken appliance, or planning a full renovation —
            we've got you covered.
          </p>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8 max-w-6xl mx-auto">
          {features.map((feature, index) => (
            <div
              key={feature.title}
              className="group relative p-8 rounded-2xl bg-white border-2 border-orange-100 hover:border-orange-300 transition-all duration-300 hover:shadow-xl hover:shadow-orange-500/10"
              style={{ animationDelay: `${index * 100}ms` }}
            >
              {/* Icon */}
              <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-orange-500/10 to-amber-500/10 flex items-center justify-center mb-6 group-hover:from-orange-500/20 group-hover:to-amber-500/20 transition-all shadow-sm">
                <feature.icon className="w-7 h-7 text-orange-600" />
              </div>

              {/* Content */}
              <h3 className="text-xl font-extrabold text-gray-900 mb-3 tracking-tight uppercase">
                {feature.title}
              </h3>
              <p className="text-gray-700 leading-relaxed font-semibold">
                {feature.description}
              </p>

              {/* Hover accent */}
              <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-orange-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none" />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
