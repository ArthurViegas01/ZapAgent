---
name: Usar sys.modules para patch de nós LangGraph
description: nodes/__init__.py sombra os módulos de nós; usar sys.modules para patch.object
type: feedback
---

Em `apps/api/src/agent/nodes/__init__.py`, os nós são re-exportados com `from .retrieve_context import retrieve_context`. Isso faz com que `import src.agent.nodes.retrieve_context as m` retorne a **função**, não o módulo.

Para mockar funções internas (ex: `_embed`, `AsyncAnthropic`) nos testes, usar:
```python
import src.agent.nodes  # carrega tudo em sys.modules
_rc_mod = sys.modules["src.agent.nodes.retrieve_context"]
# depois: _rc_mod._embed = AsyncMock(...)  ou patch.object(_rc_mod, ...)
```

**Why:** Descoberto na sessão 2026-04-28. `patch("src.agent.nodes.retrieve_context._embed")` falha porque resolve pelo chain de atributos, não por sys.modules.

**How to apply:** Em qualquer teste que precise mockar internals de nós do LangGraph neste projeto.
