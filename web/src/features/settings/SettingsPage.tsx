import { useMe } from "@/features/auth/session";

export function SettingsPage() {
  const me = useMe();
  return (
    <>
      <h1 className="text-xl font-semibold">Settings</h1>
      <p>Signed in as {me.data?.email}.</p>
    </>
  );
}
