import { useMe } from "@/features/auth/session";

export function DashboardPage() {
  const me = useMe();
  return (
    <>
      <h1 className="text-xl font-semibold">Home</h1>
      <p>Signed in as {me.data?.email}.</p>
    </>
  );
}
