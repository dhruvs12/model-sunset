import OpenAI from "openai";

const client = new OpenAI();

// Summarize a ticket thread for the weekly support digest.
export async function summarize(thread: string): Promise<string> {
  const response = await client.chat.completions.create({
    model: "gpt-4o-2024-11-20",
    messages: [
      { role: "system", content: "Summarize this support thread in two sentences for an engineer." },
      { role: "user", content: thread },
    ],
  });
  return response.choices[0].message.content ?? "";
}
