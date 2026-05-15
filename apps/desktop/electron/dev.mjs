import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const host = "127.0.0.1";
const defaultPort = 5173;
const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const viteBin = join(appRoot, "node_modules", "vite", "bin", "vite.js");
const electronBin =
  process.platform === "win32"
    ? join(appRoot, "node_modules", "electron", "dist", "electron.exe")
    : join(appRoot, "node_modules", ".bin", "electron");

const port = await findAvailablePort(host, defaultPort);
const devServerUrl = `http://${host}:${port}`;

const vite = spawn(process.execPath, [viteBin, "--host", host, "--port", String(port)], {
  cwd: appRoot,
  env: process.env,
  stdio: "inherit",
});

vite.on("error", (error) => {
  console.error(`Failed to start Vite dev server with ${process.execPath}:`, error);
  process.exit(1);
});

try {
  await waitForPortOrExit(vite, host, port);
} catch (error) {
  console.error(error.message);
  vite.kill();
  process.exit(1);
}

const electron = spawn(electronBin, ["."], {
  cwd: appRoot,
  env: {
    ...process.env,
    VITE_DEV_SERVER_URL: devServerUrl,
  },
  stdio: "inherit",
});

electron.on("error", (error) => {
  console.error(`Failed to start Electron with ${electronBin}:`, error);
  vite.kill();
  process.exit(1);
});

function shutdown() {
  electron.kill();
  vite.kill();
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

electron.on("exit", (code) => {
  vite.kill();
  process.exit(code ?? 0);
});

vite.on("exit", (code) => {
  if (code && code !== 0) {
    electron.kill();
    process.exit(code);
  }
});

async function findAvailablePort(targetHost, startPort) {
  for (let candidate = startPort; candidate < startPort + 20; candidate += 1) {
    if (await isPortAvailable(targetHost, candidate)) {
      if (candidate !== startPort) {
        console.warn(`Vite 默认端口 ${startPort} 已被占用，改用 ${candidate}。`);
      }
      return candidate;
    }
  }

  throw new Error(`无法找到可用的 Vite 开发端口，请释放 ${startPort}-${startPort + 19} 后重试。`);
}

function isPortAvailable(targetHost, targetPort) {
  return new Promise((resolve, reject) => {
    const server = createServer();

    server.once("error", (error) => {
      if (error.code === "EADDRINUSE") {
        resolve(false);
        return;
      }
      reject(error);
    });

    server.once("listening", () => {
      server.close(() => resolve(true));
    });

    server.listen(targetPort, targetHost);
  });
}

function waitForPortOrExit(childProcess, targetHost, targetPort) {
  let waiting = true;
  const exited = new Promise((_, reject) => {
    childProcess.once("exit", (code, signal) => {
      if (!waiting) {
        return;
      }
      const reason = signal ? `信号 ${signal}` : `退出码 ${code ?? 0}`;
      reject(new Error(`Vite 开发服务器启动失败（${reason}）。请查看上方日志后重试。`));
    });
  });

  return Promise.race([waitForPort(targetHost, targetPort), exited]).finally(() => {
    waiting = false;
  });
}

function waitForPort(targetHost, targetPort) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + 30_000;

    const attempt = () => {
      const socket = createServer();

      socket.once("error", (error) => {
        if (error.code === "EADDRINUSE") {
          resolve();
          return;
        }

        if (Date.now() > deadline) {
          reject(error);
          return;
        }

        setTimeout(attempt, 250);
      });

      socket.once("listening", () => {
        socket.close(() => {
          if (Date.now() > deadline) {
            reject(new Error(`Timed out waiting for ${targetHost}:${targetPort}`));
            return;
          }

          setTimeout(attempt, 250);
        });
      });

      socket.listen(targetPort, targetHost);
    };

    attempt();
  });
}
