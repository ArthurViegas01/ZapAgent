"use client";

import { useEffect, useState } from "react";
import { useFormState, useFormStatus } from "react-dom";

import { createTenant } from "./actions";

const BUSINESS_TYPES = [
  { value: "", label: "Selecione o tipo de negocio" },
  { value: "clinic", label: "Clinica / Consultorio" },
  { value: "barbershop", label: "Barbearia / Salao" },
  { value: "restaurant", label: "Restaurante / Delivery" },
  { value: "school", label: "Escola / Curso" },
  { value: "law", label: "Escritorio de Advocacia" },
  { value: "real_estate", label: "Imobiliaria" },
  { value: "other", label: "Outro" },
];

function slugify(name: string) {
  return name
    .toLowerCase()
    .replace(/[aáâãäå]/g, "a")
    .replace(/[eéêë]/g, "e")
    .replace(/[iíîï]/g, "i")
    .replace(/[oóôõö]/g, "o")
    .replace(/[uúûü]/g, "u")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {pending ? (
        <>
          <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Criando empresa...
        </>
      ) : (
        "Continuar"
      )}
    </button>
  );
}

export default function OnboardingPage() {
  const [state, formAction] = useFormState(createTenant, null);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);

  // When server action returns a slug, navigate client-side to the dashboard
  useEffect(() => {
    if (state?.slug) {
      window.location.href = `/${state.slug}`;
    }
  }, [state?.slug]);

  function handleNameChange(v: string) {
    setName(v);
    if (!slugEdited) setSlug(slugify(v));
  }

  function handleSlugChange(v: string) {
    setSlugEdited(true);
    setSlug(v.toLowerCase().replace(/[^a-z0-9-]/g, ""));
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-lg">
        {/* Logo */}
        <div className="mb-8 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600">
            <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5 text-white" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
            </svg>
          </div>
          <span className="text-lg font-semibold tracking-tight">ZapAgent</span>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
          {/* Progress bar */}
          <div className="mb-6 flex items-center gap-2">
            <div className="h-1.5 flex-1 rounded-full bg-brand-600" />
            <div className="h-1.5 flex-1 rounded-full bg-slate-200" />
            <div className="h-1.5 flex-1 rounded-full bg-slate-200" />
          </div>

          <h1 className="text-xl font-semibold text-slate-900">Crie sua empresa</h1>
          <p className="mt-1 text-sm text-slate-500">
            Essas informacoes personalizam o atendente para seus clientes.
          </p>

          <form action={formAction} className="mt-6 flex flex-col gap-4">
            {/* Nome */}
            <div className="flex flex-col gap-1.5">
              <label htmlFor="name" className="text-sm font-medium text-slate-700">
                Nome da empresa <span className="text-red-500">*</span>
              </label>
              <input
                id="name"
                name="name"
                type="text"
                required
                value={name}
                onChange={(e) => handleNameChange(e.target.value)}
                placeholder="Ex: Clinica Bem Estar"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
              />
            </div>

            {/* Slug */}
            <div className="flex flex-col gap-1.5">
              <label htmlFor="slug" className="text-sm font-medium text-slate-700">
                Identificador (slug)
              </label>
              <div className="flex items-center rounded-lg border border-slate-300 px-3 py-2 text-sm transition focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-100">
                <span className="select-none text-slate-400">app/</span>
                <input
                  id="slug"
                  name="slug"
                  type="text"
                  value={slug}
                  onChange={(e) => handleSlugChange(e.target.value)}
                  placeholder="clinica-bem-estar"
                  className="flex-1 bg-transparent outline-none"
                />
              </div>
              <p className="text-xs text-slate-400">
                Gerado automaticamente. Apenas letras minusculas, numeros e hifens.
              </p>
            </div>

            {/* Tipo de negocio */}
            <div className="flex flex-col gap-1.5">
              <label htmlFor="business_type" className="text-sm font-medium text-slate-700">
                Tipo de negocio
              </label>
              <select
                id="business_type"
                name="business_type"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
              >
                {BUSINESS_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>

            {/* Error (only show when no slug returned) */}
            {state?.error && !state.slug && (
              <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
                {state.error}
              </div>
            )}

            <SubmitButton />
          </form>
        </div>

        <p className="mt-4 text-center text-xs text-slate-400">
          Voce podera alterar esses dados depois em Configuracoes.
        </p>
      </div>
    </main>
  );
}
