# Como configurar o Google Calendar

## Passo a passo (5 minutos)

### 1. Criar projeto no Google Cloud

1. Acesse https://console.cloud.google.com
2. Clique em **"Novo projeto"** → dê um nome (ex: Encaixe) → Criar
3. No menu lateral: **APIs e Servicos → Biblioteca**
4. Pesquise **"Google Calendar API"** → Ativar

### 2. Configurar tela de consentimento OAuth

1. Menu lateral: **APIs e Servicos → Tela de permissao OAuth**
2. Tipo: **Externo** → Criar
3. Preencha: Nome do app (Encaixe), email de suporte
4. Em "Escopos": adicionar `../auth/calendar.events`
5. Em "Usuarios de teste": adicionar seu email
6. Salvar

### 3. Criar credenciais OAuth

1. Menu lateral: **APIs e Servicos → Credenciais**
2. **Criar credenciais → ID do cliente OAuth**
3. Tipo: **Aplicativo da Web**
4. Nome: Encaixe
5. URIs de redirecionamento autorizados:
   - Desenvolvimento: `http://localhost:3000/auth/google-calendar/callback`
   - Producao: `https://seudominio.com/auth/google-calendar/callback`
6. Clique em **Criar**
7. Copie o **ID do cliente** e o **Segredo do cliente**

### 4. Adicionar ao .env

```env
# apps/web/.env.local
GOOGLE_OAUTH_CLIENT_ID=xxxxxxxxxx.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxx
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:3000/auth/google-calendar/callback



# apps/api/.env
GOOGLE_OAUTH_CLIENT_ID=xxxxxxxxxx.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxx
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:3000/auth/google-calendar/callback
```

### 5. Rodar a migration de RLS

```bash
psql $DATABASE_URL -f db/migrations/0002_fix_rls_for_js_client.sql
```

### Sem Google Calendar?

O agendamento funciona sem o Google Calendar — os agendamentos sao salvos
no banco normalmente e aparecem no dashboard. O evento do calendario e um
bonus. Simplesmente nao conecte a integracao.
