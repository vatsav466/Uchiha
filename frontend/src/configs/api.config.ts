// api.config.ts
//
// All environments use a relative base path so requests go to the same
// origin the browser loaded the page from. Nginx on :5378 proxies
// /api/* → FastAPI on :8002 inside the container.
//
// Do NOT use a hardcoded host:port — it breaks every environment except
// the machine it was written for.

export const API_CONFIG = {
  development: '/api',
  staging: '/api',
  production: '/api',
};
