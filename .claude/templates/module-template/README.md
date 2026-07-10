# Module Template

Reference scaffold mirroring the fixed backend module shape defined in
`.claude/rules/backend.md` and `docs/business/RAAD_Phase3.1_Backend_LLD_v1_2.md` §1. Use
`/create-module <context-name>` (`.claude/commands/create-module.md`) rather than copying this
directory by hand, so the module name is validated against the ten approved bounded contexts first.

```
<context>/
├── __init__.py        # module facade — the ONLY public surface other modules may import
├── api/
│   ├── routers.py
│   ├── schemas.py
│   └── ws.py           # only if the module serves realtime data
├── application/
│   ├── services.py
│   ├── commands.py
│   ├── queries.py
│   └── ports.py
├── domain/
│   ├── entities.py
│   ├── value_objects.py
│   ├── events.py
│   ├── services.py
│   ├── policies.py
│   └── repositories.py
├── infra/
│   ├── models.py
│   ├── repositories.py
│   ├── adapters.py
│   └── mappers.py
└── events/
    ├── publishers.py
    └── subscribers.py
```
