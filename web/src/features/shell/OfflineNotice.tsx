import { useOnline } from "./useOnline";

export function OfflineNotice() {
  if (useOnline()) return null;
  return (
    <p role="status" className="bg-muted px-4 py-2 text-center text-sm">
      You&apos;re offline. Nothing can be sent until the connection is back.
    </p>
  );
}
