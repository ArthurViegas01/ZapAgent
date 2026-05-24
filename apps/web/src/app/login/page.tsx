"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { createClient } from "@/lib/supabase/client";

type Mode = "login" | "signup" | "reset";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState("");

  function switchMode(m: Mode) {
    setMode(m);
    setStatus("idle");
    setErrorMsg("");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setStatus("loading");
    setErrorMsg("");
    const supabase = createClient();

    if (mode === "reset") {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/auth/callback?next=/auth/update-password`,
      });
      if (error) { setStatus("error"); setErrorMsg(error.message); return; }
      setStatus("done");
      return;
    }

    if (mode === "login") {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) {
        setStatus("error");
        setErrorMsg(
          error.message === "Invalid login credentials"
            ? "E-mail ou senha incorretos."
            : error.message,
        );
        return;
      }
      router.push("/tenants");
      router.refresh();
      return;
    }

    // signup
    const { error } = await supabase.auth.signUp({ email, password });
    if (error) { setStatus("error"); setErrorMsg(error.message); return; }
    router.push("/onboarding");
    router.refresh();
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 px-6">
      <div className="flex items-center gap-2">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600">
          <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5 text-white" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
        </div>
        <span className="text-lg font-semibold tracking-tight">Encaixe</span>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        {mode === "reset" ? (
          <>
            <h1 className="text-xl font-semibold text-slate-900">Recuperar senha</h1>
            <p className="mt-1 text-sm text-slate-500">
              Enviaremos um link para redefinir sua senha.
            </p>

            {status === "done" ? (
              <div className="mt-6 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
                Link enviado para <strong>{email}</strong>. Verifique sua caixa de entrada.
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-4">
                <div className="flex flex-col gap-1.5">
                  <label className="text-sm font-medium text-slate-700" htmlFor="email">E-mail</label>
                  <input
                    id="email" type="email" required value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
                    placeholder="voce@empresa.com.br"
                  />
                </div>
                {status === "error" && (
                  <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{errorMsg}</div>
                )}
                <button type="submit" disabled={status === "loading"}
                  className="rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-brand-700 disabled:opacity-50">
                  {status === "loading" ? "Enviando..." : "Enviar link de recuperacao"}
                </button>
              </form>
            )}

            <button onClick={() => switchMode("login")}
              className="mt-4 w-full text-center text-sm text-brand-600 hover:underline">
              Voltar ao login
            </button>
          </>
        ) : (
          <>
            <div className="mb-6 flex rounded-lg border border-slate-200 bg-slate-50 p-1">
              {(["login", "signup"] as const).map((m) => (
                <button key={m} type="button" onClick={() => switchMode(m)}
                  className={`flex-1 rounded-md py-1.5 text-sm font-medium transition ${
                    mode === m ? "bg-white shadow text-slate-900" : "text-slate-500 hover:text-slate-700"
                  }`}>
                  {m === "login" ? "Entrar" : "Criar conta"}
                </button>
              ))}
            </div>

            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-sm font-medium text-slate-700" htmlFor="email">E-mail</label>
                <input
                  id="email" type="email" required value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
                  placeholder="voce@empresa.com.br"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-sm font-medium text-slate-700" htmlFor="password">Senha</label>
                <input
                  id="password" type="password" required minLength={8} value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
                  placeholder={mode === "signup" ? "Minimo 8 caracteres" : "Sua senha"}
                />
              </div>

              {mode === "login" && (
                <div className="flex justify-end">
                  <button type="button" onClick={() => switchMode("reset")}
                    className="text-xs text-slate-500 hover:text-brand-600 hover:underline">
                    Esqueci minha senha
                  </button>
                </div>
              )}

              {status === "error" && (
                <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{errorMsg}</div>
              )}

              <button type="submit" disabled={status === "loading"}
                className="mt-1 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-brand-700 disabled:opacity-50">
                {status === "loading" ? "Aguarde..." : mode === "login" ? "Entrar" : "Criar conta"}
              </button>
            </form>
          </>
        )}
      </div>
    </main>
  );
}
