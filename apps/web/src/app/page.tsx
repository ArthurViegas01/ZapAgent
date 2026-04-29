import Link from "next/link";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col justify-center gap-6 px-6 py-16">
      <p className="text-sm font-medium uppercase tracking-widest text-brand-600">
        ZapAgent
      </p>
      <h1 className="text-4xl font-semibold tracking-tight">
        Seu atendente no WhatsApp,{" "}
        <span className="text-brand-600">24 horas por dia</span>.
      </h1>
      <p className="text-lg text-slate-600">
        Responde dúvidas, agenda no Google Calendar e chama você quando
        precisa de ajuda. Sem app novo, sem treinamento — funciona no número
        da sua empresa.
      </p>
      <div className="flex gap-3">
        <Link
          href="/signup"
          className="rounded-md bg-brand-600 px-5 py-2.5 text-sm font-medium text-white shadow hover:bg-brand-700"
        >
          Começar agora
        </Link>
        <Link
          href="/login"
          className="rounded-md border border-slate-300 px-5 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
        >
          Já tenho conta
        </Link>
      </div>
    </main>
  );
}
