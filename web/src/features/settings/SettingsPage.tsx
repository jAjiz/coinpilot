import { useSignOut } from "@/api/queries";
import { describeError } from "@/api/client";
import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { useMe } from "@/features/auth/session";
import { useOnline } from "@/features/shell/useOnline";
import { AutomationBlock } from "./AutomationBlock";
import { KeyBlock } from "./KeyBlock";
import { PauseBlock } from "./PauseBlock";
import { PortfolioBlock } from "./PortfolioBlock";

export function SettingsPage() {
  const me = useMe();
  const online = useOnline();
  const { signOut, pending, error } = useSignOut();
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Settings</h1>
      <PortfolioBlock />
      <AutomationBlock />
      <KeyBlock />
      <PauseBlock />
      <section className="flex flex-col items-start gap-3">
        <p>Signed in as {me.data?.email}.</p>
        <Button
          variant="outline"
          onClick={() => void signOut()}
          disabled={!online || pending}
        >
          Sign out
        </Button>
        <FormError message={error ? describeError(error) : null} />
      </section>
    </div>
  );
}
