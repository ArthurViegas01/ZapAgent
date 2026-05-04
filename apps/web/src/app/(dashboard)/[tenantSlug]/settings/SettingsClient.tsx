"use client";

import { useFormState, useFormStatus } from "react-dom";
import { updateSettings } from "./actions";

interface TenantSettings {
  agent_persona?: string;
  confidence_threshold?: number;
  business_hours?: { open?: string; close?: string };
}

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded-lg bg-brand-600 px-5 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
    >
      {pending ? "Salvando…" : "Salvar configurações"}
    </button>
  );
}

export default function SettingsClient({
  tenantSlug,
  tenantName,
  settings,
}: {
  tenantSlug: string;
  tenantName: string;
  settings: TenantSettings;
}) {
  const boundAction = updateSettings.bind(null, tenantSlug);
  const [state, formAction] = useFormState(boundAction, null);

  const defaultConfidence = settings.confidence_threshold ?? 0.6;

  return (
    <form action={formAction} className="flex flex-col gap-8 max-w-2xl">
      {/* Company */}
      <section className="rounded-xl border border-slate-200 bg-white p-6">
        <h2 className="mb-4 text-base font-semibold text-slate-800">Empresa</h2>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="name" className="text-sm font-medium text-slate-700">
              Nome da empresa <span className="text-red-500">*</span>
            </label>
            <input
              id="name"
              name="name"
              type="text"
              required
              defaultValue={tenantName}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
            />
          </div>
        </div>
      </section>

      {/* Agent */}
      <section className="rounded-xl border border-slate-200 bg-white p-6">
        <h2 className="mb-1 text-base font-semibold text-slate-800">Agente</h2>
        <p className="mb-4 text-sm text-slate-400">
          Defina a personalidade e limites do assistente.
        </p>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="persona" className="text-sm font-medium text-slate-700">
              Persona do agente
            </label>
            <textarea
              id="persona"
              name="persona"
              rows={4}
              defaultValue={settings.agent_persona ?? ""}
              placeholder="Ex: Você é o atendente virtual da Clínica Saúde Total. Seja simpático, profissional e responda apenas dúvidas relacionadas aos nossos serviços."
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
            />
            <p className="text-xs text-slate-400">
              Instrução de sistema enviada ao modelo antes de cada resposta.
            </p>
          </div>

          <div className="flex flex-col gap-2">
            <label htmlFor="confidence_threshold" className="text-sm font-medium text-slate-700">
              Limiar de confiança: <span className="font-mono text-brand-600">{Math.round(defaultConfidence * 100)}%</span>
            </label>
            <input
              id="confidence_threshold"
              name="confidence_threshold"
              type="range"
              min="0"
              max="1"
              step="0.05"
              defaultValue={defaultConfidence}
              className="w-full accent-brand-600"
              onInput={(e) => {
                const label = e.currentTarget.parentElement?.querySelector("label");
                if (label) {
                  const val = parseFloat((e.target as HTMLInputElement).value);
                  label.innerHTML = `Limiar de confiança: <span class="font-mono text-brand-600">${Math.round(val * 100)}%</span>`;
                }
              }}
            />
            <div className="flex justify-between text-xs text-slate-400">
              <span>0% — Sempre responde</span>
              <span>100% — Nunca responde</span>
            </div>
            <p className="text-xs text-slate-400">
              Abaixo desse limiar o agente transfere para um humano.
            </p>
          </div>
        </div>
      </section>

      {/* Business hours */}
      <section className="rounded-xl border border-slate-200 bg-white p-6">
        <h2 className="mb-1 text-base font-semibold text-slate-800">Horário de atendimento</h2>
        <p className="mb-4 text-sm text-slate-400">
          Fora desse horário o agente informa que não está disponível.
        </p>
        <div className="grid grid-cols-2 gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="business_hours_open" className="text-sm font-medium text-slate-700">
              Abertura
            </label>
            <input
              id="business_hours_open"
              name="business_hours_open"
              type="time"
              defaultValue={settings.business_hours?.open ?? "09:00"}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="business_hours_close" className="text-sm font-medium text-slate-700">
              Fechamento
            </label>
            <input
              id="business_hours_close"
              name="business_hours_close"
              type="time"
              defaultValue={settings.business_hours?.close ?? "18:00"}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
            />
          </div>
        </div>
      </section>

      {/* Feedback */}
      {state?.error && (
        <p className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-600">{state.error}</p>
      )}
      {state?.ok && (
        <p className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          Configurações salvas com sucesso!
        </p>
      )}

      <div>
        <SubmitButton />
      </div>
    </form>
  );
}
