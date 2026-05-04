"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { createClient } from "@/lib/supabase/client";

export default function UpdatePasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setStatus("error");
      setErrorMsg("As senhas nao coincidem.");
      return;
    }
    setStatus("loading");
    const supabase = createClient();
    const { error } = await supabase.auth.updateUser({ password });
    if (error) { setStatus("error"); setErrorMsg(error.message); return; }
    setStatus("done");
    setTimeout(() => router.push("/tenants"), 2000);
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 px-6">
      <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-xl font-semibold text-slate-900">Nova senha</h1>
        <p className="mt-1 text-sm text-slate-500">Escolha uma senha segura para sua conta.</p>

        {status === "done" ? (
          <div className="mt-6 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            Senha atualizada! Redirecionando...
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium text-slate-700" htmlFor="pw">Nova senha</label>
              <input id="pw" type="password" required minLength={8} value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
                placeholder="Minimo 8 caracteres" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium text-slate-700" htmlFor="confirm">Confirmar senha</label>
              <input id="confirm" type="password" required minLength={8} value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
                placeholder="Repita a nova senha" />
            </div>
            {status === "error" && (
              <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{errorMsg}</div>
            )}
            <button type="submit" disabled={status === "loading"}
              className="rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-brand-700 disabled:opacity-50">
              {status === "loading" ? "Salvando..." : "Salvar nova senha"}
            </button>
          </form>
        )}
      </div>
    </main>
  );
}
