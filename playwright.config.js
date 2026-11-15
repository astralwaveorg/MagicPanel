import { defineConfig, devices } from '@playwright/test'

if (process.argv.includes('--fixture-server')) {
  const [{ createServer }, { default: vue }] = await Promise.all([
    import('vite'), import('@vitejs/plugin-vue'),
  ])
  const server = await createServer({
    configFile: false,
    plugins: [vue(), {
      name: 'isolated-download-fixture',
      configureServer(vite) {
        vite.middlewares.use((req, res, next) => {
          if (req.url?.startsWith('/api/')) {
            res.statusCode = 503
            res.end('Test API must be intercepted')
          } else if (req.url?.startsWith('/feed/')) {
            // Chromium下载会再次取文件，不能让它落到开发后端代理。
            if (new URL(req.url, 'http://127.0.0.1:7108').pathname !== '/feed/fixture-only/config.yaml') {
              res.statusCode = 404
              res.end()
              return
            }
            res.setHeader('Content-Type', 'application/yaml')
            res.setHeader('Content-Disposition', 'attachment')
            res.end('mode: rule\n')
          } else next()
        })
      },
    }],
    server: { host: '127.0.0.1', port: 7108, strictPort: true },
  })
  await server.listen()
}

export default defineConfig({
  testDir: 'e2e/v2',
  outputDir: 'tmp/playwright-results',
  forbidOnly: true,
  workers: 2,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:7108',
    trace: 'off', screenshot: 'off', video: 'off',
  },
  webServer: {
    command: 'node playwright.config.js --fixture-server',
    url: 'http://127.0.0.1:7108',
    reuseExistingServer: false,
  },
  projects: [
    { name: 'desktop', use: { browserName: 'chromium', viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } },
  ],
})
