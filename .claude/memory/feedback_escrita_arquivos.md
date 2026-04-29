---
name: Escrever arquivos Python via bash cat heredoc, não Write tool
description: O Write tool trunca arquivos Python longos no mount Windows do ZapAgent
type: feedback
---

Ao escrever arquivos Python com mais de ~80 linhas no projeto ZapAgent (montado no Windows), usar sempre `cat > caminho << 'PYEOF' ... PYEOF` via bash. O Write tool deixa bytes nulos no final que truncam o conteúdo quando o arquivo é lido pelo Python.

**Why:** Descoberto na sessão de 2026-04-28. O mount CIFS/Windows tem um comportamento de padding com \x00 que corrompe arquivos escritos pelo Write tool diretamente.

**How to apply:** Para qualquer arquivo Python > 60 linhas no ZapAgent, usar bash cat heredoc. Para arquivos curtos ou arquivos fora do ZapAgent, o Write tool é seguro.
