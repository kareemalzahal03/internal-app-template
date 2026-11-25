import { defineConfig } from '@hey-api/openapi-ts'

// openapi.json is dumped from the app; the output is committed.
export default defineConfig({
  input: 'openapi.json',
  output: 'src/lib/api',
  plugins: [
    // Relative paths, so every call stays same-origin.
    { name: '@hey-api/client-fetch', baseUrl: '' },
    // Generated queryOptions/mutationOptions, so no page hand-writes a queryKey.
    {
      name: '@tanstack/react-query',
      queryOptions: true,
      mutationOptions: true,
      queryKeys: true,
    },
  ],
})
