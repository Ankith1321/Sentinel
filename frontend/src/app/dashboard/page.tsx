import { cookies } from "next/headers";
import { AdminSignIn } from "@/components/AdminSignIn";
import { Dashboard } from "@/components/Dashboard";
import { Header } from "@/components/Header";

export default async function DashboardPage() {
  const signedIn = (await cookies()).has("sentinel_admin");

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-6xl space-y-8 px-6 py-10">
        <Header active="dashboard" />
        {signedIn ? <Dashboard /> : <AdminSignIn />}
      </div>
    </main>
  );
}
