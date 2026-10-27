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
  anchorFromInput,
  anchorInput,
  cadencePatch,
  checkCustom,
  investFields,
  isUsableDate,
  localDate,
  rebalanceFields,
  sameFields,
  type CadenceFields,
  type CustomErrors,
  type CadenceForm,
  type InvestChoice,
  type RebalanceChoice,
} from "@/lib/cadence";
import { compare, parseDecimal } from "@/lib/decimal";
import { ordinal, shortMonthNote, weekdayName } from "@/lib/summary";
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

const NO_CUSTOM: CustomErrors = { days: null, months: null, anchor: null };

const SELECT_CLASS =
  "h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-base md:text-sm";

function investHint(date: string, choice: InvestChoice): string | null {
  if (date === "") return null;
  if (choice === "weekly") return `Runs every ${weekdayName(date)}.`;
  if (choice === "monthly") {
    const day = Number(date.split("-")[2]);
    return `Runs on the ${ordinal(day)} of each month${shortMonthNote(day)}.`;
  }
  return null;
}

// Days and months are read from the text: "1.5" or "" is not a whole number,
// so it becomes NaN and checkCustom refuses it.
function wholeNumber(text: string): number {
  return /^\d+$/.test(text) ? Number(text) : NaN;
}

function CustomFields({
  fields,
  errors,
  onChange,
}: {
  fields: CadenceFields;
  errors: CustomErrors;
  onChange: (fields: CadenceFields) => void;
}) {
  const id = useId();
  const [days, setDays] = useState(String(fields.interval_days ?? 0));
  const [months, setMonths] = useState(String(fields.interval_months ?? 0));
  const [starts, setStarts] = useState(anchorInput(fields.cadence_anchor));
  return (
    <>
      <Label htmlFor={`${id}-mode`}>Repeats</Label>
      <select
        id={`${id}-mode`}
        className={SELECT_CLASS}
        value={fields.mode}
        onChange={(event) =>
          onChange({
            ...fields,
            mode: event.target.value as "MIN" | "INTERVAL",
          })
        }
      >
        <option value="MIN">Every 15 minutes</option>
        <option value="INTERVAL">On an interval</option>
      </select>
      {fields.mode === "INTERVAL" && (
        <>
          <Label htmlFor={`${id}-days`}>Days</Label>
          <Input
            id={`${id}-days`}
            inputMode="numeric"
            value={days}
            onChange={(event) => {
              setDays(event.target.value);
              onChange({
                ...fields,
                interval_days: wholeNumber(event.target.value),
              });
            }}
          />
          <FormError message={errors.days} />
          <Label htmlFor={`${id}-months`}>Months</Label>
          <Input
            id={`${id}-months`}
            inputMode="numeric"
            value={months}
            onChange={(event) => {
              setMonths(event.target.value);
              onChange({
                ...fields,
                interval_months: wholeNumber(event.target.value),
              });
            }}
          />
          <FormError message={errors.months} />
          <Label htmlFor={`${id}-starts`}>Starts</Label>
          <Input
            id={`${id}-starts`}
            type="datetime-local"
            value={starts}
            onChange={(event) => {
              setStarts(event.target.value);
              onChange({
                ...fields,
                cadence_anchor: anchorFromInput(event.target.value),
              });
            }}
          />
          <FormError message={errors.anchor} />
        </>
      )}
    </>
  );
}

function CadencePick<C extends string>({
  label,
  datePrefix,
  options,
  form,
  initialCustom,
  needsDate,
  error,
  customErrors,
  hint,
  onChange,
}: {
  label: string;
  datePrefix: string;
  options: [C, string][];
  form: CadenceForm<C>;
  initialCustom: CadenceFields | null;
  needsDate: (choice: C) => boolean;
  error: string | null;
  customErrors: CustomErrors;
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
              ? { kind: "custom", fields: initialCustom! }
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
        {initialCustom !== null && <option value="custom">Custom</option>}
      </select>
      {form.kind === "custom" && (
        <>
          <p className="text-sm text-muted-foreground">
            Set through the API. Edit its fields, or choose another option.
          </p>
          <CustomFields
            fields={form.fields}
            errors={customErrors}
            onChange={(fields) => onChange({ kind: "custom", fields })}
          />
        </>
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
  investCustom: CustomErrors;
  rebalanceCustom: CustomErrors;
};
const NO_ERRORS: Errors = {
  investDate: null,
  rebalanceDate: null,
  drift: null,
  minimum: null,
  investCustom: NO_CUSTOM,
  rebalanceCustom: NO_CUSTOM,
};

function cadenceBody<C extends string>(
  prefix: "invest" | "rebalance",
  form: CadenceForm<C>,
  initial: CadenceForm<C>,
  fieldsOf: (
    form: Extract<CadenceForm<C>, { kind: "choice" }>,
  ) => CadenceFields,
) {
  if (form.kind === "choice") return cadencePatch(prefix, fieldsOf(form));
  if (initial.kind === "custom" && sameFields(form.fields, initial.fields)) {
    return {};
  }
  return cadencePatch(prefix, form.fields);
}

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
  const customInvest =
    initial.invest.kind === "custom" ? initial.invest.fields : null;
  const customRebalance =
    initial.rebalance.kind === "custom" ? initial.rebalance.fields : null;

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
        !isUsableDate(invest.date)
          ? NO_DATE
          : null,
      rebalanceDate:
        rebalance.kind === "choice" && !isUsableDate(rebalance.date)
          ? NO_DATE
          : null,
      drift: drift === null || compare(drift, "100") > 0 ? INVALID_DRIFT : null,
      minimum: minimum === null ? INVALID_MINIMUM : null,
      investCustom:
        invest.kind === "custom" ? checkCustom(invest.fields) : NO_CUSTOM,
      rebalanceCustom:
        rebalance.kind === "custom" ? checkCustom(rebalance.fields) : NO_CUSTOM,
    };
    setErrors(found);
    const flat = [
      found.investDate,
      found.rebalanceDate,
      found.drift,
      found.minimum,
      ...Object.values(found.investCustom),
      ...Object.values(found.rebalanceCustom),
    ];
    if (flat.some((error) => error !== null)) return;

    // A custom cadence is sent only when one of its fields changed.
    const body = {
      ...cadenceBody("invest", invest, initial.invest, (form) =>
        investFields(form.choice, form.date),
      ),
      ...cadenceBody("rebalance", rebalance, initial.rebalance, (form) =>
        rebalanceFields(form.choice, form.date),
      ),
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
        initialCustom={customInvest}
        needsDate={(choice) => choice !== "asap"}
        error={errors.investDate}
        customErrors={errors.investCustom}
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
        initialCustom={customRebalance}
        needsDate={() => true}
        error={errors.rebalanceDate}
        customErrors={errors.rebalanceCustom}
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
