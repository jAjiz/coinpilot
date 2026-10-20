import { useId, useState } from "react";
import { api, describeError, unwrap } from "@/api/client";
import type { Config } from "@/api/queries";
import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useOnline } from "@/features/shell/useOnline";
import {
  cadencePatch,
  investFields,
  localDate,
  rebalanceFields,
  type CadenceForm,
  type InvestChoice,
  type RebalanceChoice,
} from "@/lib/cadence";
import { compare, parseDecimal } from "@/lib/decimal";
import { ordinal, weekdayName } from "@/lib/summary";
import type { AutomationValues } from "./automationValues";

const INVEST_OPTIONS: [InvestChoice, string][] = [
  ["asap", "As soon as possible (every 15 min)"],
  ["daily", "Daily"],
  ["weekly", "Weekly"],
  ["monthly", "Monthly"],
];
const REBALANCE_OPTIONS: [RebalanceChoice, string][] = [
  ["monthly", "Monthly"],
  ["quarterly", "Quarterly"],
  ["half-yearly", "Half-yearly"],
  ["yearly", "Yearly"],
];

const INVALID_DRIFT =
  "Enter a percentage from 0 to 100, with up to one decimal.";
const INVALID_MINIMUM = "Enter an amount of 0 or more, with up to one decimal.";
const NO_DATE = "Choose a start date.";

const SELECT_CLASS =
  "h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-base md:text-sm";

function investHint(date: string, choice: InvestChoice): string | null {
  if (date === "") return null;
  if (choice === "weekly") return `Runs every ${weekdayName(date)}.`;
  if (choice === "monthly") {
    const day = Number(date.split("-")[2]);
    return `Runs on the ${ordinal(day)} of each month${
      day >= 29 ? "; in a shorter month, on its last day" : ""
    }.`;
  }
  return null;
}

function CadencePick<C extends string>({
  label,
  datePrefix,
  options,
  form,
  hasCustom,
  needsDate,
  error,
  hint,
  onChange,
}: {
  label: string;
  datePrefix: string;
  options: [C, string][];
  form: CadenceForm<C>;
  hasCustom: boolean;
  needsDate: (choice: C) => boolean;
  error: string | null;
  hint: string | null;
  onChange: (form: CadenceForm<C>) => void;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={`${id}-cadence`}>{label}</Label>
      <select
        id={`${id}-cadence`}
        className={SELECT_CLASS}
        value={form.kind === "custom" ? "custom" : form.choice}
        onChange={(event) => {
          const value = event.target.value;
          onChange(
            value === "custom"
              ? { kind: "custom" }
              : {
                  kind: "choice",
                  choice: value as C,
                  date:
                    form.kind === "choice" ? form.date : localDate(new Date()),
                },
          );
        }}
      >
        {options.map(([value, text]) => (
          <option key={value} value={value}>
            {text}
          </option>
        ))}
        {hasCustom && <option value="custom">Custom</option>}
      </select>
      {form.kind === "custom" && (
        <p className="text-sm text-muted-foreground">
          Set through the API; kept unless you choose another option.
        </p>
      )}
      {form.kind === "choice" && needsDate(form.choice) && (
        <>
          <Label htmlFor={`${id}-date`}>Start date</Label>
          <Input
            id={`${id}-date`}
            type="date"
            aria-label={`${datePrefix} start date`}
            value={form.date}
            onChange={(event) =>
              onChange({ ...form, date: event.target.value })
            }
          />
          <FormError message={error} />
        </>
      )}
      {hint !== null && <p className="text-sm text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
  children,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  children: string;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-3">
        <Switch
          aria-labelledby={id}
          checked={checked}
          onCheckedChange={onChange}
        />
        <span id={id} className="font-medium">
          {label}
        </span>
      </div>
      <p className="text-sm text-muted-foreground">{children}</p>
    </div>
  );
}

function Threshold({
  label,
  suffix,
  value,
  onChange,
  error,
  children,
}: {
  label: string;
  suffix: string;
  value: string;
  onChange: (value: string) => void;
  error: string | null;
  children: string;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-2">
        <Input
          id={id}
          inputMode="decimal"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
        <span aria-hidden>{suffix}</span>
      </div>
      <p className="text-sm text-muted-foreground">{children}</p>
      <FormError message={error} />
    </div>
  );
}

type Errors = {
  investDate: string | null;
  rebalanceDate: string | null;
  drift: string | null;
  minimum: string | null;
};
const NO_ERRORS: Errors = {
  investDate: null,
  rebalanceDate: null,
  drift: null,
  minimum: null,
};

export function AutomationForm({
  config,
  initial,
  onSaved,
}: {
  config: Config;
  initial: AutomationValues;
  onSaved: () => Promise<void>;
}) {
  const online = useOnline();
  const [values, setValues] = useState(initial);
  const [errors, setErrors] = useState(NO_ERRORS);
  const [failure, setFailure] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  // "Custom" stays an option for as long as the form was opened with one.
  const customInvest = initial.invest.kind === "custom";
  const customRebalance = initial.rebalance.kind === "custom";

  const set = (patch: Partial<AutomationValues>) =>
    setValues((current) => ({ ...current, ...patch }));

  async function save() {
    setFailure(null);
    const { invest, rebalance } = values;
    const drift = parseDecimal(values.min_drift_pct, 1);
    const minimum = parseDecimal(values.min_order_fiat, 1);
    const found: Errors = {
      investDate:
        invest.kind === "choice" &&
        invest.choice !== "asap" &&
        invest.date === ""
          ? NO_DATE
          : null,
      rebalanceDate:
        rebalance.kind === "choice" && rebalance.date === "" ? NO_DATE : null,
      drift: drift === null || compare(drift, "100") > 0 ? INVALID_DRIFT : null,
      minimum: minimum === null ? INVALID_MINIMUM : null,
    };
    setErrors(found);
    if (Object.values(found).some((error) => error !== null)) return;

    // A custom cadence the user left alone is not sent.
    const body = {
      ...(invest.kind === "choice"
        ? cadencePatch("invest", investFields(invest.choice, invest.date))
        : {}),
      ...(rebalance.kind === "choice"
        ? cadencePatch(
            "rebalance",
            rebalanceFields(rebalance.choice, rebalance.date),
          )
        : {}),
      invest_cash_enabled: values.invest_cash_enabled,
      cash_rebalance_enabled: values.cash_rebalance_enabled,
      auto_rebalance_enabled: values.auto_rebalance_enabled,
      min_drift_pct: drift!,
      min_order_fiat: minimum!,
    };
    setSending(true);
    try {
      await unwrap(api.PATCH("/api/config", { body }));
      // Stays disabled while the step advances: a second click would send again.
      await onSaved();
    } catch (error) {
      setFailure(describeError(error));
      setSending(false);
    }
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      className="flex flex-col gap-6"
    >
      <CadencePick<InvestChoice>
        label="Invest cadence"
        datePrefix="Invest"
        options={INVEST_OPTIONS}
        form={values.invest}
        hasCustom={customInvest}
        needsDate={(choice) => choice !== "asap"}
        error={errors.investDate}
        hint={
          values.invest.kind === "choice"
            ? investHint(values.invest.date, values.invest.choice)
            : null
        }
        onChange={(invest) => set({ invest })}
      />
      <CadencePick<RebalanceChoice>
        label="Rebalance cadence"
        datePrefix="Rebalance"
        options={REBALANCE_OPTIONS}
        form={values.rebalance}
        hasCustom={customRebalance}
        needsDate={() => true}
        error={errors.rebalanceDate}
        hint={null}
        onChange={(rebalance) => set({ rebalance })}
      />
      <Toggle
        label="Invest free cash automatically"
        checked={values.invest_cash_enabled}
        onChange={(invest_cash_enabled) => set({ invest_cash_enabled })}
      >
        {`At each invest run, free ${config.fiat} is invested toward your targets. Off, you invest it yourself from Home.`}
      </Toggle>
      <Toggle
        label="When investing, buy the most underweight assets first"
        checked={values.cash_rebalance_enabled}
        onChange={(cash_rebalance_enabled) => set({ cash_rebalance_enabled })}
      >
        Off, cash is spread in proportion to the targets.
      </Toggle>
      <Toggle
        label="Rebalance automatically, without asking"
        checked={values.auto_rebalance_enabled}
        onChange={(auto_rebalance_enabled) => set({ auto_rebalance_enabled })}
      >
        Off, a rebalance waits for your approval. On, it sells and buys as soon
        as it is found.
      </Toggle>
      <Threshold
        label="Rebalance only when an asset drifts more than"
        suffix="%"
        value={values.min_drift_pct}
        onChange={(min_drift_pct) => set({ min_drift_pct })}
        error={errors.drift}
      >
        Smaller differences are left alone, so they cost no fees.
      </Threshold>
      <Threshold
        label="Skip orders smaller than"
        suffix={config.fiat}
        value={values.min_order_fiat}
        onChange={(min_order_fiat) => set({ min_order_fiat })}
        error={errors.minimum}
      >
        Kraken&apos;s own minimum always applies.
      </Threshold>
      <FormError message={failure} />
      <Button type="submit" disabled={sending || !online}>
        Save and continue
      </Button>
    </form>
  );
}
