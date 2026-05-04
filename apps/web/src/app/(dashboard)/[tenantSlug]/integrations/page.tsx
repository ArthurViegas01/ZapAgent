"use client";

import { useEffect, useState, useTransition } from "react";

import { createWhatsappInstance, disconnectWhatsapp, pollWhatsappStatus, startGoogleCalendarOAuth, disconnectGoogleCalendar } from "./actions";

interface Props {
  params: { tenantSlug: string };
}

interface Integration {
  status: string;
  external_id: string | null;
  config: { qrcode?: string; instance_name?: string } | null;
}

export default function IntegrationsPage({ params }: Props) {
  const { tenantSlug } = params;
  const [integration, setIntegration] = useState<Integration | null>(null);
  const [tenantId, setTenantId] = useState("");
  const [qrcode, setQrcode] = useState("");
  const [instanceName, setInstanceName] = useState("");
  const [error, setError] = useState("");
  const [isPending, startTransition] = useTransition();
  const [polling, setPolling] = useState(false);
  const [gcalStatus, setGcalStatus] = useState<"unknown" | "connected" | "revoked">("unknown");
  const [gcalEmail, setGcalEmail] = useState("");
  const [gcalPending, setGcalPending] = useState(false);

  useEffect(() => {
    async function load() {
      const res = await fetch(`/api/tenants/${tenantSlug}/integration`);
      // Load Google Calendar status
      const gcalRes = await fetch(`/api/tenants/${tenantSlug}/gcal-integration`);
      if (gcalRes.ok) {
        const gcalData = await gcalRes.json();
        setGcalStatus(gcalData.status ?? "revoked");
        setGcalEmail(gcalData.email ?? "");
      }

      if (res.ok) {
        const data = await res.json();
        setIntegration(data.integration);
        setTenantId(data.tenantId);
        if (data.integration?.status === "pending" && data.integration?.config?.qrcode) {
          setQrcode(data.integration.config.qrcode);
          setInstanceName(data.integration.external_id ?? "");
          setPolling(true);
        }
      }
    }
    load();
  }, [tenantSlug]);

  // Poll for QR code and connection status every 4s while pending
  useEffect(() => {
    if (!polling || !tenantId) return;
    const id = setInterval(async () => {
      const data = await pollWhatsappStatus(tenantId);
      if (data.status === "connected") {
        setIntegration((p) => p ? { ...p, status: "connected" } : null);
        setQrcode("");
        setPolling(false);
      } else if (data.qrcode) {
        setQrcode(data.qrcode);
      }
    }, 4000);
    return () => clearInterval(id);
  }, [polling, tenantId]);

  function handleConnect() {
    setError("");
    startTransition(async () => {
      const res = await createWhatsappInstance(tenantId, tenantSlug);
      if ("error" in res && res.error) { setError(res.error); return; }
      setQrcode(res.qrcode ?? "");
      setInstanceName(res.instanceName ?? "");
      setPolling(true);
    });
  }

  function handleDisconnect() {
    startTransition(async () => {
      await disconnectWhatsapp(tenantId, tenantSlug, instanceName || integration?.external_id || "");
      setIntegration((p) => p ? { ...p, status: "revoked" } : null);
      setQrcode("");
      setPolling(false);
    });
  }

  async function handleGcalConnect() {
    setGcalPending(true);
    const result = await startGoogleCalendarOAuth(tenantId, tenantSlug);
    if ("error" in result) { setError(result.error); setGcalPending(false); return; }
    window.location.href = result.url;
  }

  async function handleGcalDisconnect() {
    setGcalPending(true);
    await disconnectGoogleCalendar(tenantId, tenantSlug);
    setGcalStatus("revoked");
    setGcalEmail("");
    setGcalPending(false);
  }

  const isConnected = integration?.status === "connected";
  const isPending2 = integration?.status === "pending";

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">Integrações</h1>
        <p className="text-sm text-slate-500">Conecte seu número de WhatsApp ao agente.</p>
      </header>

      {/* WhatsApp card */}
      <div className="rounded-xl border border-slate-200 bg-white p-6">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            {/* WhatsApp icon */}
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-500">
              <svg viewBox="0 0 24 24" fill="white" className="h-7 w-7">
                <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/>
                <path d="M12 0C5.373 0 0 5.373 0 12c0 2.125.558 4.126 1.536 5.862L0 24l6.296-1.513A11.94 11.94 0 0012 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 22c-1.93 0-3.737-.5-5.31-1.376l-.38-.224-3.935.945.99-3.84-.247-.396A9.962 9.962 0 012 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10z"/>
              </svg>
            </div>
            <div>
              <p className="font-semibold text-slate-900">WhatsApp Business</p>
              <p className="text-sm text-slate-500">
                {isConnected
                  ? `Conectado · ${integration?.external_id}`
                  : qrcode
                  ? "Aguardando leitura do QR Code…"
                  : polling
                  ? "Gerando QR Code…"
                  : "Não conectado"}
              </p>
            </div>
          </div>

          {/* Status badge */}
          <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${
            isConnected ? "bg-emerald-100 text-emerald-700" :
            (qrcode || polling) ? "bg-amber-100 text-amber-700" :
            "bg-slate-100 text-slate-600"
          }`}>
            {isConnected ? "Conectado" : (qrcode || polling) ? "Pendente" : "Desconectado"}
          </span>
        </div>

        {/* QR Code area — shown while pending (spinner before QR arrives, image after) */}
        {(polling || qrcode) && !isConnected && (
          <div className="mt-6 flex flex-col items-center gap-4 rounded-xl bg-slate-50 p-6">
            {qrcode ? (
              <>
                <p className="text-sm font-medium text-slate-700">
                  Abra o WhatsApp → Dispositivos conectados → Conectar dispositivo
                </p>
                <div className="rounded-xl bg-white p-3 shadow-sm">
                  {qrcode.startsWith("data:image") ? (
                    <img src={qrcode} alt="QR Code WhatsApp" className="h-52 w-52" />
                  ) : (
                    <div className="flex h-52 w-52 items-center justify-center">
                      <p className="text-center text-xs text-slate-400 break-all">{qrcode}</p>
                    </div>
                  )}
                </div>
                <p className="text-xs text-slate-400">Verificando conexão automaticamente…</p>
              </>
            ) : (
              /* QR not yet delivered by webhook — show spinner */
              <div className="flex flex-col items-center gap-3 py-8">
                <svg className="h-8 w-8 animate-spin text-emerald-500" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <p className="text-sm text-slate-500">Aguardando QR Code do WhatsApp…</p>
              </div>
            )}
          </div>
        )}

        {/* Success state */}
        {isConnected && (
          <div className="mt-4 flex items-center gap-2 rounded-lg bg-emerald-50 px-4 py-3">
            <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5 text-emerald-500">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clipRule="evenodd" />
            </svg>
            <p className="text-sm text-emerald-700">WhatsApp conectado! O agente já está recebendo mensagens.</p>
          </div>
        )}

        {error && (
          <div className="mt-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        )}

        {/* Actions */}
        <div className="mt-5 flex gap-3">
          {!isConnected && !qrcode && !polling && (
            <button
              onClick={handleConnect}
              disabled={isPending || !tenantId}
              className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              {isPending ? "Aguarde…" : "Conectar WhatsApp"}
            </button>
          )}
          {(isConnected || qrcode || polling) && (
            <button
              onClick={handleDisconnect}
              disabled={isPending}
              className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            >
              Desconectar
            </button>
          )}
        </div>
      </div>

      {/* Google Calendar card */}
      <div className="rounded-xl border border-slate-200 bg-white p-6">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50">
              <svg viewBox="0 0 24 24" fill="none" className="h-7 w-7" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
              </svg>
            </div>
            <div>
              <p className="font-semibold text-slate-900">Google Calendar</p>
              <p className="text-sm text-slate-500">
                {gcalStatus === "connected"
                  ? `Conectado${gcalEmail ? " · " + gcalEmail : ""}`
                  : "Agendamentos automaticos no seu calendario."}
              </p>
            </div>
          </div>
          <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${
            gcalStatus === "connected" ? "bg-blue-100 text-blue-700" : "bg-slate-100 text-slate-500"
          }`}>
            {gcalStatus === "connected" ? "Conectado" : "Desconectado"}
          </span>
        </div>

        {gcalStatus === "connected" && (
          <div className="mt-4 flex items-center gap-2 rounded-lg bg-blue-50 px-4 py-3">
            <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5 text-blue-500">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clipRule="evenodd" />
            </svg>
            <p className="text-sm text-blue-700">Agendamentos serao criados automaticamente no Google Calendar.</p>
          </div>
        )}

        {gcalStatus !== "connected" && (
          <div className="mt-4 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">
            <strong>Antes de conectar:</strong> o app está em modo de testes no Google.{" "}
            <a
              href="https://console.cloud.google.com/apis/credentials/consent"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:no-underline"
            >
              Adicione seu e-mail como usuário de teste
            </a>{" "}
            na tela de consentimento OAuth do Google Cloud Console.
          </div>
        )}
        <div className="mt-4 flex gap-3">
          {gcalStatus !== "connected" ? (
            <button onClick={handleGcalConnect} disabled={gcalPending || !tenantId}
              className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              {gcalPending ? "Aguarde..." : "Conectar Google Calendar"}
            </button>
          ) : (
            <button onClick={handleGcalDisconnect} disabled={gcalPending}
              className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50">
              Desconectar
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
