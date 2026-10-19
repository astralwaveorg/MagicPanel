/* 本地开发：同时启动 FastAPI（8000）与 Vite（7100），CLI 参数透传给 Vite。 */
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const venvPython = path.join(root, '.venv', 'bin', 'python')
const python = fs.existsSync(venvPython) ? venvPython : 'python3'

const procs = []
function run(name, cmd, args, cwd) {
  const p = spawn(cmd, args, { cwd, stdio: 'inherit', env: process.env })
  p.on('exit', (code) => {
    if (!shuttingDown) {
      console.log(`[dev] ${name} 已退出（${code}），正在停止另一个进程`)
      shutdown(code ?? 0)
    }
  })
  procs.push(p)
}

let shuttingDown = false
function shutdown(code) {
  shuttingDown = true
  for (const p of procs) p.kill('SIGTERM')
  setTimeout(() => process.exit(code), 300)
}
process.on('SIGINT', () => shutdown(0))
process.on('SIGTERM', () => shutdown(0))

run('api', python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'],
  path.join(root, 'server'))
run('web', process.execPath,
  [path.join(root, 'node_modules', 'vite', 'bin', 'vite.js'), ...process.argv.slice(2)], root)
