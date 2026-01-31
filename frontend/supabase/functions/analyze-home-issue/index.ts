import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-supabase-client-platform, x-supabase-client-platform-version, x-supabase-client-runtime, x-supabase-client-runtime-version",
};

const SYSTEM_PROMPT = `You are DadOnCall, a friendly and knowledgeable home repair assistant. You're like a patient dad who knows everything about home maintenance, plumbing, appliances, and renovations.

Your personality:
- Warm, encouraging, and patient - never condescending
- Explain things clearly for beginners but can go deeper if asked
- Safety-conscious - always warn about potential hazards
- Practical - focus on what the user can actually do themselves vs when to call a pro

When analyzing images:
- Identify the specific issue you see
- Explain what's likely causing the problem
- Provide step-by-step instructions to fix it
- List any tools or materials needed
- Estimate difficulty level (Easy/Medium/Hard)
- Mention safety precautions
- Suggest when to call a professional instead

For renovation questions:
- Help identify load-bearing vs non-load-bearing walls
- Discuss permit requirements when relevant
- Provide rough cost estimates when possible
- Break down complex projects into phases

Always be encouraging - remind users that many home repairs are doable with patience and the right guidance!`;

interface Message {
  role: "user" | "assistant";
  content: string;
  image?: string;
}

serve(async (req) => {
  // Handle CORS preflight requests
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: corsHeaders });
  }

  try {
    const LOVABLE_API_KEY = Deno.env.get("LOVABLE_API_KEY");
    if (!LOVABLE_API_KEY) {
      console.error("LOVABLE_API_KEY is not configured");
      throw new Error("LOVABLE_API_KEY is not configured");
    }

    const { message, image, history = [] } = await req.json();
    console.log("Received request:", { message, hasImage: !!image, historyLength: history.length });

    // Build messages array for the API
    const messages: any[] = [
      { role: "system", content: SYSTEM_PROMPT },
    ];

    // Add conversation history (without images to save tokens)
    for (const msg of history) {
      messages.push({
        role: msg.role,
        content: msg.content,
      });
    }

    // Add current user message with optional image
    if (image) {
      messages.push({
        role: "user",
        content: [
          {
            type: "text",
            text: message || "What do you see in this image? Help me identify and fix any issues.",
          },
          {
            type: "image_url",
            image_url: {
              url: image,
            },
          },
        ],
      });
    } else {
      messages.push({
        role: "user",
        content: message,
      });
    }

    console.log("Sending request to Lovable AI Gateway...");

    const response = await fetch("https://ai.gateway.lovable.dev/v1/chat/completions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${LOVABLE_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "google/gemini-2.5-flash",
        messages,
        max_tokens: 2048,
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error("AI gateway error:", response.status, errorText);

      if (response.status === 429) {
        return new Response(
          JSON.stringify({ error: "Rate limit exceeded. Please try again in a moment." }),
          {
            status: 429,
            headers: { ...corsHeaders, "Content-Type": "application/json" },
          }
        );
      }

      if (response.status === 402) {
        return new Response(
          JSON.stringify({ error: "AI credits exhausted. Please add more credits to continue." }),
          {
            status: 402,
            headers: { ...corsHeaders, "Content-Type": "application/json" },
          }
        );
      }

      throw new Error(`AI gateway error: ${response.status}`);
    }

    const data = await response.json();
    console.log("Received response from AI gateway");

    const assistantMessage = data.choices?.[0]?.message?.content || "I couldn't analyze that. Could you try again with a clearer image or more details?";

    return new Response(
      JSON.stringify({ response: assistantMessage }),
      {
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      }
    );
  } catch (error) {
    console.error("Error in analyze-home-issue function:", error);
    return new Response(
      JSON.stringify({ 
        error: error instanceof Error ? error.message : "An unexpected error occurred" 
      }),
      {
        status: 500,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      }
    );
  }
});
