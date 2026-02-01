import { Droplets, Thermometer, Hammer, Home } from "lucide-react";

const useCases = [
  {
    icon: Droplets,
    title: "Plumbing Issues",
    examples: ["Leaky faucets", "Clogged drains", "Running toilets", "Low water pressure"],
    color: "from-cyan-500/20 to-blue-500/15",
    iconColor: "text-cyan-600",
  },
  {
    icon: Thermometer,
    title: "HVAC & Appliances",
    examples: ["Thermostat problems", "AC not cooling", "Washer won't drain", "Fridge issues"],
    color: "from-orange-500/20 to-amber-500/15",
    iconColor: "text-orange-600",
  },
  {
    icon: Hammer,
    title: "General Repairs",
    examples: ["Drywall patching", "Door adjustments", "Squeaky floors", "Window repairs"],
    color: "from-amber-500/20 to-yellow-500/15",
    iconColor: "text-amber-600",
  },
  {
    icon: Home,
    title: "Renovation Planning",
    examples: ["Load-bearing walls", "Permit requirements", "Material estimates", "Project scoping"],
    color: "from-emerald-500/20 to-green-500/15",
    iconColor: "text-emerald-600",
  },
];

export function UseCases() {
  return (
    <section className="py-24 bg-gradient-to-br from-orange-50 via-amber-50/50 to-orange-50">
      <div className="container px-4">
        <div className="text-center mb-16">
          <h2 className="text-3xl sm:text-4xl md:text-5xl font-black text-gray-900 mb-5 tracking-tight leading-tight uppercase">
            Perfect For Every Home Challenge
          </h2>
          <p className="text-lg sm:text-xl text-gray-700 max-w-2xl mx-auto leading-relaxed font-bold">
            From quick fixes to major renovations, our AI assistant has expertise across
            all aspects of home maintenance.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6 max-w-6xl mx-auto">
          {useCases.map((useCase) => (
            <div
              key={useCase.title}
              className="relative p-6 rounded-2xl bg-white border-2 border-orange-100 overflow-hidden group hover:border-orange-300 hover:shadow-xl hover:shadow-orange-500/10 transition-all duration-300"
            >
              {/* Background gradient */}
              <div className={`absolute inset-0 bg-gradient-to-br ${useCase.color} opacity-60`} />

              <div className="relative z-10">
                {/* Icon */}
                <div className="w-12 h-12 rounded-xl bg-white/90 flex items-center justify-center mb-4 shadow-md">
                  <useCase.icon className={`w-6 h-6 ${useCase.iconColor}`} />
                </div>

                {/* Title */}
                <h3 className="text-lg font-extrabold text-gray-900 mb-4 tracking-tight uppercase">
                  {useCase.title}
                </h3>

                {/* Examples */}
                <ul className="space-y-2">
                  {useCase.examples.map((example) => (
                    <li key={example} className="text-sm text-gray-700 flex items-center gap-2 font-semibold">
                      <span className="w-1.5 h-1.5 rounded-full bg-orange-500" />
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
