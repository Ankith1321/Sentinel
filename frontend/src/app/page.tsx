import { Chat } from "@/components/Chat";
import { Header } from "@/components/Header";

export default function Home() {
  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-5xl space-y-8 px-6 py-10">
        <Header active="chat" />
        <Chat />
      </div>
    </main>
  );
}
