import { cookies } from "next/headers";
import Link from "next/link";

export async function Header({ active }: { active: "chat" | "documents" | "dashboard" }) {
  const admin = (await cookies()).has("sentinel_admin");
  const link = (href: string, label: string, isActive: boolean) => (
    <Link
      href={href}
      aria-current={isActive ? "page" : undefined}
      className="rounded-xl px-4 py-2 text-sm text-zinc-400 hover:text-zinc-100 aria-[current=page]:bg-zinc-900 aria-[current=page]:text-zinc-100"
    >
      {label}
    </Link>
  );

  return (
    <header className="flex flex-wrap items-center justify-between gap-4">
      <div>
        <h1 className="text-4xl font-bold">Sentinel</h1>
        <p className="mt-2 text-zinc-400">AI assistant for the Apache Superset codebase.</p>
      </div>
      <nav aria-label="Primary" className="flex gap-1">
        {link("/", "Chat", active === "chat")}
        {link("/documents", "Documents", active === "documents")}
        {admin && link("/dashboard", "Dashboard", active === "dashboard")}
      </nav>
    </header>
  );
}
