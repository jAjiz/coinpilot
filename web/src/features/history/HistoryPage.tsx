import { useMe } from "@/features/auth/session";

export function HistoryPage() {
  const me = useMe();
  return (
    <>
      <h1 className="text-xl font-semibold">History</h1>
      <p>Signed in as {me.data?.email}.</p>
    </>
  );
}
