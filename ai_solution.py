```typescript
return {
  apply: async (context) => {
    const { h } = context;
    const records = h.records || [];
    const memories = records.filter(r => r.kind === 'memory');
    const maxLength = h.config ? h.config.get('MEMORY_INJECTION_MAX_LENGTH') || 4000 : 4000;
    const num = h.config ? h.config.get('MEMORY_INJECTION_NUM') || 10 : 10;
    const session = h.session;
    const sessionId = session ? session.id : '';
    const entries = h.session ? session.entries : [];
    const now = Date.now();
    const state = {
      sessionId,
      entries,
      now,
      maxLength,
      num,
    };
    return state;
  },
};
```