import { Droplets, Thermometer, Hammer, Home } from "lucide-react";

const useCases = [
  {
    icon: Droplets,
    title: "Plumbing Issues",
    examples: ["Leaky faucets", "Clogged drains", "Running toilets", "Low water pressure"],
    color: "from-blue-500/20 to-blue-600/10",
  },
  {
    icon: Thermometer,
    title: "HVAC & Appliances",
    examples: ["Thermostat problems", "AC not cooling", "Washer won't drain", "Fridge issues"],
    color: "from-orange-500/20 to-red-500/10",
  },
  {
    icon: Hammer,
    title: "General Repairs",
    examples: ["Drywall patching", "Door adjustments", "Squeaky floors", "Window repairs"],
    color: "from-amber-500/20 to-yellow-500/10",
  },
  {
    icon: Home,
    title: "Renovation Planning",
    examples: ["Load-bearing walls", "Permit requirements", "Material estimates", "Project scoping"],
    color: "from-green-500/20 to-emerald-500/10",
  },
];

export function UseCases() {
  return (
    <section className="py-24 bg-secondary/50">
      <div className="container px-4">
        <div className="text-center mb-16">
          <h2 className="text-3xl sm:text-4xl font-bold text-foreground mb-4">
            Perfect For Every Home Challenge
          </h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            From quick fixes to major renovations, our AI assistant has expertise across 
            all aspects of home maintenance.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6 max-w-6xl mx-auto">
          {useCases.map((useCase) => (
            <div
              key={useCase.title}
              className="relative p-6 rounded-2xl bg-card border border-border overflow-hidden group hover:border-accent/30 transition-all duration-300"
            >
              {/* Background gradient */}
              <div className={`absolute inset-0 bg-gradient-to-br ${useCase.color} opacity-50`} />
              
              <div className="relative z-10">
                {/* Icon */}
                <div className="w-12 h-12 rounded-xl bg-background/80 flex items-center justify-center mb-4 shadow-soft">
                  <useCase.icon className="w-6 h-6 text-accent" />
                </div>

                {/* Title */}
                <h3 className="text-lg font-semibold text-foreground mb-4">
                  {useCase.title}
                </h3>

                {/* Examples */}
                <ul className="space-y-2">
                  {useCase.examples.map((example) => (
                    <li key={example} className="text-sm text-muted-foreground flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-accent" />
                      {example}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
