// Unified dev launcher — replaces start_dev.bat.
//   npm run dev                 start Docker infra + backend + frontend
//   npm run dev -- --no-open    same, but do not open the browser
//   npm run dev:backend         backend only (uvicorn --reload)
//   npm run dev:frontend        frontend only (vite)
import { spawn, exec } from 'node:child_process';
import { existsSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BACKEND_PORT = 8001;
const FRONTEND_PORT = 3000;

const args = process.argv.slice(2);
const backendOnly = args.includes('--backend-only');
const frontendOnly = args.includes('--frontend-only');
const noOpen = args.includes('--no-open');

const isWindows = process.platform === 'win32';
const python = existsSync(path.join(ROOT, '.venv', 'Scripts', 'python.exe'))
  ? path.join(ROOT, '.venv', 'Scripts', 'python.exe')
  : 'python';
const npmCmd = isWindows ? 'npm.cmd' : 'npm';

const log = (msg) => console.log(`\x1b[36m[dev]\x1b[0m ${msg}`);
const warn = (msg) => console.log(`\x1b[33m[dev]\x1b[0m ${msg}`);
const error = (msg) => console.error(`\x1b[31m[dev]\x1b[0m ${msg}`);
const section = (label) => console.log(`\n\x1b[1m== ${label} ==\x1b[0m\n`);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForTcp(host, port, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await isPortListening(port)) return;
    await sleep(1000);
  }
  throw new Error(`Port ${port} not ready within ${timeoutMs}ms`);
}

async function waitForHttp(url, timeoutMs = 60000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.ok) return true;
    } catch { /* retry */ }
    await sleep(1000);
  }
  throw new Error(`${url} not reachable within ${timeoutMs}ms`);
}

function isPortListening(port) {
  return new Promise((resolve) => {
    const s = net.createConnection({ host: '127.0.0.1', port });
    s.once('connect', () => { s.destroy(); resolve(true); });
    s.once('error', () => resolve(false));
    setTimeout(() => { s.destroy(); resolve(false); }, 1500).unref();
  });
}

function run(cmd, args, opts = {}) {
  let command = cmd;
  let cmdArgs = args;
  // On Windows, .cmd/.bat launchers (e.g. npm.cmd) cannot be spawned directly
  // with shell:false (EINVAL), and shell:true emits DEP0190. Route them
  // through cmd.exe instead.
  if (isWindows && /\.(cmd|bat)$/i.test(cmd)) {
    command = 'cmd.exe';
    cmdArgs = ['/d', '/s', '/c', [cmd, ...args].join(' ')];
  }
  const child = spawn(command, cmdArgs, { stdio: 'inherit', shell: false, ...opts });
  child.on('error', (err) => {
    error(`${cmd} failed to start: ${err.message}`);
    shutdown();
  });
  return child;
}

const children = [];
function shutdown(code = 0) {
  for (const child of children) {
    if (child && !child.killed) {
      try { child.kill(); } catch { /* ignore */ }
    }
  }
  process.exit(code);
}

function openBrowser(url) {
  if (noOpen) return;
  try {
    if (isWindows) {
      exec(`start "" "${url}"`, { shell: true });
    } else if (process.platform === 'darwin') {
      exec(`open "${url}"`);
    } else {
      exec(`xdg-open "${url}"`);
    }
  } catch {
    warn(`Could not auto-open ${url}, please open it manually.`);
  }
}

function runCapture(cmd, args, opts = {}) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { ...opts, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    child.stdout?.on('data', (d) => { output += d; });
    child.stderr?.on('data', (d) => { output += d; });
    child.on('close', (code) => resolve({ code, output }));
    child.on('error', () => resolve({ code: -1, output: '' }));
  });
}

async function composeUp() {
  let result = await runCapture('docker', ['compose', 'up', '-d'], { cwd: ROOT });
  if (result.code === 0) return true;

  // Heal stale containers that were created by another compose project but
  // collide with the fixed container_name in docker-compose.yml.
  const conflicts = [...result.output.matchAll(/name "([^"]+)" is already in use/g)].map((m) => m[1]);
  const unique = [...new Set(conflicts)];
  if (unique.length > 0) {
    warn(`检测到同名容器冲突（来自其他 compose 项目），正在移除占名容器以便重建: ${unique.join(', ')}`);
    for (const name of unique) {
      await runCapture('docker', ['rm', '-f', name]);
    }
    result = await runCapture('docker', ['compose', 'up', '-d'], { cwd: ROOT });
    if (result.code === 0) return true;
  }
  error(`docker compose up 失败:\n${result.output}`);
  return false;
}

async function ensureDockerInfra() {
  section('1/3  Docker 基础设施 (PostgreSQL + Redis)');
  const dockerInfo = await runCapture('docker', ['info']);
  if (dockerInfo.code !== 0) {
    warn('Docker 未运行或未安装，跳过 PostgreSQL/Redis 启动（请确认已手动启动，否则后端无法连库）。');
    return;
  }
  if (!(await composeUp())) return;
  try {
    await waitForTcp('127.0.0.1', 5433);
    log('PostgreSQL 就绪 (127.0.0.1:5433)');
  } catch {
    warn('PostgreSQL 未就绪，后端可能启动失败；请检查 docker compose logs。');
  }
}

async function startBackend() {
  section('2/3  后端 (FastAPI)');
  const busy = await isPortListening(BACKEND_PORT);
  if (busy) {
    error(`端口 ${BACKEND_PORT} 已被占用，请先停止占用进程再启动后端。`);
    return null;
  }
  log(`python -m uvicorn app.main:app --port ${BACKEND_PORT} --reload`);
  const child = run(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(BACKEND_PORT), '--reload'], { cwd: ROOT });
  children.push(child);
  return child;
}

async function startFrontend() {
  section('3/3  前端 (React + Vite)');
  const busy = await isPortListening(FRONTEND_PORT);
  if (busy) {
    error(`端口 ${FRONTEND_PORT} 已被占用，请先停止占用进程再启动前端。`);
    return null;
  }
  log('npm run dev (frontend)');
  const child = run(npmCmd, ['run', 'dev'], { cwd: path.join(ROOT, 'frontend') });
  children.push(child);
  return child;
}

async function main() {
  process.on('SIGINT', () => shutdown(130));
  process.on('SIGTERM', () => shutdown(143));

  section('患者医疗信息 Agent — 开发启动');
  log(`工作目录: ${ROOT}`);
  log(`Python: ${python}`);

  if (backendOnly || frontendOnly) {
    if (backendOnly) {
      await startBackend();
    } else {
      await startFrontend();
    }
    // Keep running until Ctrl+C
    await new Promise(() => {});
    return;
  }

  await ensureDockerInfra();

  const backend = await startBackend();
  if (backend) {
    try {
      await waitForHttp(`http://localhost:${BACKEND_PORT}/health`);
      log(`后端就绪 http://localhost:${BACKEND_PORT}/health`);
    } catch {
      error('后端未能就绪，请检查上方后端日志。');
    }
  }

  const frontend = await startFrontend();
  if (frontend) {
    try {
      await waitForHttp(`http://localhost:${FRONTEND_PORT}`);
      const url = `http://localhost:${FRONTEND_PORT}`;
      log(`前端就绪 ${url}`);
      openBrowser(url);
    } catch {
      error('前端未能就绪，请检查上方前端日志。');
    }
  }

  log('服务已启动。Ctrl+C 停止全部服务。');
  await new Promise(() => {});
}

main().catch((err) => {
  error(err.message);
  shutdown(1);
});
