import Link from "next/link";

export default function NotFound() {
  return (
    <html lang="pt-BR">
      <body className="flex h-screen items-center justify-center bg-slate-50">
        <div className="text-center">
          <p className="text-sm font-medium text-brand-600">404</p>
          <h1 className="mt-2 text-2xl font-semibold text-slate-900">Página não encontrada</h1>
          <p className="mt-2 text-sm text-slate-500">O recurso que você procurou não existe.</p>
          <Link
            href="/"
            className="mt-6 inline-block rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            Voltar
          </Link>
        </div>
      </body>
    </html>
  );
}
