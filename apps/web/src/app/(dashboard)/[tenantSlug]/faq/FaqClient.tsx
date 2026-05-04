"use client";

import { useFormState, useFormStatus } from "react-dom";
import { useState, useTransition } from "react";
import { createFaq, deleteFaq, toggleFaq } from "./actions";

interface FaqItem {
  id: string;
  question: string;
  answer: string;
  is_active: boolean;
  created_at: string;
}

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
    >
      {pending ? "Salvando…" : "Adicionar"}
    </button>
  );
}

export default function FaqClient({
  tenantSlug,
  initialItems,
}: {
  tenantSlug: string;
  initialItems: FaqItem[];
}) {
  const [items, setItems] = useState<FaqItem[]>(initialItems);
  const [showForm, setShowForm] = useState(items.length === 0);
  const [isPending, startTransition] = useTransition();

  const boundCreate = createFaq.bind(null, tenantSlug);
  const [state, formAction] = useFormState(boundCreate, null);

  function handleDelete(id: string) {
    startTransition(async () => {
      await deleteFaq(tenantSlug, id);
      setItems((prev) => prev.filter((i) => i.id !== id));
    });
  }

  function handleToggle(id: string, current: boolean) {
    startTransition(async () => {
      await toggleFaq(tenantSlug, id, !current);
      setItems((prev) =>
        prev.map((i) => (i.id === id ? { ...i, is_active: !current } : i))
      );
    });
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Add form */}
      {showForm ? (
        <div className="rounded-xl border border-brand-200 bg-brand-50 p-5">
          <h2 className="mb-4 text-sm font-semibold text-slate-700">Nova pergunta &amp; resposta</h2>
          <form action={formAction} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="question" className="text-sm font-medium text-slate-700">
                Pergunta <span className="text-red-500">*</span>
              </label>
              <input
                id="question"
                name="question"
                type="text"
                required
                placeholder="Ex: Qual é o horário de atendimento?"
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="answer" className="text-sm font-medium text-slate-700">
                Resposta <span className="text-red-500">*</span>
              </label>
              <textarea
                id="answer"
                name="answer"
                required
                rows={3}
                placeholder="Ex: Atendemos de segunda a sábado das 9h às 19h."
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
              />
            </div>
            {state?.error && (
              <p className="text-sm text-red-600">{state.error}</p>
            )}
            <div className="flex gap-2">
              <SubmitButton />
              {items.length > 0 && (
                <button
                  type="button"
                  onClick={() => setShowForm(false)}
                  className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
                >
                  Cancelar
                </button>
              )}
            </div>
          </form>
        </div>
      ) : (
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-2 self-start rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
            <path d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" />
          </svg>
          Nova pergunta
        </button>
      )}

      {/* List */}
      {items.length === 0 && !showForm ? (
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 py-12 text-center">
          <p className="text-sm text-slate-500">Nenhuma pergunta cadastrada ainda.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {items.map((item) => (
            <div
              key={item.id}
              className={`rounded-xl border bg-white p-5 transition ${item.is_active ? "border-slate-200" : "border-slate-100 opacity-60"}`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <p className="font-medium text-slate-900">{item.question}</p>
                  <p className="mt-1 text-sm text-slate-500">{item.answer}</p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {/* Toggle */}
                  <button
                    onClick={() => handleToggle(item.id, item.is_active)}
                    disabled={isPending}
                    title={item.is_active ? "Desativar" : "Ativar"}
                    className={`relative h-5 w-9 rounded-full transition ${item.is_active ? "bg-brand-600" : "bg-slate-300"} disabled:opacity-50`}
                  >
                    <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${item.is_active ? "left-4" : "left-0.5"}`} />
                  </button>
                  {/* Delete */}
                  <button
                    onClick={() => handleDelete(item.id)}
                    disabled={isPending}
                    title="Excluir"
                    className="rounded-md p-1 text-slate-400 hover:bg-red-50 hover:text-red-500 disabled:opacity-50"
                  >
                    <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                      <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clipRule="evenodd" />
                    </svg>
                  </button>
                </div>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <span className={`rounded-full px-2 py-0.5 text-xs ${item.is_active ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                  {item.is_active ? "Ativo" : "Inativo"}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
