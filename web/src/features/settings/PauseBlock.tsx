import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, describeError, unwrap } from "@/api/client";
import { configKey, useConfig } from "@/api/queries";
import { sessionGuard } from "@/api/signOut";
import { FormError } from "@/components/FormError";
import { Switch } from "@/components/ui/switch";
import { useOnline } from "@/features/shell/useOnline";

export function PauseBlock() {
  const client = useQueryClient();
  const config = useConfig();
  const online = useOnline();
  const save = useMutation({
    mutationFn: (paused: boolean) =>
      unwrap(api.PATCH("/api/config", { body: { paused } })),
    onMutate: () => sessionGuard(client),
    onSuccess: (data, _, stillSame) => {
      if (stillSame()) client.setQueryData(configKey, data);
    },
  });

  if (!config.data) return null;

  return (
    <section className="flex flex-col items-start gap-3">
      <div className="flex items-center gap-3">
        <Switch
          aria-labelledby="pause-label"
          checked={config.data.paused}
          disabled={!online || save.isPending}
          onCheckedChange={(paused) => save.mutate(paused)}
        />
        <span id="pause-label" className="text-lg font-semibold">
          Pause everything
        </span>
      </div>
      <p>
        While paused, nothing runs on schedule. Invest now and Rebalance now
        still work. On resume, the next runs are scheduled from then: nothing
        missed while paused runs.
      </p>
      <FormError message={save.isError ? describeError(save.error) : null} />
    </section>
  );
}
